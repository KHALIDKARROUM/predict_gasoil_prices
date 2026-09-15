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


def test_insert_observation_is_idempotent_for_an_exact_retry(empty_database):
    payload = observation_payload("gasoil", 2.4, "2026-09-13", "2026-09-13T12:00:00+00:00")

    first = empty_database.insert_observation(payload)
    retry = empty_database.insert_observation(
        {**payload, "collected_at": "2026-09-13T13:00:00+00:00", "notes": "Retry"}
    )

    assert retry["id"] == first["id"]
    assert len(empty_database.observations(days=3650)) == 1


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("source_date", "2026-02-30", "date source"),
        ("source_date", "2026-09-13T00:00:00+00:00", "format YYYY-MM-DD"),
        ("collected_at", "2026-09-13", "date de collecte"),
        ("collected_at", "2026-02-30T12:00:00+00:00", "date de collecte"),
    ],
)
def test_insert_observation_rejects_invalid_dates(empty_database, field, value, message):
    payload = observation_payload("gasoil", 2.4, "2026-09-13", "2026-09-13T12:00:00+00:00")
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        empty_database.insert_observation(payload)

    assert empty_database.observations(days=3650) == []


def test_insert_observation_rejects_a_unit_that_does_not_match_the_product(empty_database):
    payload = observation_payload("gasoil", 2.4, "2026-09-13", "2026-09-13T12:00:00+00:00")
    payload["unit"] = "USD/baril"

    with pytest.raises(ValueError, match="Unité invalide"):
        empty_database.insert_observation(payload)

    assert empty_database.observations(days=3650) == []


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


def test_create_procurement_calculates_total_budget_variance_and_price_impact(empty_database):
    empty_database.insert_observation(
        observation_payload("gasoil", 2.5, "2026-09-14", "2026-09-14T12:00:00+00:00")
    )

    purchase = empty_database.create_procurement(
        {
            "product": "gasoil",
            "supplier": "Supplier ABC",
            "quantity": 1000,
            "unit": "gallon",
            "currency": "EUR",
            "unit_price": 2,
            "exchange_rate": 1.1,
            "transport_cost": 100,
            "budget_amount": 5000,
            "purchase_date": "2026-09-15",
        }
    )

    assert purchase["total_cost"] == 2100.0
    assert purchase["total_cost_usd"] == 2310.0
    assert purchase["budget_variance"] == -2900.0
    assert purchase["budget_variance_usd"] == -3190.0
    assert purchase["market_price_usd"] == 2.5
    assert purchase["price_impact_unit_usd"] == -0.3
    assert purchase["price_impact_total_usd"] == -300.0
    assert purchase["price_impact_pct"] == -12.0
    assert empty_database.procurements(limit=10)[0]["supplier"] == "Supplier ABC"


def test_create_procurement_rejects_invalid_currency_and_exchange_rate(empty_database):
    payload = {
        "product": "brent",
        "supplier": "Supplier ABC",
        "quantity": 100,
        "unit": "baril",
        "currency": "EURO",
        "unit_price": 80,
        "exchange_rate": 1.1,
    }

    with pytest.raises(ValueError, match="trois lettres"):
        empty_database.create_procurement(payload)

    payload["currency"] = "EUR"
    payload["exchange_rate"] = 0
    with pytest.raises(ValueError, match="taux de change"):
        empty_database.create_procurement(payload)


def test_history_supports_filters_and_pagination(empty_database):
    rows = [
        ("gasoil", 2.0, "2026-09-01", "Alpha", "EIA"),
        ("gasoil", 3.0, "2026-09-02", "Beta", "Internal"),
        ("gasoil", 4.0, "2026-09-03", "Alpha", "EIA"),
    ]
    for product, price, source_date, supplier, source in rows:
        payload = observation_payload(product, price, source_date, f"{source_date}T12:00:00+00:00")
        payload.update({"supplier": supplier, "source": source})
        empty_database.insert_observation(payload)

    result = empty_database.history(
        product="gasoil",
        supplier="Alpha",
        source="EIA",
        date_from="2026-09-01",
        date_to="2026-09-03",
        min_price=2,
        max_price=4,
        page=1,
        page_size=1,
    )

    assert result["total"] == 2
    assert result["pages"] == 2
    assert result["items"][0]["price"] == 4.0
    assert result["items"][0]["supplier"] == "Alpha"


def test_compare_periods_returns_average_change(empty_database):
    for price, source_date in ((10.0, "2026-09-01"), (12.0, "2026-09-10")):
        empty_database.insert_observation(
            observation_payload("brent", price, source_date, f"{source_date}T12:00:00+00:00")
        )

    comparison = empty_database.compare_periods(
        "2026-09-01", "2026-09-05", "2026-09-06", "2026-09-15"
    )

    brent = comparison["products"]["brent"]
    assert brent["period_a"]["average"] == 10.0
    assert brent["period_b"]["average"] == 12.0
    assert brent["average_change"] == 2.0
    assert brent["average_change_pct"] == 20.0
