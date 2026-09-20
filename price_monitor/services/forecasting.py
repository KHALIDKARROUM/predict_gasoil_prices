"""Short-horizon market-price forecasting and walk-forward validation.

The service intentionally uses only the Python standard library.  This keeps
forecasting available in the production image without making the exploratory
notebook dependencies part of the runtime.  A damped Holt trend is a good
fit for these slowly moving daily commodity series and is more transparent to
users than an opaque model with no validation metrics.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Iterable


FORECAST_PRODUCTS = ("gasoil", "brent")
FORECAST_HORIZONS = (7, 30, 90)
DEFAULT_HISTORY_DAYS = 1825
MAX_HISTORY_ROWS = 5000
MIN_OBSERVATIONS = 30

PRODUCT_META = {
    "gasoil": {"label": "Gasoil / diesel", "unit": "USD/gallon"},
    "brent": {"label": "Pétrole Brent", "unit": "USD/baril"},
}


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_day(row: dict[str, Any]) -> date:
    source_date = row.get("source_date")
    if source_date:
        return date.fromisoformat(str(source_date)[:10])
    return _parse_datetime(row["collected_at"]).date()


def daily_series(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated intraday observations to the latest value per day."""
    latest: dict[date, tuple[datetime, float]] = {}
    for row in rows:
        try:
            price = float(row["price"])
            if not math.isfinite(price) or price <= 0:
                continue
            collected_at = _parse_datetime(row.get("collected_at", row.get("source_date")))
            day = _row_day(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        previous = latest.get(day)
        if previous is None or collected_at >= previous[0]:
            latest[day] = (collected_at, price)
    return [{"date": day.isoformat(), "value": value} for day, (_, value) in sorted(latest.items())]


def _damped_holt(values: list[float], horizon: int) -> list[float]:
    """Forecast with a damped trend exponential-smoothing model."""
    if not values:
        return []
    if len(values) == 1:
        return [values[0]] * horizon

    # A recent window limits the effect of old regimes while retaining enough
    # history for the 90-day forecast to estimate a stable trend.
    window_size = min(len(values), max(90, horizon * 3, 180))
    series = values[-window_size:]
    alpha = 0.32
    beta = 0.08
    damping = 0.985
    level = series[0]
    trend = series[1] - series[0]
    for observed in series[1:]:
        previous_level = level
        level = alpha * observed + (1 - alpha) * (level + damping * trend)
        trend = beta * (level - previous_level) + (1 - beta) * damping * trend

    predictions: list[float] = []
    damped_trend = 0.0
    for step in range(1, horizon + 1):
        damped_trend = damping * damped_trend + damping ** step
        prediction = max(0.000001, level + damped_trend * trend)
        predictions.append(prediction)
    return predictions


def _residual_standard_deviation(values: list[float]) -> float:
    """Estimate one-step residual noise with a short walk-forward pass."""
    if len(values) < 3:
        return max(values[0] * 0.01, 0.000001) if values else 1.0
    start = max(2, len(values) - 120)
    residuals: list[float] = []
    for origin in range(start, len(values)):
        prediction = _damped_holt(values[:origin], 1)[0]
        residuals.append(values[origin] - prediction)
    if not residuals:
        return max(mean(values) * 0.01, 0.000001)
    # Keep a small non-zero band for nearly constant test/demo series.
    return max(pstdev(residuals), mean(values) * 0.01, 0.000001)


def _backtest(values: list[float], horizon: int) -> dict[str, Any]:
    """Evaluate the same model at several historical forecast origins."""
    minimum_train = max(MIN_OBSERVATIONS, min(len(values) - horizon, max(60, horizon * 2)))
    latest_origin = len(values) - horizon
    if latest_origin < minimum_train:
        return {"available": False, "samples": 0, "mae": None, "rmse": None, "mape": None}

    available_origins = list(range(minimum_train, latest_origin + 1))
    max_folds = 5
    if len(available_origins) > max_folds:
        step = (len(available_origins) - 1) / (max_folds - 1)
        origins = [available_origins[round(index * step)] for index in range(max_folds)]
    else:
        origins = available_origins

    errors: list[float] = []
    percentage_errors: list[float] = []
    for origin in origins:
        predictions = _damped_holt(values[:origin], horizon)
        actuals = values[origin: origin + horizon]
        for actual, prediction in zip(actuals, predictions):
            error = prediction - actual
            errors.append(error)
            if actual:
                percentage_errors.append(abs(error) / abs(actual) * 100)

    if not errors:
        return {"available": False, "samples": 0, "mae": None, "rmse": None, "mape": None}
    return {
        "available": True,
        "folds": len(origins),
        "samples": len(errors),
        "mae": round(mean(abs(error) for error in errors), 6),
        "rmse": round(math.sqrt(mean(error * error for error in errors)), 6),
        "mape": round(mean(percentage_errors), 4) if percentage_errors else None,
    }


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def forecast_product(rows: Iterable[dict[str, Any]], product: str, horizons: tuple[int, ...] = FORECAST_HORIZONS) -> dict[str, Any]:
    series = daily_series(rows)
    meta = PRODUCT_META[product]
    base: dict[str, Any] = {
        "product": product,
        "label": meta["label"],
        "unit": meta["unit"],
        "model": "damped_holt",
        "history_count": len(series),
        "history": series[-120:],
        "forecasts": {},
        "backtest": {},
    }
    if not series:
        base.update({"status": "insufficient_data", "message": "Aucun historique disponible."})
        return base
    base["last_actual"] = series[-1]
    if len(series) < MIN_OBSERVATIONS:
        base.update({
            "status": "insufficient_data",
            "message": f"Au moins {MIN_OBSERVATIONS} relevés journaliers sont nécessaires.",
        })
        return base

    values = [float(item["value"]) for item in series]
    last_day = date.fromisoformat(series[-1]["date"])
    residual_std = _residual_standard_deviation(values)
    base.update({
        "status": "ready",
        "training_start": series[0]["date"],
        "training_end": series[-1]["date"],
        "residual_std": _round(residual_std),
    })
    for horizon in horizons:
        predictions = _damped_holt(values, horizon)
        points = []
        for index, prediction in enumerate(predictions, start=1):
            interval = 1.96 * residual_std * math.sqrt(index)
            points.append({
                "date": (last_day + timedelta(days=index)).isoformat(),
                "value": _round(prediction),
                "lower": _round(max(0.000001, prediction - interval)),
                "upper": _round(prediction + interval),
            })
        base["forecasts"][str(horizon)] = points
        base["backtest"][str(horizon)] = _backtest(values, horizon)
    return base


def build_forecast(database: Any, history_days: int = DEFAULT_HISTORY_DAYS) -> dict[str, Any]:
    """Build forecasts for the two externally collected market products."""
    history_days = max(90, min(DEFAULT_HISTORY_DAYS, int(history_days)))
    products: dict[str, Any] = {}
    for product in FORECAST_PRODUCTS:
        rows = database.observations(product, days=history_days, limit=MAX_HISTORY_ROWS)
        products[product] = forecast_product(rows, product)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history_days": history_days,
        "horizons": list(FORECAST_HORIZONS),
        "products": products,
    }
