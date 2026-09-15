from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..config import COLLECTION_TIMES
from ..database import DatabaseBackend
from ..observability import logger, metrics
from .alerts import AlertManager
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

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        last_slot = None
        last_health_check = 0.0
        while not self._stop.wait(20):
            now = datetime.now().astimezone()
            if time.monotonic() - last_health_check >= 300:
                last_health_check = time.monotonic()
                evaluate_source_alerts(self.database)
            slot = now.strftime("%H:%M")
            token = now.date().isoformat() + slot
            if slot in COLLECTION_TIMES and token != last_slot:
                last_slot = token
                try:
                    run_collection(self.database)
                except Exception:
                    # The scheduler must survive a single failed scheduled run.
                    logger.exception("Scheduled collection failed", extra={"event": "collection_scheduler_error"})


def evaluate_source_alerts(database: DatabaseBackend) -> None:
    """Check source freshness even when a scheduled collection is missed."""
    try:
        AlertManager(database).evaluate_sources(database.source_health())
    except Exception:
        # Alerting must never stop the collection scheduler.
        logger.exception("Source alert evaluation failed", extra={"event": "source_alert_evaluation_failed"})


def _evaluate_collection_alerts(database: DatabaseBackend, observations: list[dict]) -> None:
    try:
        AlertManager(database).evaluate_collection(observations, database.source_health())
    except Exception:
        # Alerting must never turn a successful collection into an error.
        logger.exception("Collection alert evaluation failed", extra={"event": "collection_alert_evaluation_failed"})


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
        _evaluate_collection_alerts(database, observations)
        metrics.increment("price_monitor_collection_total", labels={"status": status})
        logger.info(
            "Collection completed",
            extra={"event": "collection_completed", "status": status, "rows": len(observations)},
        )
        return {"status": status, "rows": len(observations), "message": message}
    except Exception as exc:
        finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if not source_outcomes:
            source_outcomes = list(getattr(exc, "source_health", []))
        _update_source_health(database, source_outcomes, finished)
        database.log_collection("error", 0, str(exc), started, finished)
        _evaluate_collection_alerts(database, [])
        metrics.increment("price_monitor_collection_total", labels={"status": "error"})
        logger.exception("Collection failed", extra={"event": "collection_failed"})
        return {"status": "error", "rows": 0, "message": str(exc)}
