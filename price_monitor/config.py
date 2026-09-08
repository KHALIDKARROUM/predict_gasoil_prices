from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = Path(os.getenv("PRICE_MONITOR_DB", STORAGE_DIR / "price_monitor.db"))

HOST = os.getenv("PRICE_MONITOR_HOST", "127.0.0.1")
PORT = int(os.getenv("PRICE_MONITOR_PORT", "8080"))
DEMO_MODE = os.getenv("PRICE_MONITOR_DEMO", "true").lower() in {"1", "true", "yes", "on"}
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
COLLECTION_TIMES = ("08:00", "11:00", "14:00", "17:00", "20:00")

