"""A2A 0.3/1.0 JSON-RPC server and GPT Actions REST facade.

External agents discover ``/.well-known/agent-card.json``, then call
``message/send`` and ``tasks/get``. Model runs return a working task
immediately because a portfolio question can take minutes.
"""

import hmac
import json
import logging
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from config import config

logger = logging.getLogger(__name__)

Runner = Callable[[str, list, Optional[int]], Tuple[str, Optional[int]]]

_server: Optional[ThreadingHTTPServer] = None


def agent_card(public_url: str, v1: bool = False) -> dict:
    """Public discovery document. Message calls still require the bearer token."""
    card = {
        "protocolVersion": "0.3.0",
        "name": "Portfolio Agent",
        "description": "Read-only personal portfolio and trade ledger queries, plus asynchronous analysis with citations. No trading or ledger changes. Use contextId for follow-ups and tasks/get (GetTask in v1) to poll.",
        "url": public_url,
        "version": "1.1.0",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer"},
        },
        "security": [{"bearer": []}],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "portfolio-query",
                "name": "Portfolio query",
                "description": "Answer questions about holdings, prices, news, and recommendations.",
                "tags": ["portfolio", "markets"],
                "examples": ["我的组合现在怎么样？"],
            },
            {
                "id": "portfolio-ledger",
                "name": "Portfolio and transaction ledger",
                "description": 'Fast read-only query via a data part: {"operation":"holdings"|"transactions","filters":{ticker,market,status,start_date,end_date,action,limit,offset}}. Dates apply to transactions (inclusive UTC). status applies to holdings: open/closed/all. Default limit 25, max 100; follow next_offset. Costs are not live quotes.',
                "tags": ["holdings", "transactions", "read-only"],
                "examples": [
                    "我的持仓有哪些？",
                    "最近一个月买卖了什么？",
                    "查看 AAPL 的成交记录，包含已清仓仓位",
                ],
            },
        ],
    }
    if v1:
        for key in ("protocolVersion", "url", "preferredTransport", "security"):
            card.pop(key, None)
        card["supportedInterfaces"] = [
            {
                "url": public_url.rstrip("/") + "/a2a/v1",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ]
        card["securitySchemes"] = {"bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}
        card["securityRequirements"] = [{"schemes": {"bearer": {"list": []}}}]
    return card


class A2AApp:
    """In-memory task store and JSON-RPC handler, independent of the socket."""

    def __init__(
        self,
        token: str,
        public_url: str,
        runner: Optional[Runner] = None,
        *,
        actions_token: str = "",
        actions_url: str = "",
        reader=None,
    ):
        self.token = token
        self.public_url = public_url
        self.runner = runner or _default_runner
        self.actions_token = actions_token
        self.actions_url = actions_url or public_url
        if reader is None:
            from a2a.queries import read_query

            reader = read_query
        self.reader = reader
        self.tasks: Dict[str, dict] = {}
        self.contexts: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> Tuple[int, dict]:
        parsed = urlparse(path or "/")
        route = parsed.path or "/"
        v1 = route.startswith("/a2a/v1") or _header(headers, "A2A-Version") == "1.0"
        if method == "GET" and route in (
            "/.well-known/agent-card.json",
            "/a2a/v1/.well-known/agent-card.json",
        ):
            return 200, agent_card(self.public_url, v1=v1)
        if self.actions_token and (route.startswith("/api/v1/") or route == "/openapi.json"):
            from a2a.actions import handle_actions

            return handle_actions(self, method, route, parsed.query, headers, body)
        if method != "POST" or route not in ("/", "/a2a/v1", "/a2a/v1/"):
            return 404, {"error": "not found"}
        if not _authorized(headers, self.token):
            return 401, {"error": "unauthorized"}
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if not isinstance(payload, dict):
            return 400, _rpc_error(None, -32600, "Invalid request")
        rpc_id = payload.get("id")
        if payload.get("jsonrpc") != "2.0":
            return 400, _rpc_error(rpc_id, -32600, "Invalid request")
        rpc_method = payload.get("method")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return 200, _rpc_error(rpc_id, -32602, "Invalid params")
        if rpc_method == ("SendMessage" if v1 else "message/send"):
            result = self._message_send(rpc_id, params)
            if v1 and "result" in result:
                task_id = result["result"]["id"]
                with self._lock:
                    task = self.tasks.get(task_id)
                if task is None:
                    return 200, _rpc_error(rpc_id, -32001, "Task expired; retry the query")
                if not (params.get("configuration") or {}).get("returnImmediately", False):
                    task["done"].wait()
                with self._lock:
                    result["result"] = {"task": _task_payload(task, v1=True)}
            return 200, result
        if rpc_method == ("GetTask" if v1 else "tasks/get"):
            return 200, self._tasks_get(rpc_id, params, v1=v1)
        return 200, _rpc_error(rpc_id, -32601, "Method not found")

    def _message_send(self, rpc_id, params: dict, channel="a2a") -> dict:
        message = params.get("message") if isinstance(params.get("message"), dict) else params
        text = _message_text(message)
        configuration = params.get("configuration") or {}
        if not isinstance(configuration, dict):
            return _rpc_error(rpc_id, -32602, "Invalid configuration")
        parts = message.get("parts") or []
        if not isinstance(parts, list):
            return _rpc_error(rpc_id, -32602, "parts must be an array")
        data = [p["data"] for p in parts if isinstance(p, dict) and "data" in p]
        if len(data) > 1 or (data and not isinstance(data[0], dict)):
            return _rpc_error(rpc_id, -32602, "Use one data part with operation and filters")
        query = data[0] if data else None
        if query is not None and (
            set(query) - {"operation", "filters"}
            or not isinstance(query.get("operation"), str)
            or query.get("operation") not in {"holdings", "transactions"}
            or not isinstance(query.get("filters", {}), dict)
        ):
            return _rpc_error(rpc_id, -32602, "Invalid ledger operation or filters")
        if not text and query is None:
            return _rpc_error(rpc_id, -32602, "Message has no text")
        if len(text) > 8000:
            return _rpc_error(rpc_id, -32602, "Question exceeds 8000 characters")
        raw_context = message.get("contextId", params.get("contextId"))
        if raw_context is not None and not isinstance(raw_context, str):
            return _rpc_error(rpc_id, -32602, "Invalid contextId")
        context_id = message.get("contextId") or params.get("contextId") or uuid.uuid4().hex
        if not isinstance(context_id, str) or not re.fullmatch(r"[\w.-]{1,128}", context_id):
            return _rpc_error(rpc_id, -32602, "Invalid contextId")
        request_id = message.get("messageId")
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 128):
            return _rpc_error(rpc_id, -32602, "Invalid messageId")
        context_key = context_id if channel == "a2a" else f"{channel}:{context_id}"
        task_id = uuid.uuid4().hex
        with self._lock:
            self._prune()
            for existing in self.tasks.values():
                if (
                    request_id
                    and existing.get("request_id") == request_id
                    and existing["channel"] == channel
                ):
                    if (
                        existing["question"] != text
                        or existing.get("query") != query
                        or (raw_context and existing["contextId"] != raw_context)
                    ):
                        return _rpc_error(
                            rpc_id, -32602, "messageId already used for another request"
                        )
                    return {"jsonrpc": "2.0", "id": rpc_id, "result": _task_payload(existing)}
            if sum(t["state"] == "working" for t in self.tasks.values()) >= 4:
                return _rpc_error(rpc_id, -32000, "Agent busy; retry later")
            context = self.contexts.setdefault(context_key, {"session_id": None, "history": []})
            if context.get("active"):
                return _rpc_error(
                    rpc_id, -32000, "Context has a running query; poll it before following up"
                )
            context["active"] = task_id
            history = list(context.get("history") or [])
            session_id = context.get("session_id")
            self.tasks[task_id] = {
                "id": task_id,
                "contextId": context_id,
                "state": "working",
                "text": "",
                "error": "",
                "channel": channel,
                "context_key": context_key,
                "request_id": request_id,
                "question": text,
                "query": query,
                "created": time.monotonic(),
                "done": threading.Event(),
                "message_id": uuid.uuid4().hex,
                "artifact_id": uuid.uuid4().hex,
            }
            accepted = _task_payload(self.tasks[task_id])
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, context_key, text, history, session_id),
            daemon=True,
            name=f"a2a-{task_id[:8]}",
        )
        thread.start()
        return {"jsonrpc": "2.0", "id": rpc_id, "result": accepted}

    def _prune(self):
        """Bound task/context storage; terminal results expire after 24 hours."""
        now = time.monotonic()
        for ident, task in list(self.tasks.items()):
            if task["done"].is_set() and (now - task["created"] > 86400 or len(self.tasks) >= 256):
                self.tasks.pop(ident)
        used = {t["context_key"] for t in self.tasks.values()}
        for key in list(self.contexts):
            if key not in used:
                self.contexts.pop(key)

    def _run_task(self, task_id, context_id, question, history, session_id) -> None:
        try:
            query = self.tasks[task_id].get("query")
            data = None
            if query is not None:
                question = "Ledger query: " + json.dumps(query, ensure_ascii=False)
                data = self.reader(query["operation"], query.get("filters", {}))
                answer, new_session_id = json.dumps(data, ensure_ascii=False), session_id
            else:
                answer, new_session_id = self.runner(question, history, session_id)
            with self._lock:
                context = self.contexts.setdefault(context_id, {"session_id": None, "history": []})
                context["session_id"] = new_session_id or context.get("session_id")
                turns = list(history) + [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer or ""},
                ]
                context["history"] = _trim_pairs(turns)
                task = self.tasks[task_id]
                task["state"] = "completed"
                task["text"] = answer or ""
                if data is not None:
                    task["data"] = data
        except Exception as exc:
            logger.error("A2A task %s failed: %s", task_id, exc)
            with self._lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task["state"] = "failed"
                    task["error"] = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "Query failed; inspect server logs and retry."
                    )
        finally:
            with self._lock:
                self.contexts[context_id].pop("active", None)
                self.tasks[task_id]["done"].set()

    def _tasks_get(self, rpc_id, params: dict, *, v1=False, channel="a2a") -> dict:
        task_id = params.get("id") or params.get("taskId")
        if not isinstance(task_id, str):
            return _rpc_error(rpc_id, -32602, "Invalid task id")
        with self._lock:
            self._prune()
            task = self.tasks.get(task_id)
            if task is None or task["channel"] != channel:
                return _rpc_error(rpc_id, -32001, "Task not found")
            payload = _task_payload(task, v1=v1)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}


def make_server(app: A2AApp, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._respond()

        def do_POST(self):
            self._respond()

        def _respond(self):
            self.connection.settimeout(15)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 100_000 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("Invalid body size or transfer encoding")
                body = self.rfile.read(length) if length else b""
                status, payload = app.handle(self.command, self.path, self.headers, body)
            except (ValueError, TimeoutError):
                status, payload = 400, {"error": "Invalid request"}
                self.close_connection = True
            except Exception:
                logger.exception("External API request failed")
                status, payload = 500, {"error": "Internal server error"}
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            logger.info("A2A %s", fmt % args)

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def start_a2a_server() -> Optional[ThreadingHTTPServer]:
    """Start the A2A HTTP server when enabled. Raises if the token is missing."""
    global _server
    if not config.A2A_ENABLED and not config.ACTIONS_ENABLED:
        logger.info("A2A server disabled.")
        return None
    if config.A2A_ENABLED and not config.A2A_TOKEN:
        raise RuntimeError("A2A_ENABLED requires A2A_TOKEN")
    if config.ACTIONS_ENABLED and not config.ACTIONS_TOKEN:
        raise RuntimeError("ACTIONS_ENABLED requires ACTIONS_TOKEN")
    if _server is not None:
        return _server
    public_url = config.A2A_PUBLIC_URL.strip() or f"http://127.0.0.1:{config.A2A_PORT}/"
    app = A2AApp(
        token=config.A2A_TOKEN if config.A2A_ENABLED else "",
        public_url=public_url,
        actions_token=config.ACTIONS_TOKEN if config.ACTIONS_ENABLED else "",
        actions_url=config.ACTIONS_PUBLIC_URL,
    )
    server = make_server(app, config.A2A_HOST, config.A2A_PORT)
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="a2a",
    )
    try:
        thread.start()
    except Exception:
        # shutdown() would block forever if serve_forever() never started.
        server.server_close()
        raise
    _server = server
    logger.info("External API listening on %s:%s", config.A2A_HOST, config.A2A_PORT)
    return _server


def stop_a2a_server() -> None:
    """Stop the listener and release its port; safe to call repeatedly."""
    global _server
    if _server is None:
        return
    server, _server = _server, None
    server.shutdown()
    server.server_close()


def _default_runner(question: str, history: list, session_id: Optional[int]):
    from agent.core import run_ad_hoc_query_stream

    final = ""
    new_session_id = session_id
    for event in run_ad_hoc_query_stream(
        question,
        history=history,
        session_id=session_id,
        job_id="a2a",
        triggered_by="a2a",
        read_only=True,
    ):
        if event["type"] == "done":
            final = event.get("text") or final
            new_session_id = event.get("session_id") or new_session_id
        elif event["type"] == "error":
            raise RuntimeError(event.get("text") or "A2A agent failed")
    return final, new_session_id


def _task_payload(task: dict, v1=False) -> dict:
    state = task["state"]
    message = {
        "kind": "message",
        "role": "agent",
        "messageId": task["message_id"],
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"kind": "text", "text": task.get("text") or task.get("error") or ""}],
    }
    payload = {
        "id": task["id"],
        "contextId": task["contextId"],
        "kind": "task",
        "status": {"state": state},
    }
    if state == "completed":
        payload["status"]["message"] = message
        payload["artifacts"] = [
            {
                "artifactId": task["artifact_id"],
                "parts": (
                    [{"kind": "data", "data": task["data"]}]
                    if "data" in task
                    else [{"kind": "text", "text": task.get("text") or ""}]
                ),
            }
        ]
    elif state == "failed":
        payload["status"]["message"] = message
    if v1:
        payload.pop("kind")
        payload["status"]["state"] = "TASK_STATE_" + state.upper()
        message.pop("kind")
        message["role"] = "ROLE_AGENT"
        for part in message["parts"]:
            part.pop("kind", None)
        for artifact in payload.get("artifacts", []):
            for part in artifact["parts"]:
                part.pop("kind", None)
    return payload


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    if not isinstance(parts, list):
        return ""
    chunks = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if text:
                chunks.append(str(text))
    if chunks:
        return "".join(chunks).strip()
    text = message.get("text")
    return str(text).strip() if text else ""


def _authorized(headers, token: str) -> bool:
    if not token:
        return False
    raw = _header(headers, "Authorization")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not str(raw).lower().startswith("bearer "):
        return False
    presented = str(raw).split(" ", 1)[1].strip()
    return hmac.compare_digest(presented.encode(), token.encode())


def _header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), "")


def _trim_pairs(turns: list) -> list:
    from config import config as app_config

    keep = max(int(app_config.ASK_AGENT_HISTORY_TURNS), 0) * 2
    if keep and len(turns) > keep:
        return turns[-keep:]
    return turns if keep else []


def _rpc_error(rpc_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
