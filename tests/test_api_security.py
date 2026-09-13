from __future__ import annotations

import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

from price_monitor import app as app_module


class StubDatabase:
    def __init__(self) -> None:
        self.observation_calls = 0

    def observations(self, product=None, days=30):
        self.observation_calls += 1
        return [{"product": product or "bitume", "days": days}]

    def insert_observation(self, payload):
        self.observation_calls += 1
        return payload


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
