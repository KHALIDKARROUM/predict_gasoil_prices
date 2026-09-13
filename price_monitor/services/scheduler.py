from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..config import COLLECTION_TIMES
from ..database import DatabaseBackend
from .collectors import collect_all


SOURCE_CODE_BY_LABEL = {
    "EIA/FRED - DDFUELNYH": "fred_diesel",
    "EIA/FRED - DCOILBRENTEU": "fred_brent",
    "Alpha Vantage - BRENT": "alpha_brent",
}


def _observation_source_health(observations: list[dict]) -> list[dict]:
    """Infer source success for compatible/custom collectors without metadata."""
    outcomes: list[dict] = []
    for observation in observations:
        code = observation.get("source_code") or SOURCE_CODE_BY_LABEL.get(observation.get("source"))
        if code:
            outcomes.append({"code": code, "success": True, "error": None})
    return outcomes


def _update_source_health(database: DatabaseBackend, outcomes: list[dict], at: str) -> None:
    updater = getattr(database, "update_source_health", None)
    if updater is None:
        return
    for outcome in outcomes:
        code = outcome.get("code")
        if not code:
            continue
        updater(
            str(code),
            bool(outcome.get("success")),
            at,
            str(outcome.get("error")) if outcome.get("error") else None,
        )


def _collection_status(
    observations: list[dict],
    messages: list[str],
    source_outcomes: list[dict],
    has_source_metadata: bool,
) -> str:
    """Return the collection status without hiding source-level failures."""
    successful_sources = any(bool(outcome.get("success")) for outcome in source_outcomes)
    failed_sources = any(not bool(outcome.get("success")) for outcome in source_outcomes)

    if successful_sources and failed_sources:
        return "partial"

    # Older/custom collectors may not attach source metadata. In that case,
    # observations plus an error message still unambiguously means partial.
    if not has_source_metadata and observations and messages:
        return "partial"

    return "success"


class CollectionScheduler:
    """Lightweight cron-compatible scheduler; production can also call /api/collect from cron."""

    def __init__(self, database: DatabaseBackend):
        self.database = database
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="price-collection", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        last_slot = None
        while not self._stop.wait(20):
            now = datetime.now().astimezone()
            slot = now.strftime("%H:%M")
            token = now.date().isoformat() + slot
            if slot in COLLECTION_TIMES and token != last_slot:
                last_slot = token
                run_collection(self.database)


def run_collection(database: DatabaseBackend) -> dict:
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    source_outcomes: list[dict] = []
    try:
        batch = collect_all()
        observations, messages = batch
        source_health = getattr(batch, "source_health", None)
        has_source_metadata = source_health is not None
        source_outcomes = list(source_health or []) or _observation_source_health(observations)
        for observation in observations:
            database.insert_observation(observation)
        finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        _update_source_health(database, source_outcomes, finished)
        message = " ".join(messages) or "Collecte terminée avec succès."
        status = _collection_status(observations, messages, source_outcomes, has_source_metadata)
        database.log_collection(status, len(observations), message, started, finished)
        return {"status": status, "rows": len(observations), "message": message}
    except Exception as exc:
        finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if not source_outcomes:
            source_outcomes = list(getattr(exc, "source_health", []))
        _update_source_health(database, source_outcomes, finished)
        database.log_collection("error", 0, str(exc), started, finished)
        return {"status": "error", "rows": 0, "message": str(exc)}
