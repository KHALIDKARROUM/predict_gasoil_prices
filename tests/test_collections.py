from __future__ import annotations

import pytest

from price_monitor.services import collectors as collectors_module
from price_monitor.services import scheduler as scheduler_module


def gasoil_observation() -> dict:
    return {
        "product": "gasoil",
        "price": 2.4,
        "unit": "USD/gallon",
        "source": "FRED test source",
        "source_date": "2026-09-13",
        "collected_at": "2026-09-13T12:00:00+00:00",
    }


def test_collect_all_keeps_successful_source_when_another_source_fails(monkeypatch):
    monkeypatch.setattr(collectors_module, "DEMO_MODE", False)
    monkeypatch.setattr(collectors_module, "collect_gasoil", gasoil_observation)

    def failing_brent():
        raise RuntimeError("Brent service unavailable")

    monkeypatch.setattr(collectors_module, "collect_brent", failing_brent)

    observations, messages = collectors_module.collect_all()

    assert observations == [gasoil_observation()]
    assert messages == ["Brent service unavailable"]


def test_partial_collection_is_persisted_and_logged_as_success(empty_database, monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "collect_all",
        lambda: ([gasoil_observation()], ["Brent service unavailable"]),
    )

    result = scheduler_module.run_collection(empty_database)

    assert result == {
        "status": "success",
        "rows": 1,
        "message": "Brent service unavailable",
    }
    assert len(empty_database.observations(days=3650)) == 1
    log = empty_database.logs(limit=1)[0]
    assert log["status"] == "success"
    assert log["rows_collected"] == 1
    assert log["message"] == "Brent service unavailable"


def test_failed_collection_is_logged_without_persisting_rows(empty_database, monkeypatch):
    def failing_collection():
        raise RuntimeError("All market sources unavailable")

    monkeypatch.setattr(scheduler_module, "collect_all", failing_collection)

    result = scheduler_module.run_collection(empty_database)

    assert result == {
        "status": "error",
        "rows": 0,
        "message": "All market sources unavailable",
    }
    assert empty_database.observations(days=3650) == []
    log = empty_database.logs(limit=1)[0]
    assert log["status"] == "error"
    assert log["rows_collected"] == 0
    assert log["message"] == "All market sources unavailable"


def test_collect_all_fails_when_no_source_succeeds_and_demo_mode_is_off(monkeypatch):
    monkeypatch.setattr(collectors_module, "DEMO_MODE", False)
    monkeypatch.setattr(
        collectors_module,
        "collect_gasoil",
        lambda: (_ for _ in ()).throw(RuntimeError("diesel down")),
    )
    monkeypatch.setattr(
        collectors_module,
        "collect_brent",
        lambda: (_ for _ in ()).throw(RuntimeError("brent down")),
    )

    with pytest.raises(RuntimeError, match="Aucune source publique disponible"):
        collectors_module.collect_all()
