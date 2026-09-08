from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH, DEMO_MODE, STORAGE_DIR


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


class Database:
    """Small persistence layer. SQLite is the local/demo default; the SQL schema
    in sql/mysql_schema.sql provides the production MySQL equivalent."""

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

    def initialize(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(SCHEMA)
            self._seed_sources(conn)
            count = conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
            if count == 0:
                self._seed_demo(conn)

    def _seed_sources(self, conn: sqlite3.Connection) -> None:
        rows = [
            ("fred_diesel", "Gasoil / diesel", "EIA/FRED - DDFUELNYH", "quotidienne"),
            ("alpha_brent", "Pétrole Brent", "Alpha Vantage - BRENT", "quotidienne"),
            ("internal_bitumen", "Bitume", "Devis et factures internes", "à la demande"),
            ("fred_asphalt", "Indice bitume/asphalte", "FRED - PCU324121324121", "mensuelle"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO data_sources(code, label, provider, frequency) VALUES(?,?,?,?)",
            rows,
        )

    @staticmethod
    def _seed_demo(conn: sqlite3.Connection) -> None:
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
                collected_at = (now - timedelta(days=days_ago)).isoformat()
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
        collected_at = str(payload.get("collected_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        unit = str(payload.get("unit") or PRODUCTS[product]["unit"])
        source = str(payload.get("source") or "Saisie validée")[:150]
        notes = str(payload.get("notes") or "")[:500]
        with self._lock, self.connect() as conn:
            previous = conn.execute(
                "SELECT price, source_date FROM price_observations WHERE product=? ORDER BY collected_at DESC LIMIT 1",
                (product,),
            ).fetchone()
            variation = round(price - previous["price"], 6) if previous else None
            variation_pct = round((variation / previous["price"]) * 100, 4) if previous and previous["price"] else None
            unchanged = 1 if previous and previous["source_date"] == source_date else 0
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
                (started_at, finished_at, status, rows, message[:500]),
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
        params: list[Any] = [(datetime.now(timezone.utc) - timedelta(days=days)).isoformat()]
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
        rows = self.observations(days=days)
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
                "current": current["price"] if current else None,
                "variation": current["variation_pct"] if current else None,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
                "average": round(sum(values) / len(values), 4) if values else None,
                "count": len(values),
            }
        return {"days": days, "metrics": metrics, "latest": latest, "series": by_product, "demo_mode": DEMO_MODE}

    def logs(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM collection_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

