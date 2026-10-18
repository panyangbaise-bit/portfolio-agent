"""External ledger, A2A v1, Actions, and read-only enforcement."""

import json
import threading
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from a2a.actions import openapi_schema
from a2a.queries import read_query
from a2a.server import A2AApp
from db.models import Base, Holding, Transaction


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                Holding(id=1, ticker="TEST", market="US", shares=2, cost_basis=10, status="open"),
                Holding(id=2, ticker="TEST", market="HK", shares=0, cost_basis=20, status="closed"),
                Holding(
                    id=3, ticker="HIDDEN", market="US", shares=0, cost_basis=30, status="archived"
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                Transaction(
                    id=1, holding_id=1, action="buy", shares=3, price=10, date=datetime(2026, 10, 1)
                ),
                Transaction(
                    id=2,
                    holding_id=1,
                    action="sell",
                    shares=1,
                    price=12,
                    date=datetime(2026, 10, 15, 23, 59),
                ),
                Transaction(
                    id=3,
                    holding_id=2,
                    action="sell",
                    shares=2,
                    price=20,
                    date=datetime(2026, 10, 15),
                ),
                Transaction(
                    id=4,
                    holding_id=3,
                    action="sell",
                    shares=2,
                    price=30,
                    date=datetime(2026, 10, 15),
                ),
            ]
        )
        db.commit()
    monkeypatch.setattr("a2a.queries.get_session", lambda: Session(engine))
    yield engine
    engine.dispose()


def rpc(app, method, params, v1=False):
    return app.handle(
        "POST",
        "/a2a/v1" if v1 else "/",
        {"authorization": "Bearer a2a"},
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
    )[1]


def test_ledger_market_closed_positions_pagination_and_dates(ledger):
    assert read_query("holdings")["total"] == 1
    assert read_query("holdings", {"status": "all"})["total"] == 2
    assert (
        read_query("holdings", {"market": "HK", "status": "closed"})["items"][0]["currency"]
        == "HKD"
    )
    page = read_query(
        "transactions",
        {"ticker": "test", "start_date": "2026-10-15", "end_date": "2026-10-15", "limit": 1},
    )
    assert page["total"] == 2 and page["next_offset"] == 1
    assert page["items"][0]["transaction_id"] == 2
    assert page["items"][0]["amount"] == 12
    assert read_query("transactions", {"market": "US", "action": "buy"})["total"] == 1


@pytest.mark.parametrize(
    "filters",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"market": "XX"},
        {"start_date": "bad"},
        {"action": "delete"},
        {"extra": "value"},
        {"start_date": "2026-10-16", "end_date": "2026-10-01"},
    ],
)
def test_invalid_filters_are_errors_not_empty_ledgers(ledger, filters):
    with pytest.raises(ValueError):
        read_query("transactions", filters)


def test_a2a_v1_real_ledger_data_and_stable_ids(ledger):
    app = A2AApp("a2a", "http://localhost:8502")
    status, card = app.handle("GET", "/a2a/v1/.well-known/agent-card.json", {}, b"")
    assert status == 200 and card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    result = rpc(
        app,
        "SendMessage",
        {
            "message": {
                "messageId": "one",
                "role": "ROLE_USER",
                "parts": [{"data": {"operation": "transactions", "filters": {"market": "HK"}}}],
            },
            "configuration": {"returnImmediately": False},
        },
        v1=True,
    )
    task = result["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["parts"][0]["data"]["items"][0]["currency"] == "HKD"
    later = rpc(app, "GetTask", {"id": task["id"]}, v1=True)["result"]
    assert later == task


def test_actions_auth_is_separate_and_schema_is_public(ledger):
    app = A2AApp("a2a", "http://localhost", actions_token="gpt")
    assert app.handle("GET", "/openapi.json", {}, b"")[0] == 200
    for headers in ({}, {"Authorization": "Bearer a2a"}, {"Authorization": "Bearer 中文"}):
        assert app.handle("GET", "/api/v1/holdings", headers, b"")[0] == 401
    status, data = app.handle(
        "GET", "/api/v1/holdings?status=all", {"Authorization": "Bearer gpt"}, b""
    )
    assert status == 200 and data["total"] == 2
    assert app.handle("POST", "/", {"Authorization": "Bearer gpt"}, b"{}")[0] == 401
    for query in ("limit=101", "market=CN&market=US", "limit=bad"):
        assert (
            app.handle("GET", "/api/v1/holdings?" + query, {"Authorization": "Bearer gpt"}, b"")[0]
            == 400
        )


def test_async_queries_retry_followup_and_result_pagination():
    release = threading.Event()
    calls = []

    def runner(question, history, sid):
        calls.append((question, history, sid))
        release.wait(2)
        return "正文" * 15000, 42

    app = A2AApp("a2a", "http://localhost", runner=runner, actions_token="gpt")
    headers = {"Authorization": "Bearer gpt"}
    body = json.dumps({"question": "查询", "request_id": "retry1"}).encode()
    status, first = app.handle("POST", "/api/v1/queries", headers, body)
    assert status == 202 and first["status"] == "working"
    _, retry = app.handle("POST", "/api/v1/queries", headers, body)
    assert first["task_id"] == retry["task_id"]
    busy = json.dumps({"question": "追问", "context_id": first["context_id"]}).encode()
    assert app.handle("POST", "/api/v1/queries", headers, busy)[0] == 429
    assert "error" in rpc(app, "tasks/get", {"id": first["task_id"]})
    release.set()
    assert app.tasks[first["task_id"]]["done"].wait(2)
    _, done = app.handle("GET", "/api/v1/queries/" + first["task_id"], headers, b"")
    assert done["status"] == "completed" and done["next_offset"] == 20000
    _, rest = app.handle(
        "GET", "/api/v1/queries/" + first["task_id"] + "?offset=20000", headers, b""
    )
    assert done["answer"] + rest["answer"] == "正文" * 15000
    _, followup = app.handle("POST", "/api/v1/queries", headers, busy)
    assert app.tasks[followup["task_id"]]["done"].wait(2)
    assert len(calls) == 2 and calls[1][2] == 42 and calls[1][1][0]["content"] == "查询"


def test_external_mutations_rejected_even_if_model_requests_them():
    from langchain_core.messages import AIMessage

    from agent.tool_guards import execute_tool_calls

    class Tool:
        name = "add_to_watchlist"

        def invoke(self, args):
            pytest.fail("External query must never mutate watchlist")

    result = execute_tool_calls(
        {
            "read_only": True,
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "add_to_watchlist", "id": "x", "args": {"ticker": "X"}},
                    ],
                )
            ],
        },
        [Tool()],
    )
    assert json.loads(result["messages"][0].content)["error"] == "read_only"


def test_actions_schema_has_unique_operations_and_no_write_endpoints():
    schema = openapi_schema("https://portfolio.example.com")
    operations = [operation for path in schema["paths"].values() for operation in path.values()]
    assert len({op["operationId"] for op in operations}) == 4
    assert all(op["x-openai-isConsequential"] is False for op in operations)
    assert all(len(op["description"]) <= 300 for op in operations)
    assert schema["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(
    "message",
    [
        {"parts": {}},
        {"parts": [{"text": "hi"}], "contextId": []},
        {"parts": [{"data": {"operation": "delete"}}]},
        {"parts": [{"text": "x" * 8001}]},
    ],
)
def test_malformed_messages_do_not_launch_a_task(message):
    app = A2AApp("a2a", "http://localhost", runner=lambda *args: ("unexpected", None))
    result = rpc(app, "message/send", {"message": message})
    assert "error" in result
    assert not app.tasks
