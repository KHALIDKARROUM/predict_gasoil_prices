from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..config import COLLECTION_TIMES
from ..database import Database
from .collectors import collect_all


class CollectionScheduler:
    """Lightweight cron-compatible scheduler; production can also call /api/collect from cron."""

    def __init__(self, database: Database):
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


def run_collection(database: Database) -> dict:
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        observations, messages = collect_all()
        for observation in observations:
            database.insert_observation(observation)
        finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        message = " ".join(messages) or "Collecte terminée avec succès."
        database.log_collection("success", len(observations), message, started, finished)
        return {"status": "success", "rows": len(observations), "message": message}
    except Exception as exc:
        finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        database.log_collection("error", 0, str(exc), started, finished)
        return {"status": "error", "rows": 0, "message": str(exc)}

