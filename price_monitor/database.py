from __future__ import annotations

import json
import csv
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import (
    DB_BACKEND,
    DB_PATH,
    DEMO_MODE,
    MYSQL_SETTINGS,
    REAL_DATA_PATH,
    MySQLSettings,
)


PRODUCTS = {
    "gasoil": {"label": "Gasoil / diesel", "unit": "USD/gallon", "color": "#5eead4"},
    "brent": {"label": "Pétrole Brent", "unit": "USD/baril", "color": "#f9b35c"},
    "bitume": {"label": "Bitume", "unit": "USD/tonne", "color": "#a78bfa"},
}


SCHEMA = """
CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL CHECK(product IN ('gasoil', 'brent', 'bitume')),
    price REAL NOT NULL CHECK(price > 0),
    unit TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    source TEXT NOT NULL,
    source_date TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    variation REAL,
    variation_pct REAL,
    is_unchanged INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_observations_product_date
  ON price_observations(product, collected_at);
CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    label TEXT NOT NULL,
    provider TEXT NOT NULL,
    frequency TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    last_success_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS collection_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    rows_collected INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);
"""


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MYSQL_SCHEMA_PATH = PROJECT_ROOT / "sql" / "mysql_schema.sql"
MYSQL_MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "mysql_migrations"
MYSQL_SCHEMA = MYSQL_SCHEMA_PATH.read_text(encoding="utf-8")


class DatabaseBackend(Protocol):
    """Persistence contract shared by the SQLite and MySQL implementations."""

    def insert_observation(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def log_collection(self, status: str, rows: int, message: str, started_at: str, finished_at: str) -> None: ...

    def latest(self) -> list[dict[str, Any]]: ...

    def observations(self, product: str | None = None, days: int = 30, limit: int = 600) -> list[dict[str, Any]]: ...

    def dashboard(self, days: int = 30) -> dict[str, Any]: ...

    def logs(self, limit: int = 12) -> list[dict[str, Any]]: ...


def _split_sql_script(script: str) -> list[str]:
    """Split the simple DDL scripts used by the project into executable statements."""
    statements: list[str] = []
    current: list[str] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        current.append(raw_line)
        if line.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    remainder = "\n".join(current).strip()
    if remainder:
        statements.append(remainder)
    return statements


def run_mysql_migrations(connection: Any, migrations_dir: Path = MYSQL_MIGRATIONS_DIR) -> list[str]:
    """Apply pending numbered MySQL migrations and return applied versions."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(32) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()}
    newly_applied: list[str] = []
    for migration in sorted(migrations_dir.glob("*.sql")):
        version = migration.stem.split("_", 1)[0]
        if not version or version in applied:
            continue
        for statement in _split_sql_script(migration.read_text(encoding="utf-8")):
            connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations(version) VALUES(?)", (version,))
        newly_applied.append(version)
    return newly_applied


class SQLiteDatabase:
    """SQLite persistence backend used locally and by default."""

    _lock = threading.RLock()

    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _datetime_value(value: str) -> str:
        return value

    def initialize(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(SCHEMA)
            self._seed_sources(conn)
            count = conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
            if count == 0:
                imported = self._seed_real_data(conn)
                if imported == 0 and DEMO_MODE:
                    self._seed_demo(conn)

    def _seed_sources(self, conn: sqlite3.Connection) -> None:
        rows = [
            ("fred_diesel", "Gasoil / diesel", "EIA/FRED - DDFUELNYH", "quotidienne"),
            ("fred_brent", "Pétrole Brent", "EIA/FRED - DCOILBRENTEU", "quotidienne"),
            ("internal_bitumen", "Bitume", "Devis et factures internes", "à la demande"),
            ("fred_asphalt", "Indice bitume/asphalte", "FRED - PCU324121324121", "mensuelle"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO data_sources(code, label, provider, frequency) VALUES(?,?,?,?)",
            rows,
        )

    def _seed_real_data(self, conn: Any) -> int:
        """Load the reproducible FRED/EIA snapshot bundled with the project."""
        if not REAL_DATA_PATH.exists():
            return 0
        previous: dict[str, float] = {}
        imported = 0
        with REAL_DATA_PATH.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                source_date = str(row.get("date") or "")[:10]
                if not source_date:
                    continue
                for product, column, unit, source in (
                    ("gasoil", "gasoil", "USD/gallon", "EIA/FRED - DDFUELNYH"),
                    ("brent", "brent", "USD/baril", "EIA/FRED - DCOILBRENTEU"),
                ):
                    raw_value = row.get(column)
                    if raw_value in (None, "", "."):
                        continue
                    price = float(raw_value)
                    prior = previous.get(product)
                    variation = round(price - prior, 6) if prior is not None else None
                    variation_pct = round((variation / prior) * 100, 4) if prior else None
                    conn.execute(
                        """INSERT INTO price_observations
                        (product, price, unit, currency, source, source_date, collected_at,
                         variation, variation_pct, is_unchanged, notes)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (product, price, unit, "USD", source, source_date,
                         self._datetime_value(f"{source_date}T12:00:00+00:00"), variation, variation_pct, 0,
                         "Historique réel EIA importé depuis FRED; horodatage de collecte approximé pour le backfill."),
                    )
                    previous[product] = price
                    imported += 1
        return imported

    def _seed_demo(self, conn: Any) -> None:
        """Create a useful 30-day sandbox so the dashboard is meaningful at first launch."""
        now = datetime.now(timezone.utc).replace(microsecond=0)
        base = {"gasoil": 2.33, "brent": 81.40, "bitume": 522.00}
        units = {k: v["unit"] for k, v in PRODUCTS.items()}
        labels = {"gasoil": "Mode démonstration - EIA/FRED", "brent": "Mode démonstration - Alpha Vantage", "bitume": "Mode démonstration - saisie interne"}
        for days_ago in range(29, -1, -1):
            for product, value in base.items():
                wave = ((days_ago * 17 + len(product) * 5) % 19 - 9) / 100
                price = round(value * (1 + wave / 100), 4)
                source_date = (now - timedelta(days=days_ago)).date().isoformat()
                collected_at = self._datetime_value((now - timedelta(days=days_ago)).isoformat())
                conn.execute(
                    """INSERT INTO price_observations
                    (product, price, unit, currency, source, source_date, collected_at,
                     variation, variation_pct, is_unchanged, notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (product, price, units[product], "USD", labels[product], source_date,
                     collected_at, None, None, 0, "Donnée de démonstration à remplacer par une source configurée."),
                )

    def seed_if_empty(self) -> None:
        with self.connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == 0:
                imported = self._seed_real_data(conn)
                if imported == 0 and DEMO_MODE:
                    self._seed_demo(conn)

    def insert_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        product = str(payload.get("product", "")).lower().strip()
        if product not in PRODUCTS:
            raise ValueError("Produit inconnu. Utilisez gasoil, brent ou bitume.")
        try:
            price = float(payload.get("price"))
        except (TypeError, ValueError):
            raise ValueError("Le prix doit être numérique.") from None
        if price <= 0 or price > 1_000_000:
            raise ValueError("Le prix doit être compris entre 0 et 1 000 000.")
        source_date = str(payload.get("source_date") or datetime.now(timezone.utc).date().isoformat())[:10]
        collected_at = self._datetime_value(
            str(payload.get("collected_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        )
        unit = str(payload.get("unit") or PRODUCTS[product]["unit"])
        source = str(payload.get("source") or "Saisie validée")[:150]
        notes = str(payload.get("notes") or "")[:500]
        with self._lock, self.connect() as conn:
            previous = conn.execute(
                "SELECT price, source_date FROM price_observations WHERE product=? ORDER BY collected_at DESC LIMIT 1",
                (product,),
            ).fetchone()
            previous_price = float(previous["price"]) if previous else None
            variation = round(price - previous_price, 6) if previous_price is not None else None
            variation_pct = round((variation / previous_price) * 100, 4) if previous_price else None
            previous_source_date = previous["source_date"] if previous else None
            if isinstance(previous_source_date, (date, datetime)):
                previous_source_date = previous_source_date.isoformat()[:10]
            unchanged = 1 if previous and previous_source_date == source_date else 0
            if unchanged:
                notes = (notes + " | Publication source inchangée.").strip(" |")
            cur = conn.execute(
                """INSERT INTO price_observations
                (product, price, unit, currency, source, source_date, collected_at,
                 variation, variation_pct, is_unchanged, notes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (product, price, unit, "USD", source, source_date, collected_at,
                 variation, variation_pct, unchanged, notes),
            )
            record = conn.execute("SELECT * FROM price_observations WHERE id=?", (cur.lastrowid,)).fetchone()
            return dict(record)

    def log_collection(self, status: str, rows: int, message: str, started_at: str, finished_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO collection_logs(started_at,finished_at,status,rows_collected,message) VALUES(?,?,?,?,?)",
                (self._datetime_value(started_at), self._datetime_value(finished_at), status, rows, message[:500]),
            )

    def latest(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT p.* FROM price_observations p
                JOIN (SELECT product, MAX(collected_at) max_at FROM price_observations GROUP BY product) latest
                ON p.product=latest.product AND p.collected_at=latest.max_at
                ORDER BY CASE p.product WHEN 'gasoil' THEN 1 WHEN 'brent' THEN 2 ELSE 3 END"""
            ).fetchall()
            return [dict(r) for r in rows]

    def observations(self, product: str | None = None, days: int = 30, limit: int = 600) -> list[dict[str, Any]]:
        clauses = ["collected_at >= ?"]
        params: list[Any] = [
            self._datetime_value((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
        ]
        if product in PRODUCTS:
            clauses.append("product = ?")
            params.append(product)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM price_observations WHERE {' AND '.join(clauses)} ORDER BY collected_at ASC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def dashboard(self, days: int = 30) -> dict[str, Any]:
        rows = self.observations(days=days, limit=100_000)
        latest = self.latest()
        by_product: dict[str, list[dict[str, Any]]] = {p: [] for p in PRODUCTS}
        for row in rows:
            by_product.setdefault(row["product"], []).append(row)
        metrics = {}
        for product, meta in PRODUCTS.items():
            values = [float(r["price"]) for r in by_product.get(product, [])]
            current = next((r for r in latest if r["product"] == product), None)
            metrics[product] = {
                "label": meta["label"], "unit": meta["unit"], "color": meta["color"],
                "current": float(current["price"]) if current else None,
                "variation": float(current["variation_pct"]) if current and current["variation_pct"] is not None else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "average": round(sum(values) / len(values), 4) if values else None,
                "count": len(values),
            }
        active_sources = {row["source"] for row in rows if row.get("source")}
        return {
            "days": days,
            "metrics": metrics,
            "latest": latest,
            "series": by_product,
            "quality": {
                "score": 100 if rows else 0,
                "source_count": len(active_sources),
                "observation_count": len(rows),
            },
            "demo_mode": DEMO_MODE,
        }

    def logs(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM collection_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def _get_mysql_connector() -> Any:
    try:
        import mysql.connector
    except ImportError as exc:
        raise RuntimeError("Installez mysql-connector-python pour utiliser MySQL.") from exc
    return mysql.connector


class _MySQLConnection:
    """Small adapter exposing the SQLite connection methods used by the backend."""

    def __init__(self, connection: Any):
        self._connection = connection

    def __enter__(self) -> "_MySQLConnection":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self._connection.close()

    @staticmethod
    def _sql(statement: str) -> str:
        return statement.replace("?", "%s")

    def execute(self, statement: str, params: Any = ()) -> Any:
        cursor = self._connection.cursor(dictionary=True, buffered=True)
        if params:
            cursor.execute(self._sql(statement), tuple(params))
        else:
            cursor.execute(self._sql(statement))
        return cursor

    def executemany(self, statement: str, params: Any) -> None:
        cursor = self._connection.cursor()
        cursor.executemany(self._sql(statement), params)
        cursor.close()

    def executescript(self, script: str) -> None:
        for statement in _split_sql_script(script):
            self.execute(statement)


class MySQLDatabase(SQLiteDatabase):
    """MySQL persistence backend using the same application-level contract."""

    def __init__(self, settings: MySQLSettings = MYSQL_SETTINGS):
        self.settings = settings
        self.initialize()

    def _ensure_database(self) -> None:
        connector = _get_mysql_connector()
        connection = connector.connect(**self.settings.connector_kwargs(include_database=False))
        cursor = connection.cursor()
        database_name = self.settings.database.replace("`", "``")
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
            f"CHARACTER SET {self.settings.charset} COLLATE {self.settings.charset}_unicode_ci"
        )
        connection.commit()
        cursor.close()
        connection.close()

    def connect(self) -> _MySQLConnection:
        connector = _get_mysql_connector()
        return _MySQLConnection(connector.connect(**self.settings.connector_kwargs()))

    @staticmethod
    def _datetime_value(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def initialize(self) -> None:
        self._ensure_database()
        with self.connect() as connection:
            connection.executescript(MYSQL_SCHEMA)
            run_mysql_migrations(connection)
            self._seed_sources(connection)
            count = connection.execute("SELECT COUNT(*) AS count FROM price_observations").fetchone()["count"]
            if count == 0:
                imported = self._seed_real_data(connection)
                if imported == 0 and DEMO_MODE:
                    self._seed_demo(connection)

    def _seed_sources(self, connection: _MySQLConnection) -> None:
        rows = [
            ("fred_diesel", "Gasoil / diesel", "EIA/FRED - DDFUELNYH", "quotidienne"),
            ("fred_brent", "Pétrole Brent", "EIA/FRED - DCOILBRENTEU", "quotidienne"),
            ("internal_bitumen", "Bitume", "Devis et factures internes", "à la demande"),
            ("fred_asphalt", "Indice bitume/asphalte", "FRED - PCU324121324121", "mensuelle"),
        ]
        connection.executemany(
            "INSERT IGNORE INTO data_sources(code, label, provider, frequency) VALUES(?,?,?,?)",
            rows,
        )


# Backwards-compatible name for callers that explicitly want the SQLite backend.
Database = SQLiteDatabase


def create_database() -> DatabaseBackend:
    """Create the configured persistence backend for the application."""
    if DB_BACKEND in {"sqlite", "sqlite3"}:
        return SQLiteDatabase()
    if DB_BACKEND in {"mysql", "mysql8"}:
        return MySQLDatabase()
    raise ValueError(f"Backend de base de données inconnu: {DB_BACKEND}")
