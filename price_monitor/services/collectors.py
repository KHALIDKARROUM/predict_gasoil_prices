from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import ALPHA_VANTAGE_API_KEY, DEMO_MODE, FRED_API_KEY


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
                return {"product": "gasoil", "price": float(obs["value"]), "unit": "USD/gallon", "source": "EIA/FRED - DDFUELNYH", "source_date": obs["date"], "notes": "Collecte API FRED"}
    raise RuntimeError("FRED_API_KEY non configurée")


def collect_brent() -> dict:
    if ALPHA_VANTAGE_API_KEY:
        query = urlencode({"function": "BRENT", "interval": "daily", "apikey": ALPHA_VANTAGE_API_KEY, "datatype": "json"})
        data = _request_json(f"https://www.alphavantage.co/query?{query}")
        rows = data.get("data") or data.get("observations") or []
        for obs in rows:
            date = obs.get("date") or obs.get("timestamp")
            value = obs.get("value") or obs.get("price")
            if date and value not in (None, "."):
                return {"product": "brent", "price": float(value), "unit": "USD/baril", "source": "Alpha Vantage - BRENT", "source_date": date[:10], "notes": "Collecte API Alpha Vantage"}
    raise RuntimeError("ALPHA_VANTAGE_API_KEY non configurée")


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
    observations: list[dict] = []
    messages: list[str] = []
    for collector in (collect_gasoil, collect_brent):
        try:
            observations.append(collector())
        except Exception as exc:  # source failure must not stop the other source
            messages.append(str(exc))
    if DEMO_MODE or len(observations) < 2:
        observations = demo_observations()
        messages.append("Mode démonstration actif ou source publique indisponible.")
    return observations, messages

