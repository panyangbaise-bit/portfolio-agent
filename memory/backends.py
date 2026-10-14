"""Small HTTP clients; no local inference runtime or Qdrant SDK required."""
import hashlib
import json
import math
from urllib.parse import quote

import requests

from config import config


class BackendError(RuntimeError):
    pass


def profile():
    raw = [config.MEMORY_EMBEDDING_BASE_URL, config.MEMORY_EMBEDDING_MODEL,
           config.MEMORY_EMBEDDING_DIMENSIONS, config.MEMORY_EMBEDDING_SEND_DIMENSIONS, "chunks-v1"]
    return hashlib.sha256(json.dumps(raw).encode()).hexdigest()[:16]


def configured():
    return bool(config.MEMORY_VECTOR_ENABLED and config.MEMORY_EMBEDDING_BASE_URL
                and config.MEMORY_EMBEDDING_MODEL and config.MEMORY_EMBEDDING_API_KEY)


def request(method, url, *, service="Service", **kwargs):
    try:
        response = requests.request(method, url, timeout=(3, 15), **kwargs)
    except requests.RequestException as exc:
        # Provider URLs, authorization headers and response bodies may contain secrets.
        raise BackendError(f"{service} unavailable ({type(exc).__name__})") from None
    if response.status_code >= 400:
        raise BackendError(f"{service} returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise BackendError(f"{service} returned invalid JSON") from None


def embed(texts):
    if not configured():
        raise BackendError("Embedding is not configured")
    if config.MEMORY_EMBEDDING_MODEL == "qwen3.7-text-embedding-flash":
        if config.MEMORY_EMBEDDING_DIMENSIONS not in (256, 512, 768, 1024):
            raise BackendError("qwen3.7-text-embedding-flash requires 256, 512, 768 or 1024 dimensions")
        if len(texts) > 20:
            raise BackendError("qwen3.7-text-embedding-flash supports at most 20 inputs per request")
    payload = {"model": config.MEMORY_EMBEDDING_MODEL, "input": texts, "encoding_format": "float"}
    if config.MEMORY_EMBEDDING_SEND_DIMENSIONS:
        payload["dimensions"] = config.MEMORY_EMBEDDING_DIMENSIONS
    data = request("POST", config.MEMORY_EMBEDDING_BASE_URL + "/embeddings",
                   headers={"Authorization": "Bearer " + config.MEMORY_EMBEDDING_API_KEY}, json=payload, service="Embedding")
    try:
        rows = sorted(data["data"], key=lambda x: x["index"])
        if [r["index"] for r in rows] != list(range(len(texts))):
            raise ValueError()
        vectors = [r["embedding"] for r in rows]
        for vector in vectors:
            if len(vector) != config.MEMORY_EMBEDDING_DIMENSIONS or not all(
                isinstance(x, (int, float)) and math.isfinite(x) for x in vector
            ) or not any(vector):
                raise ValueError()
        return vectors
    except (TypeError, KeyError, ValueError):
        raise BackendError("Embedding response has invalid count, dimensions or values") from None


class Qdrant:
    def __init__(self):
        # A changed embedding model or dimension always gets an isolated collection.
        self.url = config.MEMORY_QDRANT_URL + "/collections/" + quote(
            config.MEMORY_COLLECTION + "_" + profile(), safe="")
        self.headers = {"api-key": config.MEMORY_QDRANT_API_KEY} if config.MEMORY_QDRANT_API_KEY else {}

    def call(self, method, path="", **kwargs):
        return request(method, self.url + path, headers=self.headers, service="Qdrant", **kwargs)

    def ensure(self):
        exists = self.call("GET", "/exists").get("result", {}).get("exists")
        if not exists:
            self.call("PUT", json={
                "vectors": {"size": config.MEMORY_EMBEDDING_DIMENSIONS,
                            "distance": "Cosine", "on_disk": True},
                "on_disk_payload": True, "shard_number": 1,
                "hnsw_config": {"on_disk": True, "max_indexing_threads": 1},
                "optimizers_config": {"max_optimization_threads": 1},
            })

    def upsert(self, points):
        self.call("PUT", "/points?wait=true", json={"points": points})

    def search(self, vector, conditions, limit=60):
        result = self.call("POST", "/points/query", json={
            "query": vector, "filter": {"must": conditions}, "limit": limit,
            "with_payload": False, "with_vector": False,
        })
        try:
            return [int(p["id"]) for p in result["result"]["points"]]
        except (TypeError, KeyError, ValueError):
            raise BackendError("Vector service returned invalid results") from None
