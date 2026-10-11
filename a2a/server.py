"""Small A2A JSON-RPC server (Python 3.9, standard library only).

External agents discover ``/.well-known/agent-card.json``, then call
``message/send`` and ``tasks/get``. Model runs return a working task
immediately because a portfolio question can take minutes.
"""

import hmac
import json
import logging
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from config import config

logger = logging.getLogger(__name__)

Runner = Callable[[str, list, Optional[int]], Tuple[str, Optional[int]]]

_server: Optional[ThreadingHTTPServer] = None


def agent_card(public_url: str) -> dict:
    """Public discovery document. Message calls still require the bearer token."""
    return {
        "protocolVersion": "0.3.0",
        "name": "Portfolio Agent",
        "description": "个人投资组合助手，回答持仓、行情、新闻和建议相关问题。",
        "url": public_url,
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer"},
        },
        "security": [{"bearer": []}],
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "portfolio-query",
                "name": "Portfolio query",
                "description": "Answer questions about holdings, prices, news, and recommendations.",
                "tags": ["portfolio", "markets"],
                "examples": ["我的组合现在怎么样？"],
            }
        ],
    }


class A2AApp:
    """In-memory task store and JSON-RPC handler, independent of the socket."""

    def __init__(self, token: str, public_url: str, runner: Optional[Runner] = None):
        self.token = token
        self.public_url = public_url
        self.runner = runner or _default_runner
        self.tasks: Dict[str, dict] = {}
        self.contexts: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> Tuple[int, dict]:
        parsed = urlparse(path or "/")
        route = parsed.path or "/"
        if method == "GET" and route == "/.well-known/agent-card.json":
            return 200, agent_card(self.public_url)
        if method != "POST" or route not in ("/", ""):
            return 404, {"error": "not found"}
        if not _authorized(headers, self.token):
            return 401, {"error": "unauthorized"}
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if not isinstance(payload, dict):
            return 400, _rpc_error(None, -32600, "Invalid request")
        rpc_id = payload.get("id")
        rpc_method = payload.get("method")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return 200, _rpc_error(rpc_id, -32602, "Invalid params")
        if rpc_method == "message/send":
            return 200, self._message_send(rpc_id, params)
        if rpc_method == "tasks/get":
            return 200, self._tasks_get(rpc_id, params)
        return 200, _rpc_error(rpc_id, -32601, "Method not found")

    def _message_send(self, rpc_id, params: dict) -> dict:
        message = params.get("message") if isinstance(params.get("message"), dict) else params
        text = _message_text(message)
        if not text:
            return _rpc_error(rpc_id, -32602, "Message has no text")
        context_id = (
            message.get("contextId")
            or params.get("contextId")
            or uuid.uuid4().hex
        )
        task_id = uuid.uuid4().hex
        with self._lock:
            context = self.contexts.setdefault(
                context_id, {"session_id": None, "history": []}
            )
            history = list(context.get("history") or [])
            session_id = context.get("session_id")
            self.tasks[task_id] = {
                "id": task_id,
                "contextId": context_id,
                "state": "working",
                "text": "",
                "error": "",
            }
            accepted = _task_payload(self.tasks[task_id])
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, context_id, text, history, session_id),
            daemon=True,
            name=f"a2a-{task_id[:8]}",
        )
        thread.start()
        return {"jsonrpc": "2.0", "id": rpc_id, "result": accepted}

    def _run_task(self, task_id, context_id, question, history, session_id) -> None:
        try:
            answer, new_session_id = self.runner(question, history, session_id)
            with self._lock:
                context = self.contexts.setdefault(
                    context_id, {"session_id": None, "history": []}
                )
                context["session_id"] = new_session_id or context.get("session_id")
                turns = list(history) + [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer or ""},
                ]
                context["history"] = _trim_pairs(turns)
                task = self.tasks[task_id]
                task["state"] = "completed"
                task["text"] = answer or ""
        except Exception as exc:
            logger.error("A2A task %s failed: %s", task_id, exc)
            with self._lock:
                task = self.tasks.get(task_id)
                if task is not None:
                    task["state"] = "failed"
                    task["error"] = str(exc)

    def _tasks_get(self, rpc_id, params: dict) -> dict:
        task_id = params.get("id") or params.get("taskId")
        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return _rpc_error(rpc_id, -32001, "Task not found")
            payload = _task_payload(task)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}


def make_server(app: A2AApp, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._respond()

        def do_POST(self):
            self._respond()

        def _respond(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            status, payload = app.handle(self.command, self.path, self.headers, body)
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            logger.info("A2A %s", fmt % args)

    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def start_a2a_server() -> Optional[ThreadingHTTPServer]:
    """Start the A2A HTTP server when enabled. Raises if the token is missing."""
    global _server
    if not config.A2A_ENABLED:
        logger.info("A2A server disabled.")
        return None
    if not config.A2A_TOKEN:
        raise RuntimeError("A2A_ENABLED requires A2A_TOKEN")
    if _server is not None:
        return _server
    public_url = config.A2A_PUBLIC_URL.strip() or f"http://127.0.0.1:{config.A2A_PORT}/"
    app = A2AApp(token=config.A2A_TOKEN, public_url=public_url)
    _server = make_server(app, "0.0.0.0", config.A2A_PORT)
    thread = threading.Thread(
        target=_server.serve_forever,
        daemon=True,
        name="a2a",
    )
    thread.start()
    logger.info("A2A server listening on 0.0.0.0:%s", config.A2A_PORT)
    return _server


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
    ):
        if event["type"] == "done":
            final = event.get("text") or final
            new_session_id = event.get("session_id") or new_session_id
        elif event["type"] == "error":
            raise RuntimeError(event.get("text") or "A2A agent failed")
    return final, new_session_id


def _task_payload(task: dict) -> dict:
    state = task["state"]
    message = {
        "role": "agent",
        "messageId": uuid.uuid4().hex,
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
        payload["artifacts"] = [{
            "artifactId": uuid.uuid4().hex,
            "parts": [{"kind": "text", "text": task.get("text") or ""}],
        }]
    elif state == "failed":
        payload["status"]["message"] = message
    return payload


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
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
    if hasattr(headers, "get"):
        raw = headers.get("Authorization") or ""
    else:
        raw = ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not str(raw).lower().startswith("bearer "):
        return False
    presented = str(raw).split(" ", 1)[1].strip()
    return hmac.compare_digest(presented, token)


def _trim_pairs(turns: list) -> list:
    from config import config as app_config

    keep = max(int(app_config.ASK_AGENT_HISTORY_TURNS), 0) * 2
    if keep and len(turns) > keep:
        return turns[-keep:]
    return turns


def _rpc_error(rpc_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }
