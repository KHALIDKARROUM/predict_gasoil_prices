from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any

from ..config import ALPHA_VANTAGE_API_KEY, DEMO_MODE, FRED_API_KEY


class CollectionBatch(tuple):
    """A backwards-compatible pair with per-source outcomes attached."""

    source_health: list[dict[str, Any]]
    benchmarks: list[dict[str, Any]]

    def __new__(
        cls,
        observations: list[dict],
        messages: list[str],
        source_health: list[dict[str, Any]],
        benchmarks: list[dict[str, Any]] | None = None,
    ) -> "CollectionBatch":
        result = super().__new__(cls, (observations, messages))
        result.source_health = source_health
        result.benchmarks = list(benchmarks or [])
        return result


class CollectionError(RuntimeError):
    """Raised when every configured source fails, retaining source outcomes."""

    source_health: list[dict[str, Any]]

    def __init__(self, message: str, source_health: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.source_health = source_health


def _request_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "PriceMonitor/1.0"})
    with urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_gasoil() -> dict:
    if FRED_API_KEY:
        query = urlencode({"series_id": "DDFUELNYH", "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 10})
        data = _request_json(f"https://api.stlouisfed.org/fred/series/observations?{query}")
        for obs in data.get("observations", []):
            if obs.get("value") not in (None, "."):
                return {"product": "gasoil", "price": float(obs["value"]), "unit": "USD/gallon", "source": "EIA/FRED - DDFUELNYH", "source_code": "fred_diesel", "source_date": obs["date"], "notes": "Collecte API FRED"}
    raise RuntimeError("FRED_API_KEY non configurée")


def collect_brent() -> dict:
    if FRED_API_KEY:
        query = urlencode({"series_id": "DCOILBRENTEU", "api_key": FRED_API_KEY, "file_type": "json", "sort_order": "desc", "limit": 10})
        data = _request_json(f"https://api.stlouisfed.org/fred/series/observations?{query}")
        for obs in data.get("observations", []):
            if obs.get("value") not in (None, "."):
                return {"product": "brent", "price": float(obs["value"]), "unit": "USD/baril", "source": "EIA/FRED - DCOILBRENTEU", "source_code": "fred_brent", "source_date": obs["date"], "notes": "Collecte API FRED"}
    if ALPHA_VANTAGE_API_KEY:
        query = urlencode({"function": "BRENT", "interval": "daily", "apikey": ALPHA_VANTAGE_API_KEY, "datatype": "json"})
        data = _request_json(f"https://www.alphavantage.co/query?{query}")
        rows = data.get("data") or data.get("observations") or []
        for obs in rows:
            date = obs.get("date") or obs.get("timestamp")
            value = obs.get("value") or obs.get("price")
            if date and value not in (None, "."):
                return {"product": "brent", "price": float(value), "unit": "USD/baril", "source": "Alpha Vantage - BRENT", "source_code": "alpha_brent", "source_date": date[:10], "notes": "Collecte API Alpha Vantage"}
    raise RuntimeError("FRED_API_KEY ou ALPHA_VANTAGE_API_KEY non configurée")


def collect_bitumen_benchmark() -> dict:
    """Collect a free public asphalt PPI as a clearly labelled bitumen proxy.

    WPU058 is an official monthly U.S. producer-price index.  It is useful for
    direction and negotiation context, but it is not a cargo quote and must
    never be represented as USD/tonne.
    """
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/WPU058?latest=true"
    data = _request_json(url)
    results = data.get("Results") or {}
    series = results.get("series") if isinstance(results, dict) else None
    if data.get("status") != "REQUEST_SUCCEEDED" or not series:
        message = "; ".join(str(item) for item in data.get("message") or [])
        raise RuntimeError(message or "Indice bitume BLS indisponible")
    rows = series[0].get("data") or []
    for row in rows:
        period = str(row.get("period") or "")
        value = row.get("value")
        if period.startswith("M") and period != "M13" and value not in (None, ""):
            month = int(period[1:])
            return {
                "code": "bls_wpu058",
                "product": "bitume",
                "label": "Indice PPI asphalte et produits pétroliers (proxy bitume)",
                "value": float(value),
                "unit": "indice (déc. 1984 = 100)",
                "geography": "États-Unis",
                "source": "U.S. BLS Public Data API - WPU058",
                "source_code": "bls_asphalt_ppi",
                "source_date": f"{int(row['year']):04d}-{month:02d}-01",
                "source_url": "https://fred.stlouisfed.org/series/WPU058",
                "notes": (
                    "Indicateur mensuel de tendance. Ce n'est ni un prix international "
                    "en USD/tonne, ni une offre d'achat exécutable."
                ),
            }
    raise RuntimeError("Indice bitume BLS sans observation mensuelle exploitable")


def demo_observations() -> list[dict]:
    """A clearly labelled fallback for demonstrations and local development."""
    now = datetime.now(timezone.utc)
    jitter = random.uniform(-0.01, 0.01)
    return [
        {"product": "gasoil", "price": round(2.33 + jitter, 4), "unit": "USD/gallon", "source": "Mode démonstration - EIA/FRED", "source_date": now.date().isoformat(), "notes": "Source API non configurée; valeur de démonstration."},
        {"product": "brent", "price": round(81.4 + jitter * 10, 2), "unit": "USD/baril", "source": "Mode démonstration - Alpha Vantage", "source_date": now.date().isoformat(), "notes": "Source API non configurée; valeur de démonstration."},
        {"product": "bitume", "price": round(522 + jitter * 40, 2), "unit": "USD/tonne", "source": "Mode démonstration - saisie interne", "source_date": now.date().isoformat(), "notes": "À remplacer par un devis, une commande ou une facture validée."},
    ]


def collect_all() -> tuple[list[dict], list[str]]:
    if DEMO_MODE:
        return CollectionBatch(demo_observations(), ["Mode démonstration actif."], [], [])
    observations: list[dict] = []
    benchmarks: list[dict] = []
    messages: list[str] = []
    source_health: list[dict[str, Any]] = []
    for source_code, collector in (("fred_diesel", collect_gasoil), ("fred_brent", collect_brent)):
        try:
            observation = collector()
            observations.append(observation)
            source_health.append({"code": observation.get("source_code") or source_code, "success": True, "error": None})
        except Exception as exc:  # source failure must not stop the other source
            messages.append(str(exc))
            source_health.append({"code": source_code, "success": False, "error": str(exc)})
    try:
        benchmark = collect_bitumen_benchmark()
        benchmarks.append(benchmark)
        source_health.append(
            {"code": benchmark.get("source_code") or "bls_asphalt_ppi", "success": True, "error": None}
        )
    except Exception as exc:
        messages.append(str(exc))
        source_health.append({"code": "bls_asphalt_ppi", "success": False, "error": str(exc)})
    if not observations and not benchmarks:
        raise CollectionError(
            "Aucune source publique disponible. Configurez FRED_API_KEY et vérifiez l'accès à l'API BLS.",
            source_health,
        )
    return CollectionBatch(observations, messages, source_health, benchmarks)
