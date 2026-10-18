"""Verify process lifecycle without launching live providers or background jobs."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import runtime


@pytest.fixture
def services(monkeypatch):
    from a2a import server
    from adapters import base
    from adapters.base import AdapterRegistry
    from db import migrate, repository
    from memory import indexer
    from notifier import telegram
    from scheduler import cron

    events = []
    monkeypatch.setattr(runtime, "_services", None)
    monkeypatch.setattr(runtime, "_infrastructure_ready", False)
    monkeypatch.setattr(base, "registry", AdapterRegistry())
    monkeypatch.setattr(repository, "init_db", lambda: events.append("db"))
    monkeypatch.setattr(migrate, "migrate", lambda engine: events.append("migrate"))
    for module, name, event in (
        (indexer, "start_worker", "memory+"),
        (indexer, "stop_worker", "memory-"),
        (cron, "start_scheduler", "scheduler+"),
        (cron, "stop_scheduler", "scheduler-"),
        (server, "start_a2a_server", "api+"),
        (server, "stop_a2a_server", "api-"),
        (telegram, "send_welcome", "welcome"),
    ):
        monkeypatch.setattr(module, name, lambda *args, event=event: events.append(event))
    yield events
    runtime.stop_services()


def test_concurrent_reruns_start_only_one_service_set(services):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: runtime.start_services(include_api=True), range(20)))
    assert services == ["db", "migrate", "memory+", "scheduler+", "api+", "welcome"]
    runtime.stop_services()
    runtime.stop_services()
    assert services[-3:] == ["api-", "scheduler-", "memory-"]


def test_direct_ui_start_keeps_api_off(services):
    runtime.start_services()
    assert "api+" not in services
    runtime.stop_services()
    assert services[-2:] == ["scheduler-", "memory-"]


def test_api_failure_cleans_up_and_allows_retry(services, monkeypatch):
    from a2a import server

    failure = Mock(side_effect=RuntimeError("invalid API configuration"))
    monkeypatch.setattr(server, "start_a2a_server", failure)
    with pytest.raises(RuntimeError, match="invalid API"):
        runtime.start_services(include_api=True)
    assert services[-3:] == ["api-", "scheduler-", "memory-"]
    assert runtime._services is None
    monkeypatch.setattr(server, "start_a2a_server", lambda: services.append("api+"))
    runtime.start_services(include_api=True)
    assert services.count("db") == 1
    assert services[-1] == "welcome"


def test_optional_notification_failure_keeps_services_running(services, monkeypatch):
    from notifier import telegram

    monkeypatch.setattr(telegram, "send_welcome", Mock(side_effect=OSError("offline")))
    runtime.start_services()
    assert runtime._services is not None
    assert "scheduler-" not in services


def test_importing_server_does_not_bootstrap(monkeypatch):
    import server

    start = Mock(side_effect=AssertionError("import must be inert"))
    monkeypatch.setattr(runtime, "start_services", start)
    importlib.reload(server)
    start.assert_not_called()


def test_memory_worker_can_stop_and_restart_without_overlapping(monkeypatch):
    import threading

    from memory import indexer

    observed = threading.Event()
    monkeypatch.setattr(indexer.config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(indexer, "initialize", lambda engine: None)
    monkeypatch.setattr(indexer, "tick", lambda engine: observed.set())
    monkeypatch.setattr(indexer, "_thread", None)
    monkeypatch.setattr(indexer, "_stop", threading.Event())
    try:
        indexer.start_worker(None)
        assert observed.wait(1)
        first = indexer._thread
        indexer.stop_worker()
        assert not first.is_alive()
        observed.clear()
        indexer.start_worker(None)
        assert observed.wait(1)
        assert indexer._thread is not first
    finally:
        indexer.stop_worker()


def test_memory_thread_start_failure_is_safe_to_clean_up(monkeypatch):
    import threading

    from memory import indexer

    monkeypatch.setattr(indexer.config, "MEMORY_ENABLED", True)
    monkeypatch.setattr(indexer, "initialize", lambda engine: None)
    monkeypatch.setattr(indexer, "_thread", None)
    monkeypatch.setattr(indexer, "_stop", threading.Event())
    monkeypatch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("no threads")))
    with pytest.raises(RuntimeError, match="no threads"):
        indexer.start_worker(None)
    indexer.stop_worker()
    assert indexer._thread is None
