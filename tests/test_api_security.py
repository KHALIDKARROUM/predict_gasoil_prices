from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from price_monitor import app as app_module


class StubDatabase:
    def __init__(self) -> None:
        self.observation_calls = 0
        self.history_calls = 0
        self.alerts = []

    def observations(self, product=None, days=30, limit=600):
        self.observation_calls += 1
        return [{"product": product or "bitume", "days": days}]

    def insert_observation(self, payload):
        self.observation_calls += 1
        return payload

    def history(self, **kwargs):
        self.history_calls += 1
        return {"items": [{"product": "gasoil"}], "page": 1, "pages": 1, "total": 1}

    def compare_periods(self, *args, **kwargs):
        self.history_calls += 1
        return {"products": {}}

    def alert_rules(self):
        return self.alerts

    def create_alert_rule(self, payload):
        alert = {"id": 1, **payload, "status": "normal"}
        self.alerts = [alert]
        return alert

    def update_alert_rule(self, rule_id, payload):
        self.alerts[0].update(payload)
        return self.alerts[0]

    def delete_alert_rule(self, rule_id):
        self.alerts = []


@pytest.fixture
def api_server(monkeypatch):
    database = StubDatabase()
    monkeypatch.setattr(app_module, "database", database)
    monkeypatch.setattr(app_module, "API_KEY", "test-api-key")
    monkeypatch.setattr(app_module, "RATE_LIMIT_ENABLED", False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), app_module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, database
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, method, path, headers=None, body=None):
    connection = http.client.HTTPConnection(*server.server_address)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, result


def test_protected_routes_reject_missing_api_key(api_server):
    server, database = api_server

    status, headers, _ = request(server, "GET", "/api/observations")

    assert status == 401
    assert headers["WWW-Authenticate"] == 'Bearer realm="price-monitor"'
    assert database.observation_calls == 0


def test_protected_routes_accept_api_key_headers(api_server, monkeypatch):
    server, database = api_server
    monkeypatch.setattr(
        app_module,
        "run_collection",
        lambda _database: {"status": "success", "rows": 0, "message": "ok"},
    )

    status, _, _ = request(server, "GET", "/api/observations", {"X-API-Key": "test-api-key"})
    assert status == 200

    status, _, _ = request(
        server,
        "POST",
        "/api/collect",
        {"Authorization": "Bearer test-api-key", "Content-Length": "0"},
    )
    assert status == 200
    assert database.observation_calls == 1


def test_forecast_route_returns_public_market_forecast(api_server):
    server, database = api_server

    status, _, body = request(server, "GET", "/api/forecast?history_days=90")

    assert status == 200
    assert database.observation_calls == 2
    assert body and b'"products"' in body


def test_read_only_history_is_public_while_observation_writes_stay_protected(api_server):
    server, database = api_server

    status, _, body = request(server, "GET", "/api/history?page=1&page_size=50")

    assert status == 200
    assert database.history_calls == 1
    assert b'"total": 1' in body

    payload = json.dumps({"product": "bitume", "price": 500})
    status, _, _ = request(
        server,
        "POST",
        "/api/observations",
        {"Content-Type": "application/json", "Content-Length": str(len(payload))},
        payload,
    )
    assert status == 401


def test_alert_crud_requires_key_for_writes_and_supports_edit_and_delete(api_server):
    server, _ = api_server
    body = json.dumps({"product": "brent", "direction": "above", "threshold": 90, "channel": "webhook"})
    headers = {"X-API-Key": "test-api-key", "Content-Type": "application/json", "Content-Length": str(len(body))}

    status, _, _ = request(server, "POST", "/api/alerts", body=body)
    assert status == 401

    status, _, _ = request(server, "POST", "/api/alerts", headers=headers, body=body)
    assert status == 201
    status, _, body = request(server, "PUT", "/api/alerts/1", headers={**headers, "Content-Length": str(len('{"muted": true}'))}, body='{"muted": true}')
    assert status == 200
    assert b'"muted": true' in body
    status, _, _ = request(server, "DELETE", "/api/alerts/1", headers={"X-API-Key": "test-api-key"})
    assert status == 200


def test_rate_limiter_returns_retry_after_for_production_requests(api_server, monkeypatch):
    server, _ = api_server
    monkeypatch.setattr(app_module, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(app_module, "rate_limiter", app_module.RateLimiter(1, 60))
    headers = {"X-API-Key": "test-api-key"}

    first_status, _, _ = request(server, "GET", "/api/observations", headers)
    second_status, second_headers, _ = request(server, "GET", "/api/observations", headers)

    assert first_status == 200
    assert second_status == 429
    assert int(second_headers["Retry-After"]) >= 1


def test_missing_api_key_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "")
    monkeypatch.setattr(app_module, "ENVIRONMENT", "development")
    monkeypatch.setattr(app_module, "HOST", "127.0.0.1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), app_module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = request(server, "GET", "/api/observations")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 503


@pytest.mark.parametrize(
    ("environment", "host", "api_key", "should_fail"),
    [
        ("production", "127.0.0.1", "", True),
        ("development", "0.0.0.0", "", True),
        ("production", "127.0.0.1", "configured", False),
    ],
)
def test_security_configuration_requires_key_for_production_or_public_bind(
    monkeypatch, environment, host, api_key, should_fail
):
    monkeypatch.setattr(app_module, "ENVIRONMENT", environment)
    monkeypatch.setattr(app_module, "HOST", host)
    monkeypatch.setattr(app_module, "API_KEY", api_key)

    if should_fail:
        with pytest.raises(RuntimeError):
            app_module.validate_security_configuration()
    else:
        app_module.validate_security_configuration()
