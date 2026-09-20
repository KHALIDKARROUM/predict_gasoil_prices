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


def bitumen_benchmark() -> dict:
    return {
        "code": "bls_wpu058",
        "product": "bitume",
        "label": "Asphalt PPI",
        "value": 546.938,
        "unit": "indice (déc. 1984 = 100)",
        "geography": "États-Unis",
        "source": "U.S. BLS Public Data API - WPU058",
        "source_code": "bls_asphalt_ppi",
        "source_date": "2026-08-01",
    }


def test_collect_all_keeps_successful_source_when_another_source_fails(monkeypatch):
    monkeypatch.setattr(collectors_module, "DEMO_MODE", False)
    monkeypatch.setattr(collectors_module, "collect_gasoil", gasoil_observation)
    monkeypatch.setattr(collectors_module, "collect_bitumen_benchmark", bitumen_benchmark)

    def failing_brent():
        raise RuntimeError("Brent service unavailable")

    monkeypatch.setattr(collectors_module, "collect_brent", failing_brent)

    observations, messages = collectors_module.collect_all()

    assert observations == [gasoil_observation()]
    assert messages == ["Brent service unavailable"]


def test_collect_bitumen_benchmark_keeps_index_separate_from_price(monkeypatch):
    monkeypatch.setattr(
        collectors_module,
        "_request_json",
        lambda url: {
            "status": "REQUEST_SUCCEEDED",
            "Results": {"series": [{"data": [{"year": "2026", "period": "M08", "value": "546.938"}]}]},
        },
    )

    result = collectors_module.collect_bitumen_benchmark()

    assert result["product"] == "bitume"
    assert result["value"] == 546.938
    assert result["unit"].startswith("indice")
    assert result["source_date"] == "2026-08-01"
    assert "USD/tonne" in result["notes"]


def test_partial_collection_is_persisted_and_logged_as_partial(empty_database, monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "collect_all",
        lambda: ([gasoil_observation()], ["Brent service unavailable"]),
    )

    result = scheduler_module.run_collection(empty_database)

    assert result == {
        "status": "partial",
        "rows": 1,
        "message": "Brent service unavailable",
    }
    assert len(empty_database.observations(days=3650)) == 1
    log = empty_database.logs(limit=1)[0]
    assert log["status"] == "partial"
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


def test_scheduler_persists_bitumen_benchmark_in_its_separate_table(empty_database, monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "collect_all",
        lambda: collectors_module.CollectionBatch(
            [],
            [],
            [{"code": "bls_asphalt_ppi", "success": True, "error": None}],
            [bitumen_benchmark()],
        ),
    )

    result = scheduler_module.run_collection(empty_database)

    assert result["status"] == "success"
    assert result["rows"] == 1
    assert result["benchmarks"] == 1
    assert empty_database.latest_benchmarks("bitume")[0]["value"] == 546.938
    assert empty_database.observations(product="bitume", days=3650) == []


def test_collection_updates_source_health_and_quality_score(empty_database, monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "collect_all",
        lambda: collectors_module.CollectionBatch(
            [gasoil_observation()],
            ["Brent service unavailable"],
            [
                {"code": "fred_diesel", "success": True, "error": None},
                {"code": "fred_brent", "success": False, "error": "Brent service unavailable"},
            ],
        ),
    )

    result = scheduler_module.run_collection(empty_database)

    assert result["status"] == "partial"
    health = {row["code"]: row for row in empty_database.source_health()}
    assert health["fred_diesel"]["last_success_at"]
    assert health["fred_diesel"]["last_error"] is None
    assert health["fred_brent"]["last_success_at"] is None
    assert health["fred_brent"]["last_error"] == "Brent service unavailable"
    assert empty_database.dashboard(days=30)["quality"]["score"] < 100


def test_successful_collection_clears_previous_source_error(empty_database):
    empty_database.update_source_health(
        "fred_diesel", False, "2026-09-13T11:00:00+00:00", "temporary outage"
    )
    empty_database.update_source_health("fred_diesel", True, "2026-09-13T12:00:00+00:00")

    source = next(row for row in empty_database.source_health() if row["code"] == "fred_diesel")
    assert source["last_success_at"] == "2026-09-13T12:00:00+00:00"
    assert source["last_error"] is None


def test_collect_all_fails_when_no_source_succeeds_and_demo_mode_is_off(monkeypatch):
    monkeypatch.setattr(collectors_module, "DEMO_MODE", False)
    monkeypatch.setattr(
        collectors_module,
        "collect_bitumen_benchmark",
        lambda: (_ for _ in ()).throw(RuntimeError("bitumen benchmark down")),
    )
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
