"""A2A discovery card, bearer auth, and task completion."""

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from a2a.server import A2AApp, make_server, start_a2a_server


def _runner(question, history, session_id):
    assert question == "持仓如何"
    assert history == []
    assert session_id is None
    return "组合平稳", 11


def test_agent_card_is_public_and_message_requires_token():
    app = A2AApp(token="secret", public_url="http://agent.example/", runner=_runner)
    status, card = app.handle("GET", "/.well-known/agent-card.json", {}, b"")
    assert status == 200
    assert card["url"] == "http://agent.example/"
    assert card["skills"][0]["id"] == "portfolio-query"
    assert card["securitySchemes"]["bearer"]["scheme"] == "bearer"

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {"role": "user", "parts": [{"kind": "text", "text": "持仓如何"}]}
            },
        }
    ).encode()
    status, denied = app.handle("POST", "/", {}, body)
    assert status == 401
    assert denied["error"] == "unauthorized"


def test_message_send_then_tasks_get_returns_answer():
    app = A2AApp(token="secret", public_url="http://127.0.0.1:8502/", runner=_runner)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "contextId": "ctx-1",
                    "parts": [{"kind": "text", "text": "持仓如何"}],
                }
            },
        }
    ).encode()
    headers = {"Authorization": "Bearer secret"}
    status, accepted = app.handle("POST", "/", headers, body)
    assert status == 200
    assert accepted["result"]["status"]["state"] == "working"
    task_id = accepted["result"]["id"]

    completed = None
    for _ in range(50):
        status, payload = app.handle(
            "POST",
            "/",
            headers,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "2",
                    "method": "tasks/get",
                    "params": {"id": task_id},
                }
            ).encode(),
        )
        assert status == 200
        if payload["result"]["status"]["state"] == "completed":
            completed = payload
            break
        threading.Event().wait(0.02)
    assert completed is not None
    assert completed["result"]["artifacts"][0]["parts"][0]["text"] == "组合平稳"
    assert app.contexts["ctx-1"]["session_id"] == 11


def test_http_round_trip_rejects_missing_token_and_serves_card():
    app = A2AApp(token="secret", public_url="http://127.0.0.1/", runner=_runner)
    httpd = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/.well-known/agent-card.json") as response:
            card = json.loads(response.read().decode())
        assert card["skills"][0]["id"] == "portfolio-query"

        request = Request(
            f"http://127.0.0.1:{port}/",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "message/send",
                    "params": {"message": {"parts": [{"kind": "text", "text": "持仓如何"}]}},
                }
            ).encode(),
            method="POST",
        )
        with pytest.raises(HTTPError) as raised:
            urlopen(request)
        assert raised.value.code == 401
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_start_refuses_enabled_server_without_token(monkeypatch):
    monkeypatch.setattr("a2a.server.config.A2A_ENABLED", True)
    monkeypatch.setattr("a2a.server.config.A2A_TOKEN", "")
    with pytest.raises(RuntimeError, match="A2A_TOKEN"):
        start_a2a_server()


def test_listener_shutdown_releases_port_and_can_restart(monkeypatch):
    from a2a import server

    monkeypatch.setattr(server.config, "A2A_ENABLED", True)
    monkeypatch.setattr(server.config, "A2A_TOKEN", "test-token")
    monkeypatch.setattr(server.config, "A2A_HOST", "127.0.0.1")
    monkeypatch.setattr(server.config, "A2A_PORT", 0)
    listener = server.start_a2a_server()
    port = listener.server_address[1]
    try:
        assert server.start_a2a_server() is listener
    finally:
        server.stop_a2a_server()
    server.stop_a2a_server()
    monkeypatch.setattr(server.config, "A2A_PORT", port)
    try:
        assert server.start_a2a_server().server_address[1] == port
    finally:
        server.stop_a2a_server()


def test_thread_start_failure_closes_listener_without_shutdown_deadlock(monkeypatch):
    from unittest.mock import Mock

    from a2a import server

    monkeypatch.setattr(server.config, "A2A_ENABLED", True)
    monkeypatch.setattr(server.config, "A2A_TOKEN", "test-token")
    listener = Mock()
    monkeypatch.setattr(server, "make_server", lambda *args: listener)
    monkeypatch.setattr(
        server.threading.Thread, "start", Mock(side_effect=RuntimeError("no threads"))
    )
    with pytest.raises(RuntimeError, match="no threads"):
        server.start_a2a_server()
    assert server._server is None
    listener.server_close.assert_called_once()
    listener.shutdown.assert_not_called()
