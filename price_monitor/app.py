from __future__ import annotations

import json
import mimetypes
import os
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import HOST, PORT
from .database import Database, PRODUCTS
from .services.export import csv_bytes, xlsx_bytes
from .services.scheduler import CollectionScheduler, run_collection


ROOT = Path(__file__).resolve().parent
database = Database()
scheduler = CollectionScheduler(database)


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

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            return self.serve_file(ROOT / "templates" / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            candidate = (ROOT / parsed.path.removeprefix("/static/")).resolve()
            if ROOT / "static" in candidate.parents:
                return self.serve_file(candidate, mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/dashboard":
                days = max(1, min(365, int(query.get("days", [30])[0])))
                return self.send_json(database.dashboard(days))
            if parsed.path == "/api/observations":
                product = query.get("product", [None])[0]
                days = max(1, min(365, int(query.get("days", [30])[0])))
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
        length = int(self.headers.get("Content-Length", 0))
        try:
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

