from __future__ import annotations

import json
import hmac
import mimetypes
import threading
import time
import traceback
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import (
    API_KEY,
    ENVIRONMENT,
    HOST,
    PORT,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from .database import create_database
from .services.export import csv_bytes, xlsx_bytes
from .services.scheduler import CollectionScheduler, run_collection


ROOT = Path(__file__).resolve().parent
database = create_database()
scheduler = CollectionScheduler(database)


class RateLimiter:
    """A small in-memory fixed-window limiter for one application process."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client_key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = self._requests.setdefault(client_key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.max_requests:
                retry_after = max(1, int(timestamps[0] + self.window_seconds - now + 0.999))
                return False, retry_after
            timestamps.append(now)
            return True, 0


rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)


def _is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def validate_security_configuration() -> None:
    """Prevent an explicitly public/production server from starting without a key."""
    if ENVIRONMENT in {"production", "prod"} and not API_KEY:
        raise RuntimeError("PRICE_MONITOR_API_KEY est obligatoire en production")
    if not _is_loopback_host(HOST) and not API_KEY:
        raise RuntimeError("PRICE_MONITOR_API_KEY est obligatoire lorsque PRICE_MONITOR_HOST est public")


def _authorization_value(handler: BaseHTTPRequestHandler) -> str:
    api_key = handler.headers.get("X-API-Key", "").strip()
    if api_key:
        return api_key
    authorization = handler.headers.get("Authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        return value.strip()
    return ""


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "PriceMonitor/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_data(self, body: bytes, content_type: str, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value: object, status: int = 200) -> None:
        self.send_data(json_bytes(value), "application/json; charset=utf-8", status)

    def _rate_limit(self) -> bool:
        if not RATE_LIMIT_ENABLED:
            return True
        allowed, retry_after = rate_limiter.check(self.client_address[0])
        if allowed:
            return True
        self.send_data(
            json_bytes({"error": "Trop de requêtes. Réessayez plus tard."}),
            "application/json; charset=utf-8",
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )
        return False

    def _authenticate_api(self) -> bool:
        if not API_KEY:
            self.send_json(
                {"error": "API non configurée. Définissez PRICE_MONITOR_API_KEY."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        if not hmac.compare_digest(_authorization_value(self), API_KEY):
            self.send_data(
                json_bytes({"error": "Authentification requise."}),
                "application/json; charset=utf-8",
                HTTPStatus.UNAUTHORIZED,
                headers={"WWW-Authenticate": 'Bearer realm="price-monitor"'},
            )
            return False
        return True

    def _protect_api(self) -> bool:
        return self._authenticate_api()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            return self.serve_file(ROOT / "templates" / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            candidate = (ROOT / parsed.path.lstrip("/")).resolve()
            if ROOT / "static" in candidate.parents:
                return self.serve_file(candidate, mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        query = parse_qs(parsed.query)
        try:
            if parsed.path.startswith("/api/") and not self._rate_limit():
                return
            if parsed.path == "/api/dashboard":
                days = max(1, min(1825, int(query.get("days", [30])[0])))
                return self.send_json(database.dashboard(days))
            if parsed.path == "/api/observations":
                if not self._protect_api():
                    return
                product = query.get("product", [None])[0]
                days = max(1, min(1825, int(query.get("days", [30])[0])))
                return self.send_json(database.observations(product, days))
            if parsed.path == "/api/logs":
                return self.send_json({"logs": database.logs()})
            if parsed.path == "/export.csv":
                body = csv_bytes(database.observations(days=3650, limit=100000))
                return self.send_data(body, "text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=price-observations.csv"})
            if parsed.path == "/export.xlsx":
                body = xlsx_bytes(database.observations(days=3650, limit=100000))
                return self.send_data(body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=price-observations.xlsx"})
            return self.send_json({"error": "Route introuvable"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/") and not self._rate_limit():
                return
            if parsed.path in {"/api/collect", "/api/observations"} and not self._protect_api():
                return
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/collect":
                return self.send_json(run_collection(database))
            if parsed.path == "/api/observations":
                record = database.insert_observation(payload)
                return self.send_json({"status": "success", "observation": record}, 201)
            return self.send_json({"error": "Route introuvable"}, 404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            return self.send_json({"error": str(exc)}, 500)

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            return self.send_json({"error": "Fichier introuvable"}, 404)
        self.send_data(path.read_bytes(), content_type)


def main() -> None:
    validate_security_configuration()
    scheduler.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Price Monitor disponible sur http://{HOST}:{PORT}")
    print("Collectes planifiées: 08:00, 11:00, 14:00, 17:00, 20:00")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Arrêt demandé.")
    finally:
        scheduler.stop()
        server.server_close()


if __name__ == "__main__":
    main()
