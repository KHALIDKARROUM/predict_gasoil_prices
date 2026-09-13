from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def observation_payload(product: str, price: float, source_date: str, collected_at: str) -> dict:
    return {
        "product": product,
        "price": price,
        "source_date": source_date,
        "collected_at": collected_at,
        "source": "Test source",
    }


def test_insert_observation_calculates_variation_and_unchanged_publication(empty_database):
    first = empty_database.insert_observation(
        observation_payload("gasoil", 2.0, "2026-09-10", "2026-09-10T12:00:00+00:00")
    )
    second = empty_database.insert_observation(
        observation_payload("gasoil", 2.5, "2026-09-10", "2026-09-10T13:00:00+00:00")
    )

    assert first["variation"] is None
    assert first["variation_pct"] is None
    assert second["variation"] == 0.5
    assert second["variation_pct"] == 25.0
    assert second["is_unchanged"] == 1
    assert "Publication source inchangée." in second["notes"]
    assert empty_database.observations(product="gasoil", days=3650)[-1]["id"] == second["id"]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"product": "copper", "price": 10}, "Produit inconnu"),
        ({"product": "brent", "price": "not-a-number"}, "prix doit être numérique"),
        ({"product": "brent", "price": 0}, "compris entre 0"),
        ({"product": "brent", "price": -1}, "compris entre 0"),
        ({"product": "brent", "price": 1_000_001}, "compris entre 0"),
    ],
)
def test_insert_observation_rejects_invalid_payload(empty_database, payload, message):
    with pytest.raises(ValueError, match=message):
        empty_database.insert_observation(payload)

    assert empty_database.observations(days=3650) == []


def test_dashboard_returns_per_product_statistics(empty_database):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = [
        ("gasoil", 10.0, "gasoil-source", now - timedelta(days=2)),
        ("gasoil", 20.0, "gasoil-source", now - timedelta(days=1)),
        ("brent", 100.0, "brent-source", now - timedelta(days=1)),
    ]
    for product, price, source, collected_at in rows:
        payload = observation_payload(product, price, collected_at.date().isoformat(), collected_at.isoformat())
        payload["source"] = source
        empty_database.insert_observation(payload)

    dashboard = empty_database.dashboard(days=30)

    gasoil = dashboard["metrics"]["gasoil"]
    assert gasoil["current"] == 20.0
    assert gasoil["variation"] == 100.0
    assert gasoil["min"] == 10.0
    assert gasoil["max"] == 20.0
    assert gasoil["average"] == 15.0
    assert gasoil["count"] == 2

    brent = dashboard["metrics"]["brent"]
    assert brent["current"] == 100.0
    assert brent["average"] == 100.0
    assert brent["count"] == 1
    assert dashboard["metrics"]["bitume"]["current"] is None
    assert dashboard["metrics"]["bitume"]["count"] == 0
    assert dashboard["quality"] == {
        "score": 100,
        "source_count": 2,
        "observation_count": 3,
    }


def test_dashboard_excludes_observations_outside_requested_window(empty_database):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = now - timedelta(days=10)
    recent = now - timedelta(days=1)
    for price, collected_at in ((10.0, old), (20.0, recent)):
        empty_database.insert_observation(
            observation_payload("gasoil", price, collected_at.date().isoformat(), collected_at.isoformat())
        )

    dashboard = empty_database.dashboard(days=3)

    assert dashboard["metrics"]["gasoil"]["count"] == 1
    assert dashboard["metrics"]["gasoil"]["average"] == 20.0
