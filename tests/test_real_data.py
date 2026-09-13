from __future__ import annotations

import csv
from pathlib import Path

from price_monitor import database as database_module
from price_monitor.database import Database


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_real_snapshot_is_imported_into_empty_database(tmp_path, monkeypatch):
    snapshot = REPO_ROOT / "data" / "processed" / "market_prices.csv"
    monkeypatch.setattr(database_module, "REAL_DATA_PATH", snapshot)
    monkeypatch.setattr(database_module, "DEMO_MODE", False)

    with snapshot.open("r", encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    expected_rows = sum(
        1
        for row in source_rows
        for product in ("brent", "gasoil")
        if row.get(product) not in (None, "", ".")
    )

    database = Database(tmp_path / "real-data.db")
    with database.connect() as connection:
        imported_count = connection.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
        observations = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM price_observations ORDER BY collected_at ASC"
            ).fetchall()
        ]

    assert expected_rows > 2_000
    assert imported_count == expected_rows
    assert len(observations) == expected_rows
    assert {row["product"] for row in observations} == {"brent", "gasoil"}
    assert all(row["source"].startswith("EIA/FRED - ") for row in observations)
    assert all("Historique réel EIA importé" in row["notes"] for row in observations)
    assert any(row["variation"] is not None for row in observations)
    assert database.dashboard(days=10_000)["quality"]["observation_count"] == expected_rows
