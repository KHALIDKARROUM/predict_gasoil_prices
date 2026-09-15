from __future__ import annotations

from datetime import datetime, timedelta, timezone

from price_monitor.services.alerts import AlertManager


class FakeNotifier:
    def __init__(self) -> None:
        self.batches = []

    def send(self, events):
        self.batches.append(events)
        return True


def test_price_alert_notifies_on_crossing_and_recovery(empty_database):
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    notifier = FakeNotifier()
    manager = AlertManager(
        empty_database,
        notifier=notifier,
        thresholds={"brent": {"above": 90}},
        now=lambda: now,
    )

    triggered = manager.evaluate_prices([{"product": "brent", "price": 91}])
    unchanged = manager.evaluate_prices([{"product": "brent", "price": 92}])
    recovered = manager.evaluate_prices([{"product": "brent", "price": 80}])

    assert [event.status for event in triggered] == ["triggered"]
    assert unchanged == []
    assert [event.status for event in recovered] == ["recovered"]
    assert [[event.status for event in batch] for batch in notifier.batches] == [
        ["triggered"],
        ["recovered"],
    ]


def test_source_failure_alert_recovers_after_success(empty_database):
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    notifier = FakeNotifier()
    manager = AlertManager(empty_database, notifier=notifier, now=lambda: now)
    failed_source = {
        "code": "fred_brent",
        "label": "Brent",
        "frequency": "quotidienne",
        "active": 1,
        "last_success_at": None,
        "last_error": "Service indisponible",
    }
    healthy_source = {
        **failed_source,
        "last_success_at": "2026-09-15T11:00:00+00:00",
        "last_error": None,
    }

    failed = manager.evaluate_sources([failed_source])
    recovered = manager.evaluate_sources([healthy_source])

    assert [event.kind for event in failed] == ["source_failure"]
    assert [event.status for event in recovered] == ["recovered"]
    assert recovered[0].kind == "source_failure"


def test_stale_source_alert_uses_expected_frequency(empty_database):
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    notifier = FakeNotifier()
    manager = AlertManager(empty_database, notifier=notifier, now=lambda: now)
    stale_source = {
        "code": "fred_diesel",
        "label": "Gasoil",
        "frequency": "quotidienne",
        "active": 1,
        "last_success_at": (now - timedelta(days=3)).isoformat(),
        "last_error": None,
    }

    events = manager.evaluate_sources([stale_source])

    assert len(events) == 1
    assert events[0].kind == "source_stale"
    assert events[0].status == "triggered"
