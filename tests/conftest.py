from __future__ import annotations

import pytest

from price_monitor import database as database_module
from price_monitor.database import Database


@pytest.fixture
def empty_database(tmp_path, monkeypatch) -> Database:
    """Return an isolated database without importing the bundled snapshot."""
    monkeypatch.setattr(database_module, "REAL_DATA_PATH", tmp_path / "missing.csv")
    monkeypatch.setattr(database_module, "DEMO_MODE", False)
    return Database(tmp_path / "price_monitor.db")
