"""GPT Actions REST facade over the same read-only query/task service."""

import json
import uuid
from urllib.parse import parse_qs


def _filters(query):
    values = parse_qs(query, keep_blank_values=True)
    if any(len(v) != 1 for v in values.values()):
        raise ValueError("Duplicate query parameter")
    return {k: v[0] for k, v in values.items()}


def task_response(app, task_id, offset=0):
    with app._lock:
        app._prune()
        task = app.tasks.get(task_id)
        if task is None or task["channel"] != "actions":
            return 404, {"error": "Task not found (expired or server restarted)"}
        answer = task.get("text") or ""
        end = offset + 20000
        return 200, {
            "task_id": task["id"],
            "context_id": task["contextId"],
            "status": task["state"],
            "answer": answer[offset:end],
            "answer_offset": offset,
            "next_offset": end if end < len(answer) else None,
            "error": task.get("error") or None,
            "retry_after_seconds": 5 if task["state"] == "working" else 0,
        }


def handle_actions(app, method, route, query, headers, body):
    from a2a.server import _authorized

    if method == "GET" and route == "/openapi.json":
        return 200, openapi_schema(app.actions_url)
    if not _authorized(headers, app.actions_token):
        return 401, {"error": "unauthorized"}
    try:
        if method == "GET" and route in {"/api/v1/holdings", "/api/v1/transactions"}:
            return 200, app.reader(route.rsplit("/", 1)[-1], _filters(query))
        if method == "POST" and route == "/api/v1/queries":
            payload = json.loads(body)
            if not isinstance(payload, dict) or set(payload) - {
                "question",
                "context_id",
                "request_id",
            }:
                raise ValueError("Expected question, optional context_id and request_id")
            question = payload.get("question")
            if not isinstance(question, str) or not question.strip() or len(question) > 8000:
                raise ValueError("question must contain 1–8000 characters")
            result = app._message_send(
                None,
                {
                    "message": {
                        "messageId": payload.get("request_id") or uuid.uuid4().hex,
                        "contextId": payload.get("context_id"),
                        "parts": [{"kind": "text", "text": question}],
                    }
                },
                channel="actions",
            )
            if "error" in result:
                error = result["error"]
                return (429 if error["code"] == -32000 else 400), {"error": error["message"]}
            _, data = task_response(app, result["result"]["id"])
            return 202, data
        if method == "GET" and route.startswith("/api/v1/queries/"):
            params = _filters(query)
            if set(params) - {"offset"}:
                raise ValueError("Only offset is supported")
            from a2a.queries import _integer

            offset = _integer(params.get("offset"), "offset", 0, 0, 10_000_000)
            return task_response(app, route.rsplit("/", 1)[-1], offset)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return 400, {"error": str(exc)}
    return 404, {"error": "not found"}


def openapi_schema(public_url):
    def prop(kind, **kwargs):
        return {"type": kind, **kwargs}

    def param(name, schema, description=""):
        return {
            "name": name,
            "in": "query",
            "required": False,
            "description": description,
            "schema": schema,
        }

    def response(schema, description="Successful response"):
        return {"description": description, "content": {"application/json": {"schema": schema}}}

    def ref(name):
        return {"$ref": "#/components/schemas/" + name}

    errors = {
        str(code): response(ref("Error"), label)
        for code, label in (
            (400, "Invalid input"),
            (401, "Bearer token required"),
            (404, "Not found or expired"),
            (429, "Busy; retry later"),
            (500, "Query failed"),
        )
    }
    common = [
        param("ticker", prop("string", maxLength=20)),
        param("market", prop("string", enum=["US", "CN", "HK", "CRYPTO"])),
        param("limit", prop("integer", minimum=1, maximum=100, default=25)),
        param("offset", prop("integer", minimum=0, maximum=1000000, default=0)),
    ]
    paths = {}
    for kind, operation_id, description, extra in [
        (
            "holdings",
            "getPortfolioHoldings",
            "Read stored holdings and broker unit costs. These are not live quotes or returns. Follow next_offset for all rows.",
            [param("status", prop("string", enum=["open", "closed", "all"], default="open"))],
        ),
        (
            "transactions",
            "getPortfolioTransactions",
            "Read recorded buys and sells, including closed positions. Dates are inclusive UTC dates; amounts use each row's currency. Follow next_offset.",
            [
                param("start_date", prop("string", format="date")),
                param("end_date", prop("string", format="date")),
                param("action", prop("string", enum=["buy", "sell"])),
            ],
        ),
    ]:
        paths["/api/v1/" + kind] = {
            "get": {
                "operationId": operation_id,
                "description": description,
                "x-openai-isConsequential": False,
                "parameters": common + extra,
                "responses": {
                    "200": response(
                        ref("HoldingsPage" if kind == "holdings" else "TransactionsPage")
                    ),
                    **errors,
                },
            }
        }
    paths["/api/v1/queries"] = {
        "post": {
            "operationId": "askPortfolioAgent",
            "x-openai-isConsequential": False,
            "description": "Start read-only analysis. Returns promptly; poll getPortfolioAnswer with task_id. Reuse context_id for follow-ups and request_id on retries. Cannot trade or change the portfolio.",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["question"],
                            "additionalProperties": False,
                            "properties": {
                                "question": prop("string", minLength=1, maxLength=8000),
                                "context_id": prop("string", maxLength=128, pattern=r"^[\w.-]+$"),
                                "request_id": prop("string", maxLength=128),
                            },
                        }
                    }
                },
            },
            "responses": {
                "202": response(ref("QueryTask"), "Accepted; poll for completion"),
                **errors,
            },
        }
    }
    paths["/api/v1/queries/{task_id}"] = {
        "get": {
            "operationId": "getPortfolioAnswer",
            "x-openai-isConsequential": False,
            "description": "Get analysis state and answer. If working, poll later; do not resubmit. Follow next_offset for long answers. Tasks expire after 24h, capacity eviction, or a server restart.",
            "parameters": [
                {"name": "task_id", "in": "path", "required": True, "schema": prop("string")},
                param("offset", prop("integer", minimum=0, maximum=10000000, default=0)),
            ],
            "responses": {"200": response(ref("QueryTask")), **errors},
        }
    }
    identity = {
        "holding_id": prop("integer"),
        "ticker": prop("string"),
        "name": prop(["string", "null"]),
        "market": prop("string"),
        "currency": prop(["string", "null"]),
        "shares": prop("number"),
    }
    schemas = {
        "Error": {"type": "object", "properties": {"error": prop("string")}},
        "Holding": {
            "type": "object",
            "properties": {
                **identity,
                "cost_basis": prop("number"),
                "position_type": prop("string"),
                "status": prop("string"),
                "updated_at": prop(["string", "null"]),
            },
        },
        "Transaction": {
            "type": "object",
            "properties": {
                **identity,
                "transaction_id": prop("integer"),
                "action": prop("string"),
                "price": prop("number"),
                "amount": prop("number"),
                "date": prop(["string", "null"]),
                "notes": prop("string"),
            },
        },
        "QueryTask": {
            "type": "object",
            "properties": {
                "task_id": prop("string"),
                "context_id": prop("string"),
                "status": prop("string", enum=["working", "completed", "failed"]),
                "answer": prop("string"),
                "answer_offset": prop("integer"),
                "next_offset": prop(["integer", "null"]),
                "error": prop(["string", "null"]),
                "retry_after_seconds": prop("integer"),
            },
        },
    }
    for name, item in (("HoldingsPage", "Holding"), ("TransactionsPage", "Transaction")):
        schemas[name] = {
            "type": "object",
            "properties": {
                "operation": prop("string"),
                "source": prop("string"),
                "read_only": prop("boolean"),
                "as_of": prop("string"),
                "timezone": prop("string"),
                "notes": prop("string"),
                "items": prop("array", items=ref(item)),
                "total": prop("integer"),
                "limit": prop("integer"),
                "offset": prop("integer"),
                "next_offset": prop(["integer", "null"]),
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Portfolio Agent",
            "version": "1.0.0",
            "description": "Read-only personal portfolio, trade ledger, and asynchronous analysis.",
        },
        "servers": [{"url": public_url.rstrip("/")}],
        "paths": paths,
        "security": [{"bearerAuth": []}],
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
            "schemas": schemas,
        },
    }
