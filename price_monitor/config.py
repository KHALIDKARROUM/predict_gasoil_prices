from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
STORAGE_DIR = BASE_DIR / "storage"


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE settings without overwriting real environment values."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_DIR / ".env")


@dataclass(frozen=True)
class MySQLSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "utf8mb4"

    def connector_kwargs(self, include_database: bool = True) -> dict[str, object]:
        settings: dict[str, object] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "charset": self.charset,
        }
        if include_database:
            settings["database"] = self.database
        return settings


DB_PATH = Path(os.getenv("PRICE_MONITOR_DB", STORAGE_DIR / "price_monitor.db"))
REAL_DATA_PATH = Path(os.getenv("PRICE_MONITOR_DATA", BASE_DIR.parent / "data" / "processed" / "market_prices.csv"))
DB_BACKEND = os.getenv("PRICE_MONITOR_DB_BACKEND", "sqlite").strip().lower()
MYSQL_SETTINGS = MySQLSettings(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    database=os.getenv("MYSQL_DATABASE", "price_monitor"),
    user=os.getenv("MYSQL_USER", "price_monitor"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    charset=os.getenv("MYSQL_CHARSET", "utf8mb4"),
)

HOST = os.getenv("PRICE_MONITOR_HOST", "127.0.0.1")
PORT = int(os.getenv("PRICE_MONITOR_PORT", "8080"))
DEMO_MODE = os.getenv("PRICE_MONITOR_DEMO", "false").lower() in {"1", "true", "yes", "on"}
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
COLLECTION_TIMES = ("08:00", "11:00", "14:00", "17:00", "20:00")
