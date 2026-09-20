from __future__ import annotations

from datetime import datetime, timedelta, timezone

from price_monitor.services.forecasting import build_forecast, daily_series, forecast_product


def synthetic_rows(count: int = 220) -> list[dict]:
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    return [
        {
            "product": "gasoil",
            "price": round(2.0 + index * 0.004 + (index % 5) * 0.002, 5),
            "source_date": (start + timedelta(days=index)).date().isoformat(),
            "collected_at": (start + timedelta(days=index)).isoformat(),
        }
        for index in range(count)
    ]


def test_daily_series_keeps_latest_intraday_observation():
    rows = [
        {"price": 80, "source_date": "2026-01-01", "collected_at": "2026-01-01T08:00:00+00:00"},
        {"price": 82, "source_date": "2026-01-01", "collected_at": "2026-01-01T17:00:00+00:00"},
    ]

    assert daily_series(rows) == [{"date": "2026-01-01", "value": 82.0}]


def test_forecast_returns_all_horizons_confidence_bands_and_backtest_metrics():
    result = forecast_product(synthetic_rows(), "gasoil")

    assert result["status"] == "ready"
    assert result["model"] == "damped_holt"
    assert result["history_count"] == 220
    for horizon in (7, 30, 90):
        points = result["forecasts"][str(horizon)]
        assert len(points) == horizon
        assert points[0]["lower"] <= points[0]["value"] <= points[0]["upper"]
        assert points[-1]["date"] == (datetime(2026, 8, 8) + timedelta(days=horizon)).date().isoformat()
        assert result["backtest"][str(horizon)]["available"] is True
        assert result["backtest"][str(horizon)]["mape"] is not None


def test_forecast_marks_short_history_as_insufficient():
    result = forecast_product(synthetic_rows(12), "brent")

    assert result["status"] == "insufficient_data"
    assert result["forecasts"] == {}


class ForecastDatabase:
    def observations(self, product=None, days=30, limit=600):
        rows = synthetic_rows()
        for row in rows:
            row["product"] = product
        return rows


def test_build_forecast_returns_both_market_products():
    result = build_forecast(ForecastDatabase())

    assert result["horizons"] == [7, 30, 90]
    assert set(result["products"]) == {"gasoil", "brent"}
    assert result["products"]["gasoil"]["status"] == "ready"
