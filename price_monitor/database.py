from __future__ import annotations

import json
import csv
import math
import os
import re
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

PURCHASE_UNITS = {
    "gasoil": "gallon",
    "brent": "baril",
    "bitume": "tonne",
}

PROCUREMENT_PRODUCTS = {"gasoil", "bitume"}

SUPPLIER_CHANNEL_ROWS = [
    (
        "Shell Commercial Fuels", "gasoil", "global",
        "Afrique, Amériques, Asie/Moyen-Orient et plusieurs marchés européens",
        "Contact commercial B2B local ou distributeur agréé",
        "Contrat local; livraison camion-citerne ou dépôt selon le pays",
        "Demander EN 590 (soufre 10 ppm) ou la norme locale équivalente",
        "https://www.shell.com/business-customers/commercial-fuels.html",
        "https://www.shell.com/business-customers/commercial-fuels/contact-commercial-fuels.html",
        "Vérifier la disponibilité, la licence d'importation et le volume minimum auprès de l'entité locale.",
        10,
    ),
    (
        "TotalEnergies - réseau entreprises", "gasoil", "global",
        "Réseau international de filiales et de sites clients par pays",
        "Filiale locale, service grands comptes ou distributeur B2B",
        "Conditions, crédit et livraison négociés dans le pays de destination",
        "Préciser EN 590/ASTM, teneur en soufre, quantité, terminal et date de livraison",
        "https://totalenergies.com/company/energy-expertise/ship-market",
        "https://totalenergies.com/clients-websites",
        "Choisir le site officiel du pays de livraison et demander une offre écrite à l'entité contractante.",
        20,
    ),
    (
        "Négociant ou distributeur agréé au terminal", "gasoil", "local",
        "Terminal pétrolier ou dépôt agréé le plus proche de la destination",
        "Appel d'offres auprès de trois distributeurs titulaires d'une licence",
        "Ex-rack/EXW, FCA, DAP ou livraison camion selon l'infrastructure",
        "Spécification nationale, certificat d'analyse, SDS et preuve d'origine",
        "",
        "",
        "Contrôler le registre du commerce, la licence énergie, les sanctions et les coordonnées bancaires hors e-mail.",
        30,
    ),
    (
        "Shell Bitumen", "bitume", "global",
        "Réseau de production, dépôts et distribution dans de nombreux marchés",
        "Demande de devis B2B auprès de l'équipe bitume du pays",
        "Vrac chauffé, camion ou navire selon la destination et le volume",
        "Préciser EN 12591/ASTM D946, grade, température, emballage et application",
        "https://www.shell.com/business-customers/bitumen.html",
        "https://www.shell.com/business-customers/bitumen.html",
        "La disponibilité et le point de chargement varient par pays; obtenir un devis avec Incoterm et validité.",
        10,
    ),
    (
        "TotalEnergies Bitumen", "bitume", "europe",
        "Sept raffineries et opérations annoncées dans quinze pays européens",
        "Équipe commerciale locale ou portail Bitumen Online pour clients admis",
        "Vrac chauffé; prix fixe ou formule selon le marché et le contrat",
        "Bitume routier, modifié ou industriel; préciser grade et norme",
        "https://bitumen.totalenergies.com/",
        "https://bitumen.totalenergies.com/digital-portal-bitumen-customers",
        "L'accès au portail et aux prix est réservé aux clients; demander l'ouverture d'un compte fournisseur.",
        20,
    ),
    (
        "Nynas Bitumen", "bitume", "europe",
        "Pays nordiques, États baltes, Royaume-Uni et export selon disponibilité",
        "Contact commercial régional ou export",
        "Contrat annuel ou devis spot; logistique chauffée selon le site",
        "Bitumes routiers et modifiés; demander PDS, SDS et déclaration de performance",
        "https://nynas.com/en/products/bitumen/",
        "https://nynas.com/en/products/bitumen/our-offer/",
        "Utiliser le sélecteur de marché officiel ou le contact export indiqué par Nynas.",
        30,
    ),
    (
        "Puma Energy Bitumen", "bitume", "global",
        "Marchés desservis par le réseau Puma Energy, notamment Afrique et Asie-Pacifique",
        "Contact technique et commercial bitume",
        "Vrac, conteneur bitume et solutions navire-camion selon le marché",
        "Grades conformes notamment à EN 12591 ou AS 2008 selon le produit",
        "https://pumaenergy.com/bitumen/",
        "https://pumaenergy.com/bitumen/bitumen-products/",
        "Confirmer le territoire couvert, le point de chargement et le coût du maintien en température.",
        40,
    ),
]


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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product, source, source_date, price)
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
CREATE TABLE IF NOT EXISTS alert_states (
    alert_key TEXT PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    last_value REAL,
    last_notified_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS procurement_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL CHECK(product IN ('gasoil', 'brent', 'bitume')),
    supplier TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit TEXT NOT NULL,
    currency TEXT NOT NULL,
    unit_price REAL NOT NULL CHECK(unit_price > 0),
    exchange_rate REAL NOT NULL CHECK(exchange_rate > 0),
    transport_cost REAL NOT NULL DEFAULT 0 CHECK(transport_cost >= 0),
    budget_amount REAL,
    purchase_date TEXT NOT NULL,
    total_cost REAL NOT NULL,
    total_cost_usd REAL NOT NULL,
    budget_variance REAL,
    budget_variance_usd REAL,
    market_price_usd REAL,
    price_impact_unit_usd REAL,
    price_impact_total_usd REAL,
    price_impact_pct REAL,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_procurement_purchase_date
  ON procurement_purchases(purchase_date, product);
CREATE TABLE IF NOT EXISTS market_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    product TEXT NOT NULL CHECK(product IN ('gasoil', 'bitume')),
    label TEXT NOT NULL,
    value REAL NOT NULL CHECK(value > 0),
    unit TEXT NOT NULL,
    geography TEXT NOT NULL,
    source TEXT NOT NULL,
    source_date TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    variation REAL,
    variation_pct REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, source_date, value)
);
CREATE INDEX IF NOT EXISTS idx_market_benchmarks_code_date
  ON market_benchmarks(code, source_date);
CREATE TABLE IF NOT EXISTS supplier_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    product TEXT NOT NULL CHECK(product IN ('gasoil', 'bitume')),
    region TEXT NOT NULL,
    coverage TEXT NOT NULL,
    channel TEXT NOT NULL,
    typical_terms TEXT NOT NULL,
    specifications TEXT NOT NULL,
    website_url TEXT NOT NULL DEFAULT '',
    contact_url TEXT NOT NULL DEFAULT '',
    buyer_note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    UNIQUE(name, product, region)
);
"""


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
SQL_ROOT = Path(os.getenv("PRICE_MONITOR_SQL_DIR", PROJECT_ROOT / "sql"))
if not (SQL_ROOT / "mysql_schema.sql").exists():
    SQL_ROOT = PACKAGE_DIR
MYSQL_SCHEMA_PATH = SQL_ROOT / "mysql_schema.sql"
MYSQL_MIGRATIONS_DIR = SQL_ROOT / "mysql_migrations"
MYSQL_SCHEMA = MYSQL_SCHEMA_PATH.read_text(encoding="utf-8")
SQLITE_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class DatabaseBackend(Protocol):
    """Persistence contract shared by the SQLite and MySQL implementations."""

    def insert_observation(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def log_collection(self, status: str, rows: int, message: str, started_at: str, finished_at: str) -> None: ...

    def update_source_health(self, source_code: str, success: bool, at: str, error: str | None = None) -> None: ...

    def source_health(self) -> list[dict[str, Any]]: ...

    def latest(self) -> list[dict[str, Any]]: ...

    def observations(self, product: str | None = None, days: int = 30, limit: int = 600) -> list[dict[str, Any]]: ...

    def dashboard(self, days: int = 30) -> dict[str, Any]: ...

    def logs(self, limit: int = 12) -> list[dict[str, Any]]: ...

    def get_alert_state(self, alert_key: str) -> dict[str, Any] | None: ...

    def set_alert_state(
        self,
        alert_key: str,
        active: bool,
        last_value: float | None,
        updated_at: str,
        last_notified_at: str | None = None,
        last_status: str | None = None,
    ) -> None: ...

    def alert_rules(self, include_disabled: bool = True) -> list[dict[str, Any]]: ...

    def create_alert_rule(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def update_alert_rule(self, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...

    def delete_alert_rule(self, rule_id: int) -> None: ...

    def create_procurement(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def procurements(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def insert_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def latest_benchmarks(self, product: str | None = None, limit: int = 20) -> list[dict[str, Any]]: ...

    def supplier_channels(self, product: str | None = None, region: str | None = None) -> list[dict[str, Any]]: ...

    def history(
        self,
        product: str | None = None,
        supplier: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]: ...

    def compare_periods(
        self,
        period_a_from: str,
        period_a_to: str,
        period_b_from: str,
        period_b_to: str,
        product: str | None = None,
        supplier: str | None = None,
        source: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
    ) -> dict[str, Any]: ...


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


def run_sqlite_migrations(connection: sqlite3.Connection, migrations_dir: Path = SQLITE_MIGRATIONS_DIR) -> list[str]:
    """Apply numbered SQLite migrations and record them for repeatable deploys."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()}
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

    @staticmethod
    def _source_date_value(value: Any) -> str:
        """Validate and normalize a publication date without silently truncating it."""
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("La date source doit être au format YYYY-MM-DD.")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("La date source doit être une date calendaire valide.") from None

    @staticmethod
    def _collected_at_value(value: Any) -> str:
        """Validate an ISO-8601 timestamp and store it in a comparable UTC form."""
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ):
            raise ValueError("La date de collecte doit être un horodatage ISO 8601 avec fuseau.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("La date de collecte doit être un horodatage ISO 8601 valide.") from None
        if parsed.tzinfo is None:
            raise ValueError("La date de collecte doit inclure un fuseau horaire.")
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _deduplicate_observations(connection: Any) -> None:
        """Keep the first row before adding the identity index to older databases."""
        connection.execute(
            """DELETE FROM price_observations
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM price_observations
                GROUP BY product, source, source_date, price
            )"""
        )

    @staticmethod
    def _ensure_observation_identity(connection: Any) -> None:
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_observation_identity
            ON price_observations(product, source, source_date, price)"""
        )

    def initialize(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(SCHEMA)
            run_sqlite_migrations(conn)
            self._deduplicate_observations(conn)
            self._ensure_observation_identity(conn)
            self._seed_sources(conn)
            self._seed_supplier_channels(conn)
            count = conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
            if count == 0:
                imported = self._seed_real_data(conn)
                if imported == 0 and DEMO_MODE:
                    self._seed_demo(conn)

    def healthcheck(self) -> dict[str, str]:
        """Verify that the configured database accepts a simple read."""
        with self.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "backend": "sqlite"}

    def _seed_sources(self, conn: sqlite3.Connection) -> None:
        rows = [
            ("fred_diesel", "Gasoil / diesel", "EIA/FRED - DDFUELNYH", "quotidienne"),
            ("fred_brent", "Pétrole Brent", "EIA/FRED - DCOILBRENTEU", "quotidienne"),
            ("alpha_brent", "Pétrole Brent", "Alpha Vantage - BRENT", "quotidienne"),
            ("internal_bitumen", "Bitume", "Devis et factures internes", "à la demande"),
            ("bls_asphalt_ppi", "Indice bitume/asphalte (proxy)", "U.S. BLS - WPU058", "mensuelle"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO data_sources(code, label, provider, frequency) VALUES(?,?,?,?)",
            rows,
        )

    def _seed_supplier_channels(self, conn: Any) -> None:
        conn.executemany(
            """INSERT OR IGNORE INTO supplier_channels
            (name, product, region, coverage, channel, typical_terms, specifications,
             website_url, contact_url, buyer_note, sort_order)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            SUPPLIER_CHANNEL_ROWS,
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
        if not math.isfinite(price) or price <= 0 or price > 1_000_000:
            raise ValueError("Le prix doit être compris entre 0 et 1 000 000.")
        source_date_input = payload.get("source_date")
        source_date = self._source_date_value(
            datetime.now(timezone.utc).date().isoformat() if source_date_input is None else source_date_input
        )
        collected_at_input = payload.get("collected_at")
        collected_at = self._datetime_value(
            self._collected_at_value(
                datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                if collected_at_input is None
                else collected_at_input
            )
        )
        unit_input = payload.get("unit")
        unit = PRODUCTS[product]["unit"] if unit_input is None else unit_input
        if not isinstance(unit, str) or unit.strip() != PRODUCTS[product]["unit"]:
            raise ValueError(f"Unité invalide pour {product}. Utilisez {PRODUCTS[product]['unit']}.")
        unit = unit.strip()
        source = str(payload.get("source") or "Saisie validée")[:150]
        supplier = str(payload.get("supplier") or "").strip()[:150]
        if not supplier and product == "bitume":
            supplier = source
        notes = str(payload.get("notes") or "")[:500]
        with self._lock, self.connect() as conn:
            existing = conn.execute(
                """SELECT * FROM price_observations
                WHERE product=? AND source=? AND source_date=? AND price=?
                ORDER BY id LIMIT 1""",
                (product, source, source_date, price),
            ).fetchone()
            if existing:
                return dict(existing)
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
            try:
                cur = conn.execute(
                    """INSERT INTO price_observations
                    (product, price, unit, currency, source, supplier, source_date, collected_at,
                     variation, variation_pct, is_unchanged, notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (product, price, unit, "USD", source, supplier, source_date, collected_at,
                     variation, variation_pct, unchanged, notes),
                )
            except Exception:
                # Another worker may have inserted the same observation after the
                # pre-insert lookup. The unique identity index makes that race safe.
                existing = conn.execute(
                    """SELECT * FROM price_observations
                    WHERE product=? AND source=? AND source_date=? AND price=?
                    ORDER BY id LIMIT 1""",
                    (product, source, source_date, price),
                ).fetchone()
                if existing:
                    return dict(existing)
                raise
            record = conn.execute("SELECT * FROM price_observations WHERE id=?", (cur.lastrowid,)).fetchone()
            return dict(record)

    def insert_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a non-tradable market indicator without mixing it with quotes."""
        code = str(payload.get("code") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{2,64}", code):
            raise ValueError("Le code de l'indicateur est invalide.")
        product = str(payload.get("product") or "").strip().lower()
        if product not in PROCUREMENT_PRODUCTS:
            raise ValueError("L'indicateur doit concerner le gasoil ou le bitume.")
        try:
            value = float(payload.get("value"))
        except (TypeError, ValueError):
            raise ValueError("La valeur de l'indicateur doit être numérique.") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError("La valeur de l'indicateur doit être supérieure à zéro.")
        label = str(payload.get("label") or "").strip()[:180]
        unit = str(payload.get("unit") or "").strip()[:64]
        source = str(payload.get("source") or "").strip()[:180]
        if not label or not unit or not source:
            raise ValueError("Le libellé, l'unité et la source de l'indicateur sont obligatoires.")
        source_date = self._source_date_value(payload.get("source_date"))
        collected_at = self._collected_at_value(
            payload.get("collected_at")
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        geography = str(payload.get("geography") or "International")[:100]
        source_url = str(payload.get("source_url") or "")[:500]
        notes = str(payload.get("notes") or "")[:500]

        with self._lock, self.connect() as conn:
            existing = conn.execute(
                """SELECT * FROM market_benchmarks
                WHERE code=? AND source_date=? AND value=? ORDER BY id LIMIT 1""",
                (code, source_date, value),
            ).fetchone()
            if existing:
                return dict(existing)
            previous = conn.execute(
                "SELECT value FROM market_benchmarks WHERE code=? ORDER BY source_date DESC, id DESC LIMIT 1",
                (code,),
            ).fetchone()
            previous_value = float(previous["value"]) if previous else None
            variation = round(value - previous_value, 6) if previous_value is not None else None
            variation_pct = round((variation / previous_value) * 100, 4) if previous_value else None
            try:
                cursor = conn.execute(
                    """INSERT INTO market_benchmarks
                    (code, product, label, value, unit, geography, source, source_date,
                     collected_at, source_url, notes, variation, variation_pct)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        code, product, label, value, unit, geography, source, source_date,
                        self._datetime_value(collected_at), source_url, notes, variation, variation_pct,
                    ),
                )
            except Exception:
                existing = conn.execute(
                    """SELECT * FROM market_benchmarks
                    WHERE code=? AND source_date=? AND value=? ORDER BY id LIMIT 1""",
                    (code, source_date, value),
                ).fetchone()
                if existing:
                    return dict(existing)
                raise
            record = conn.execute(
                "SELECT * FROM market_benchmarks WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return dict(record)

    def latest_benchmarks(
        self, product: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if product is not None:
            product = product.strip().lower()
            if product not in PROCUREMENT_PRODUCTS:
                raise ValueError("Produit inconnu. Utilisez gasoil ou bitume.")
        safe_limit = max(1, min(int(limit), 100))
        clauses = ["product=?"] if product else []
        params: list[Any] = [product] if product else []
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM market_benchmarks {where}
                ORDER BY source_date DESC, collected_at DESC, id DESC""",
                params,
            ).fetchall()
        latest_by_code: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            latest_by_code.setdefault(str(item["code"]), item)
            if len(latest_by_code) >= safe_limit:
                break
        return list(latest_by_code.values())

    def supplier_channels(
        self, product: str | None = None, region: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["active=1"]
        params: list[Any] = []
        if product:
            product = product.strip().lower()
            if product not in PROCUREMENT_PRODUCTS:
                raise ValueError("Produit inconnu. Utilisez gasoil ou bitume.")
            clauses.append("product=?")
            params.append(product)
        normalized_region = str(region or "").strip().lower()
        if normalized_region and normalized_region not in {"all", "global"}:
            if not re.fullmatch(r"[a-z_]{2,32}", normalized_region):
                raise ValueError("Région invalide.")
            clauses.append("region IN ('global', ?)")
            params.append(normalized_region)
        with self.connect() as conn:
            rows = conn.execute(
                f"""SELECT id, name, product, region, coverage, channel, typical_terms,
                specifications, website_url, contact_url, buyer_note
                FROM supplier_channels WHERE {' AND '.join(clauses)}
                ORDER BY product, sort_order, name""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_procurement(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a purchase estimate and compare it with the latest USD market price."""
        product = str(payload.get("product", "")).lower().strip()
        if product not in PRODUCTS:
            raise ValueError("Produit inconnu. Utilisez gasoil, brent ou bitume.")

        supplier = str(payload.get("supplier") or "").strip()
        if not supplier:
            raise ValueError("Le fournisseur est obligatoire.")
        supplier = supplier[:150]

        def positive_number(field: str, label: str, default: float | None = None) -> float:
            raw = payload.get(field, default)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{label} doit être numérique.") from None
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} doit être supérieur à zéro.")
            return value

        quantity = positive_number("quantity", "La quantité")
        unit = str(payload.get("unit") or PURCHASE_UNITS[product]).strip().lower()
        if unit != PURCHASE_UNITS[product]:
            raise ValueError(f"Unité invalide pour {product}. Utilisez {PURCHASE_UNITS[product]}.")
        currency = str(payload.get("currency") or "USD").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("La devise doit être un code ISO de trois lettres, par exemple USD ou EUR.")
        unit_price = positive_number("unit_price", "Le prix unitaire")

        exchange_input = payload.get("exchange_rate")
        if exchange_input in (None, "") and currency == "USD":
            exchange_input = 1
        try:
            exchange_rate = float(exchange_input)
        except (TypeError, ValueError):
            raise ValueError("Le taux de change doit être numérique.") from None
        if not math.isfinite(exchange_rate) or exchange_rate <= 0:
            raise ValueError("Le taux de change doit être supérieur à zéro.")

        try:
            transport_cost = float(payload.get("transport_cost") or 0)
        except (TypeError, ValueError):
            raise ValueError("Le transport doit être numérique.") from None
        if not math.isfinite(transport_cost) or transport_cost < 0:
            raise ValueError("Le transport doit être positif ou nul.")

        budget_raw = payload.get("budget_amount")
        budget_amount: float | None
        if budget_raw in (None, ""):
            budget_amount = None
        else:
            try:
                budget_amount = float(budget_raw)
            except (TypeError, ValueError):
                raise ValueError("Le budget doit être numérique.") from None
            if not math.isfinite(budget_amount) or budget_amount < 0:
                raise ValueError("Le budget doit être positif ou nul.")

        purchase_date = self._source_date_value(
            datetime.now(timezone.utc).date().isoformat()
            if payload.get("purchase_date") is None
            else payload.get("purchase_date")
        )
        notes = str(payload.get("notes") or "")[:500]
        total_cost = round(quantity * unit_price + transport_cost, 6)
        total_cost_usd = round(total_cost * exchange_rate, 6)
        budget_variance = round(total_cost - budget_amount, 6) if budget_amount is not None else None
        budget_variance_usd = round(budget_variance * exchange_rate, 6) if budget_variance is not None else None

        with self._lock, self.connect() as conn:
            market_row = conn.execute(
                """SELECT price FROM price_observations
                WHERE product=? ORDER BY collected_at DESC LIMIT 1""",
                (product,),
            ).fetchone()
            market_price_usd = float(market_row["price"]) if market_row else None
            unit_price_usd = unit_price * exchange_rate
            price_impact_unit_usd = (
                round(unit_price_usd - market_price_usd, 6) if market_price_usd is not None else None
            )
            price_impact_total_usd = (
                round(price_impact_unit_usd * quantity, 6)
                if price_impact_unit_usd is not None
                else None
            )
            price_impact_pct = (
                round((price_impact_unit_usd / market_price_usd) * 100, 4)
                if price_impact_unit_usd is not None and market_price_usd
                else None
            )
            created_at = self._datetime_value(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
            cur = conn.execute(
                """INSERT INTO procurement_purchases
                (product, supplier, quantity, unit, currency, unit_price, exchange_rate,
                 transport_cost, budget_amount, purchase_date, total_cost, total_cost_usd,
                 budget_variance, budget_variance_usd, market_price_usd, price_impact_unit_usd,
                 price_impact_total_usd, price_impact_pct, notes, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    product, supplier, quantity, unit, currency, unit_price, exchange_rate,
                    transport_cost, budget_amount, purchase_date, total_cost, total_cost_usd,
                    budget_variance, budget_variance_usd, market_price_usd, price_impact_unit_usd,
                    price_impact_total_usd, price_impact_pct, notes, created_at,
                ),
            )
            record = conn.execute(
                "SELECT * FROM procurement_purchases WHERE id=?", (cur.lastrowid,)
            ).fetchone()
            return dict(record)

    def procurements(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM procurement_purchases
                ORDER BY purchase_date DESC, id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def history(
        self,
        product: str | None = None,
        supplier: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        clauses, params = self._history_filters(
            product, supplier, source, date_from, date_to, min_price, max_price
        )
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 10_000))
        where = " AND ".join(clauses) if clauses else "1=1"
        offset = (page - 1) * page_size
        with self.connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM price_observations WHERE {where}", params
            ).fetchone()
            rows = conn.execute(
                f"""SELECT * FROM price_observations WHERE {where}
                ORDER BY source_date DESC, collected_at DESC, id DESC LIMIT ? OFFSET ?""",
                [*params, page_size, offset],
            ).fetchall()
        total = int(total_row["count"] if isinstance(total_row, sqlite3.Row) else total_row["count"])
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0,
        }

    def compare_periods(
        self,
        period_a_from: str,
        period_a_to: str,
        period_b_from: str,
        period_b_to: str,
        product: str | None = None,
        supplier: str | None = None,
        source: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
    ) -> dict[str, Any]:
        period_a_from = self._source_date_value(period_a_from)
        period_a_to = self._source_date_value(period_a_to)
        period_b_from = self._source_date_value(period_b_from)
        period_b_to = self._source_date_value(period_b_to)
        if period_a_from > period_a_to or period_b_from > period_b_to:
            raise ValueError("La date de début doit précéder la date de fin.")

        first = self.history(
            product, supplier, source, period_a_from, period_a_to, min_price, max_price,
            page=1, page_size=10_000,
        )["items"]
        second = self.history(
            product, supplier, source, period_b_from, period_b_to, min_price, max_price,
            page=1, page_size=10_000,
        )["items"]

        def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            result: dict[str, dict[str, Any]] = {}
            for key in PRODUCTS:
                values = [float(row["price"]) for row in rows if row["product"] == key]
                result[key] = {
                    "count": len(values),
                    "average": round(sum(values) / len(values), 6) if values else None,
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                }
            return result

        first_summary = summarize(first)
        second_summary = summarize(second)
        products: dict[str, dict[str, Any]] = {}
        for key in PRODUCTS:
            a_average = first_summary[key]["average"]
            b_average = second_summary[key]["average"]
            change = round(b_average - a_average, 6) if a_average is not None and b_average is not None else None
            change_pct = round((change / a_average) * 100, 4) if change is not None and a_average else None
            products[key] = {
                "period_a": first_summary[key],
                "period_b": second_summary[key],
                "average_change": change,
                "average_change_pct": change_pct,
            }
        return {
            "period_a": {"from": period_a_from, "to": period_a_to},
            "period_b": {"from": period_b_from, "to": period_b_to},
            "products": products,
        }

    def _history_filters(
        self,
        product: str | None,
        supplier: str | None,
        source: str | None,
        date_from: str | None,
        date_to: str | None,
        min_price: float | None,
        max_price: float | None,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if product:
            product = product.strip().lower()
            if product not in PRODUCTS:
                raise ValueError("Produit inconnu. Utilisez gasoil, brent ou bitume.")
            clauses.append("product=?")
            params.append(product)
        if supplier:
            clauses.append("supplier LIKE ?")
            params.append(f"%{supplier.strip()}%")
        if source:
            clauses.append("source LIKE ?")
            params.append(f"%{source.strip()}%")
        if date_from:
            clauses.append("source_date >= ?")
            params.append(self._source_date_value(date_from))
        if date_to:
            clauses.append("source_date <= ?")
            params.append(self._source_date_value(date_to))
        numeric_filters: list[tuple[str, Any, str]] = [
            ("price >= ?", min_price, "Le prix minimum"),
            ("price <= ?", max_price, "Le prix maximum"),
        ]
        for clause, raw, label in numeric_filters:
            if raw is None or raw == "":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{label} doit être numérique.") from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} doit être positif ou nul.")
            clauses.append(clause)
            params.append(value)
        if min_price is not None and max_price is not None and float(min_price) > float(max_price):
            raise ValueError("Le prix minimum doit être inférieur au prix maximum.")
        return clauses, params

    def log_collection(self, status: str, rows: int, message: str, started_at: str, finished_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO collection_logs(started_at,finished_at,status,rows_collected,message) VALUES(?,?,?,?,?)",
                (self._datetime_value(started_at), self._datetime_value(finished_at), status, rows, message[:500]),
            )

    def update_source_health(
        self,
        source_code: str,
        success: bool,
        at: str,
        error: str | None = None,
    ) -> None:
        """Persist the latest outcome for one configured source."""
        with self._lock, self.connect() as conn:
            if success:
                conn.execute(
                    "UPDATE data_sources SET last_success_at=?, last_error=NULL WHERE code=?",
                    (self._datetime_value(at), source_code),
                )
            else:
                conn.execute(
                    "UPDATE data_sources SET last_error=? WHERE code=?",
                    (str(error or "Échec de collecte")[:500], source_code),
                )

    def source_health(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT code, label, provider, frequency, active, last_success_at, last_error
                FROM data_sources WHERE active=1 ORDER BY id"""
            ).fetchall()
            return [dict(row) for row in rows]

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
        source_health = self.source_health()
        quality_score = self._quality_score(rows, source_health)
        return {
            "days": days,
            "metrics": metrics,
            "latest": latest,
            "series": by_product,
            "quality": {
                "score": quality_score,
                "source_count": len(active_sources),
                "observation_count": len(rows),
            },
            "source_health": source_health,
            "demo_mode": DEMO_MODE,
        }

    @classmethod
    def _quality_score(cls, rows: list[dict[str, Any]], sources: list[dict[str, Any]]) -> int:
        """Score stored data and the health of sources that have been checked.

        Sources that have never been collected are intentionally excluded from
        the health denominator: manually maintained and not-yet-configured
        sources should not make an otherwise valid dataset look unhealthy.
        """
        if not rows:
            return 0

        valid_rows = sum(cls._observation_is_valid(row) for row in rows)
        data_score = (valid_rows / len(rows)) * 100

        monitored = [
            source
            for source in sources
            if source.get("last_success_at") is not None or source.get("last_error")
        ]
        if not monitored:
            source_score = 100.0
        else:
            healthy = sum(cls._source_is_healthy(source) for source in monitored)
            source_score = (healthy / len(monitored)) * 100

        return max(0, min(100, round((data_score + source_score) / 2)))

    @staticmethod
    def _observation_is_valid(row: dict[str, Any]) -> bool:
        required = ("product", "price", "unit", "currency", "source", "source_date", "collected_at")
        if any(row.get(field) in (None, "") for field in required):
            return False
        try:
            price = float(row["price"])
            if price <= 0 or not math.isfinite(price):
                return False
            date.fromisoformat(str(row["source_date"])[:10])
            collected_at = row["collected_at"]
            if isinstance(collected_at, datetime):
                parsed = collected_at
            else:
                parsed = datetime.fromisoformat(str(collected_at).replace("Z", "+00:00"))
            return parsed.tzinfo is not None or isinstance(collected_at, datetime)
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _source_is_healthy(source: dict[str, Any]) -> bool:
        if source.get("last_error") or not source.get("last_success_at"):
            return False
        try:
            value = source["last_success_at"]
            if isinstance(value, datetime):
                success_at = value
                if success_at.tzinfo is None:
                    success_at = success_at.replace(tzinfo=timezone.utc)
            else:
                success_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if success_at.tzinfo is None:
                    success_at = success_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - success_at.astimezone(timezone.utc)
            freshness_window = {"quotidienne": timedelta(days=2), "mensuelle": timedelta(days=62)}.get(
                str(source.get("frequency", "")).lower(), timedelta(days=365)
            )
            return age <= freshness_window
        except (TypeError, ValueError, OverflowError):
            return False

    def logs(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM collection_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def get_alert_state(self, alert_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT alert_key, active, last_value, last_notified_at, updated_at, last_status FROM alert_states WHERE alert_key=?",
                (alert_key,),
            ).fetchone()
            return dict(row) if row else None

    def set_alert_state(
        self,
        alert_key: str,
        active: bool,
        last_value: float | None,
        updated_at: str,
        last_notified_at: str | None = None,
        last_status: str | None = None,
    ) -> None:
        with self._lock, self.connect() as conn:
            notified_value = self._datetime_value(last_notified_at) if last_notified_at else None
            existing = conn.execute(
                "SELECT alert_key FROM alert_states WHERE alert_key=?", (alert_key,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE alert_states
                    SET active=?, last_value=?, last_notified_at=COALESCE(?, last_notified_at),
                        updated_at=?, last_status=COALESCE(?, last_status)
                    WHERE alert_key=?""",
                    (int(active), last_value, notified_value, self._datetime_value(updated_at), last_status, alert_key),
                )
            else:
                conn.execute(
                    """INSERT INTO alert_states
                    (alert_key, active, last_value, last_notified_at, updated_at, last_status)
                    VALUES(?,?,?,?,?,?)""",
                    (alert_key, int(active), last_value, notified_value, self._datetime_value(updated_at), last_status or "normal"),
                )

    @staticmethod
    def _alert_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"}:
            return False
        raise ValueError("Le champ muted doit être booléen.")

    @classmethod
    def _validate_alert_rule(cls, payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        product = str(payload.get("product", current.get("product", ""))).strip().lower()
        if product not in PRODUCTS:
            raise ValueError("Produit inconnu. Utilisez gasoil, brent ou bitume.")
        direction = str(payload.get("direction", current.get("direction", ""))).strip().lower()
        if direction not in {"above", "below"}:
            raise ValueError("La direction doit être above ou below.")
        threshold_input = payload.get("threshold", current.get("threshold"))
        try:
            threshold = float(threshold_input)
        except (TypeError, ValueError):
            raise ValueError("Le seuil doit être numérique.") from None
        if not math.isfinite(threshold) or threshold <= 0 or threshold > 1_000_000:
            raise ValueError("Le seuil doit être compris entre 0 et 1 000 000.")
        channel = str(payload.get("channel", current.get("channel", "webhook"))).strip().lower()
        if channel not in {"webhook", "email", "both"}:
            raise ValueError("Le canal doit être webhook, email ou both.")
        return {
            "product": product,
            "direction": direction,
            "threshold": threshold,
            "channel": channel,
            "muted": cls._alert_bool(payload.get("muted", current.get("muted", False))),
            "enabled": cls._alert_bool(payload.get("enabled", current.get("enabled", True)), True),
        }

    @staticmethod
    def _alert_key(product: str, direction: str, threshold: float) -> str:
        return f"price:{product}:{direction}:{threshold:g}"

    def alert_rules(self, include_disabled: bool = True) -> list[dict[str, Any]]:
        where = "" if include_disabled else " WHERE r.enabled=1"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT r.* FROM alert_rules r{where} ORDER BY r.product, CASE r.direction WHEN 'above' THEN 1 ELSE 2 END, r.id"
            ).fetchall()
            result: list[dict[str, Any]] = []
            for raw in rows:
                row = dict(raw)
                key = self._alert_key(row["product"], row["direction"], float(row["threshold"]))
                state_row = conn.execute(
                    "SELECT active, last_value, last_notified_at, updated_at, last_status FROM alert_states WHERE alert_key=?",
                    (key,),
                ).fetchone()
                state = dict(state_row) if state_row else {}
                status = "muted" if bool(row["muted"]) else (
                    "active" if bool(state.get("active")) else
                    "recovered" if state.get("last_status") == "recovered" else "normal"
                )
                row.update({
                    "id": int(row["id"]),
                    "threshold": float(row["threshold"]),
                    "muted": bool(row["muted"]),
                    "enabled": bool(row["enabled"]),
                    "status": status,
                    "alert_key": key,
                    "active": bool(state.get("active")),
                    "last_value": state.get("last_value"),
                    "last_notified_at": state.get("last_notified_at"),
                    "last_evaluated_at": state.get("updated_at"),
                })
                result.append(row)
            return result

    def create_alert_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule = self._validate_alert_rule(payload)
        now = self._datetime_value(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        with self._lock, self.connect() as conn:
            duplicate = conn.execute(
                "SELECT id FROM alert_rules WHERE product=? AND direction=?",
                (rule["product"], rule["direction"]),
            ).fetchone()
            if duplicate:
                raise ValueError("Une règle existe déjà pour ce produit et cette direction.")
            cursor = conn.execute(
                """INSERT INTO alert_rules
                (product, direction, threshold, channel, muted, enabled, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (rule["product"], rule["direction"], rule["threshold"], rule["channel"], int(rule["muted"]), int(rule["enabled"]), now, now),
            )
            rule_id = getattr(cursor, "lastrowid", None)
            if not rule_id:
                rule_id = conn.execute("SELECT MAX(id) FROM alert_rules").fetchone()[0]
        return next(item for item in self.alert_rules() if item["id"] == int(rule_id))

    def update_alert_rule(self, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            rule_id = int(rule_id)
        except (TypeError, ValueError):
            raise ValueError("Identifiant de règle invalide.") from None
        now = self._datetime_value(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        with self._lock, self.connect() as conn:
            existing_row = conn.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
            if not existing_row:
                raise ValueError("Règle introuvable.")
            existing = dict(existing_row)
            rule = self._validate_alert_rule(payload, existing)
            duplicate = conn.execute(
                "SELECT id FROM alert_rules WHERE product=? AND direction=? AND id<>?",
                (rule["product"], rule["direction"], rule_id),
            ).fetchone()
            if duplicate:
                raise ValueError("Une règle existe déjà pour ce produit et cette direction.")
            conn.execute(
                """UPDATE alert_rules SET product=?, direction=?, threshold=?, channel=?, muted=?, enabled=?, updated_at=?
                WHERE id=?""",
                (rule["product"], rule["direction"], rule["threshold"], rule["channel"], int(rule["muted"]), int(rule["enabled"]), now, rule_id),
            )
        return next(item for item in self.alert_rules() if item["id"] == rule_id)

    def delete_alert_rule(self, rule_id: int) -> None:
        try:
            rule_id = int(rule_id)
        except (TypeError, ValueError):
            raise ValueError("Identifiant de règle invalide.") from None
        with self._lock, self.connect() as conn:
            deleted = conn.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,)).rowcount
            if not deleted:
                raise ValueError("Règle introuvable.")


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

    def healthcheck(self) -> dict[str, str]:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "backend": "mysql"}

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
            self._deduplicate_mysql_observations(connection)
            self._ensure_mysql_observation_identity(connection)
            self._seed_sources(connection)
            self._seed_supplier_channels(connection)
            count = connection.execute("SELECT COUNT(*) AS count FROM price_observations").fetchone()["count"]
            if count == 0:
                imported = self._seed_real_data(connection)
                if imported == 0 and DEMO_MODE:
                    self._seed_demo(connection)

    def _seed_sources(self, connection: _MySQLConnection) -> None:
        rows = [
            ("fred_diesel", "Gasoil / diesel", "EIA/FRED - DDFUELNYH", "quotidienne"),
            ("fred_brent", "Pétrole Brent", "EIA/FRED - DCOILBRENTEU", "quotidienne"),
            ("alpha_brent", "Pétrole Brent", "Alpha Vantage - BRENT", "quotidienne"),
            ("internal_bitumen", "Bitume", "Devis et factures internes", "à la demande"),
            ("bls_asphalt_ppi", "Indice bitume/asphalte (proxy)", "U.S. BLS - WPU058", "mensuelle"),
        ]
        connection.executemany(
            "INSERT IGNORE INTO data_sources(code, label, provider, frequency) VALUES(?,?,?,?)",
            rows,
        )

    def _seed_supplier_channels(self, connection: _MySQLConnection) -> None:
        connection.executemany(
            """INSERT IGNORE INTO supplier_channels
            (name, product, region, coverage, channel, typical_terms, specifications,
             website_url, contact_url, buyer_note, sort_order)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            SUPPLIER_CHANNEL_ROWS,
        )

    @staticmethod
    def _deduplicate_mysql_observations(connection: _MySQLConnection) -> None:
        connection.execute(
            """DELETE newer FROM price_observations AS newer
            INNER JOIN price_observations AS older
              ON older.product = newer.product
             AND older.source = newer.source
             AND older.source_date = newer.source_date
             AND older.price = newer.price
             AND older.id < newer.id"""
        )

    @staticmethod
    def _ensure_mysql_observation_identity(connection: _MySQLConnection) -> None:
        indexes = connection.execute(
            "SHOW INDEX FROM price_observations WHERE Key_name=?",
            ("uq_observation_identity",),
        ).fetchall()
        if not indexes:
            connection.execute(
                """ALTER TABLE price_observations
                ADD UNIQUE KEY uq_observation_identity(product, source, source_date, price)"""
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
