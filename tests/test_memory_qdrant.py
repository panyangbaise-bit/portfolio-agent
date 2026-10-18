"""Opt-in transport integration against an isolated real Qdrant server.

Run: MEMORY_TEST_QDRANT_URL=http://127.0.0.1:16333 pytest tests/test_memory_qdrant.py
Embeddings are served locally from a deterministic fixture, not an external API.
"""

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config import config
from db.models import Base, TradingDiscipline
from memory import backends, retrieval
from memory.indexer import index_lexical_batch, index_vector_batch, initialize


@pytest.mark.skipif(
    not os.environ.get("MEMORY_TEST_QDRANT_URL"), reason="Real Qdrant integration is opt-in"
)
def test_real_qdrant_and_embedding_http_roundtrip(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v1/embeddings"
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(payload)
            content = json.dumps(
                {
                    "data": [
                        {"index": i, "embedding": [1.0, 0.1, 0.2, 0.3]}
                        for i, _ in enumerate(payload["input"])
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(config, "MEMORY_VECTOR_ENABLED", True)
    monkeypatch.setattr(
        config, "MEMORY_EMBEDDING_BASE_URL", f"http://127.0.0.1:{http.server_port}/v1"
    )
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_API_KEY", "test-only")
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_MODEL", "fixture")
    monkeypatch.setattr(config, "MEMORY_EMBEDDING_DIMENSIONS", 4)
    monkeypatch.setattr(config, "MEMORY_QDRANT_URL", os.environ["MEMORY_TEST_QDRANT_URL"])
    monkeypatch.setattr(config, "MEMORY_COLLECTION", "portfolio_test_" + uuid.uuid4().hex)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    client = backends.Qdrant()
    try:
        Base.metadata.create_all(engine)
        initialize(engine)
        with Session(engine) as db:
            db.add(TradingDiscipline(id=1, content="不要追涨，每次开仓先设定止损"))
            db.commit()
        index_lexical_batch(engine)
        assert index_vector_batch(engine) == 1
        with Session(engine) as db:
            # The query has no lexical overlap; evidence must arrive via real Qdrant.
            result = retrieval.search(db, "protect savings", source_types=["discipline"])
            assert result["mode"] == "hybrid", result
            assert result["results"] and result["results"][0]["source_type"] == "discipline"
            assert (
                retrieval.search(db, "protect savings", source_types=["transaction"])["results"]
                == []
            )
            assert retrieval.search(db, "protect savings", as_of="2000-01-01Z")["results"] == []
        assert calls and all(c["model"] == "fixture" for c in calls)
    finally:
        try:
            client.call("DELETE")
        finally:
            http.shutdown()
            http.server_close()
            worker.join(timeout=2)
            engine.dispose()
