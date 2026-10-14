"""Bounded, restartable indexing. Network calls never hold a DB transaction."""
import hashlib
import logging
import re
import threading
from datetime import timedelta, timezone

from sqlalchemy import select, text, or_
from sqlalchemy.orm import Session

from config import config
from db.models import Base, MemoryDocument, MemoryChunk, MemoryCheckpoint, MemoryEmbedding
from memory.capture import SOURCE_TYPES, build_document, utcnow
from memory import backends

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_thread = None
_stop = threading.Event()


def initialize(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(tokens)"))


def tokens(content):
    """Preserve codes; CJK bigrams support Chinese without a large NLP dependency."""
    out = []
    for part in re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", content.lower()):
        if '\u3400' <= part[0] <= '\u9fff':
            out.extend(part[i:i+2] for i in range(max(1, len(part)-1)))
        else:
            out.append(part)
    return out


def chunks(body, size=1600):
    """Prefer paragraph boundaries and retain a small overlap for long paragraphs."""
    buffer = ""
    for paragraph in body.split("\n\n"):
        while len(paragraph) > size:
            if buffer:
                yield buffer
                buffer = ""
            yield paragraph[:size]
            paragraph = paragraph[size-120:]
        if buffer and len(buffer) + len(paragraph) + 2 > size:
            yield buffer
            buffer = ""
        buffer = (buffer + "\n\n" + paragraph).strip()
    if buffer:
        yield buffer


def backfill_batch(engine, limit=None):
    """Keyset checkpoints prevent rescanning all history on every startup."""
    limit = config.MEMORY_IMPORT_BATCH_SIZE if limit is None else max(1, min(200, int(limit)))
    count = 0
    with Session(engine) as db:
        db.execute(text("BEGIN IMMEDIATE"))
        for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__tablename__):
            model = mapper.class_
            source = SOURCE_TYPES.get(model.__tablename__)
            if not source:
                continue
            checkpoint = db.get(MemoryCheckpoint, source)
            if checkpoint is None:
                checkpoint = MemoryCheckpoint(source_type=source, last_id=0)
                db.add(checkpoint)
                db.flush()
            rows = db.scalars(select(model).where(model.id > checkpoint.last_id)
                              .order_by(model.id).limit(limit-count)).all()
            for obj in rows:
                exists = db.scalar(select(MemoryDocument.id).where(
                    MemoryDocument.source_type == source, MemoryDocument.source_id == obj.id).limit(1))
                if not exists:
                    doc = build_document(db.connection(), obj, "import", backfill=True)
                    if doc:
                        db.add(doc)
                checkpoint.last_id = obj.id
                count += 1
            if count >= limit:
                break
        db.commit()
    return count


def index_lexical_batch(engine, limit=None):
    limit = config.MEMORY_LEXICAL_BATCH_SIZE if limit is None else max(1, min(200, int(limit)))
    with Session(engine) as db:
        db.execute(text("BEGIN IMMEDIATE"))
        docs = db.scalars(select(MemoryDocument).where(MemoryDocument.indexed_at.is_(None))
                          .order_by(MemoryDocument.id).limit(limit)).all()
        for doc in docs:
            for ordinal, content in enumerate(chunks(doc.body)):
                chunk = MemoryChunk(document_id=doc.id, ordinal=ordinal, body=content)
                db.add(chunk)
                db.flush()
                db.execute(text("INSERT INTO memory_fts(rowid, tokens) VALUES (:id, :tokens)"),
                           {"id": chunk.id, "tokens": " ".join(tokens(doc.title + " " + content))})
            doc.indexed_at = utcnow()
        db.commit()
        return len(docs)


def _epoch(dt):
    return dt.replace(tzinfo=timezone.utc).timestamp()


def embed_cached(engine, texts):
    version = backends.profile()
    hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
    cached = {}
    with Session(engine) as db:
        for row in db.scalars(select(MemoryEmbedding).where(
            MemoryEmbedding.profile == version, MemoryEmbedding.content_hash.in_(hashes))):
            cached[row.content_hash] = row.vector
    missing = dict((h, t) for h, t in zip(hashes, texts) if h not in cached)
    if missing:
        vectors = backends.embed(list(missing.values()))
        from sqlalchemy.dialects.sqlite import insert
        with Session(engine) as db:
            for h, vector in zip(missing, vectors):
                db.execute(insert(MemoryEmbedding).values(profile=version, content_hash=h, vector=vector)
                           .on_conflict_do_nothing())
                cached[h] = vector
            db.commit()
    return [cached[h] for h in hashes]


def index_vector_batch(engine, limit=None):
    limit = config.MEMORY_VECTOR_DOCUMENT_BATCH_SIZE if limit is None else max(1, min(20, int(limit)))
    if not backends.configured():
        return 0
    version = backends.profile()
    with Session(engine) as db:
        ids = list(db.scalars(select(MemoryDocument.id).where(
            MemoryDocument.indexed_at.is_not(None),
            or_(MemoryDocument.vector_profile.is_(None), MemoryDocument.vector_profile != version),
            or_(MemoryDocument.retry_at.is_(None), MemoryDocument.retry_at <= utcnow()),
        ).order_by(MemoryDocument.id).limit(limit)))
    for ident in ids:
        try:
            client = backends.Qdrant()
            client.ensure()
            # Stream bounded batches even for very long reports.
            last_chunk = 0
            while True:
                with Session(engine) as db:
                    doc = db.get(MemoryDocument, ident)
                    batch = db.scalars(select(MemoryChunk).where(MemoryChunk.document_id == ident,
                        MemoryChunk.id > last_chunk).order_by(MemoryChunk.id)
                        .limit(config.MEMORY_BATCH_SIZE)).all()
                    payload = {"document_id": ident, "source_type": doc.source_type,
                               "instruments": doc.instruments, "occurred_at": _epoch(doc.occurred_at),
                               "known_at": _epoch(doc.known_at)}
                    rows = [(c.id, c.body) for c in batch]
                if not rows:
                    break
                vectors = embed_cached(engine, [r[1] for r in rows])
                client.upsert([{"id": row[0], "vector": vector, "payload": payload}
                               for row, vector in zip(rows, vectors)])
                last_chunk = rows[-1][0]
            with Session(engine) as db:
                doc = db.get(MemoryDocument, ident)
                doc.vector_profile, doc.error, doc.retry_at, doc.attempts = version, None, None, 0
                db.commit()
        except Exception as exc:
            with Session(engine) as db:
                doc = db.get(MemoryDocument, ident)
                doc.attempts += 1
                failure = str(exc) if isinstance(exc, backends.BackendError) else type(exc).__name__
                doc.error = failure
                doc.retry_at = utcnow() + timedelta(seconds=min(3600, 30 * 2**min(doc.attempts, 7)))
                db.commit()
            logger.warning("Memory vector indexing delayed for document %s (%s)", ident, failure)
    return len(ids)


def tick(engine):
    if not _lock.acquire(blocking=False):
        return
    try:
        backfill_batch(engine)
        index_lexical_batch(engine)
        index_vector_batch(engine)
    finally:
        _lock.release()


def start_worker(engine):
    global _thread
    if not config.MEMORY_ENABLED or (_thread and _thread.is_alive()):
        return
    initialize(engine)
    _stop.clear()
    def run():
        while not _stop.is_set():
            try:
                tick(engine)
            except Exception as exc:
                logger.warning("Memory worker will retry (%s)", type(exc).__name__)
            _stop.wait(config.MEMORY_INTERVAL_SECONDS)
    _thread = threading.Thread(target=run, name="memory-indexer", daemon=True)
    _thread.start()


def stop_worker():
    _stop.set()
