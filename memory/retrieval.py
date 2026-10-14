"""Hybrid evidence retrieval with SQL-enforced filters and bounded output."""
from datetime import datetime, timezone
from collections import defaultdict

from sqlalchemy import select, text, func

from config import config
from db.models import Base, MemoryCheckpoint, MemoryDocument, MemoryChunk, Holding, WatchlistItem
from memory import backends
from memory.indexer import tokens
from memory.capture import SOURCE_TYPES


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo(config.APP_TIMEZONE))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        raise ValueError("Use an ISO date/time, optionally with timezone") from None


def resolve_instruments(db, instruments):
    result = set()
    for term in instruments or []:
        term = term.strip()
        if not term:
            continue
        if ":" in term:
            result.add(term.upper())
            continue
        found = set()
        for model in (Holding, WatchlistItem):
            rows = db.execute(select(model.market, model.ticker).where(
                (func.upper(model.ticker) == term.upper()) | (model.name == term))).all()
            found.update(f"{m}:{t.upper()}" for m, t in rows)
        # Also resolve aliases from immutable snapshots after a source was deleted.
        rows = db.execute(text("""SELECT DISTINCT j.value FROM memory_documents d,
            json_each(d.instruments) j WHERE
            upper(json_extract(d.snapshot, '$.instrument_ticker')) = :term
            OR json_extract(d.snapshot, '$.instrument_name') = :name"""),
            {"term": term.upper(), "name": term}).all()
        found.update(r[0] for r in rows)
        result.update(found or {"?:" + term.upper()})
    return sorted(result)


def filters(db, instruments=None, source_types=None, start_at=None, end_at=None, as_of=None):
    if source_types and any(s not in SOURCE_TYPES.values() for s in source_types):
        raise ValueError("Unknown source type")
    start, end, known = map(parse_time, (start_at, end_at, as_of))
    if start and end and start > end:
        raise ValueError("start_at must not be after end_at")
    resolved = resolve_instruments(db, instruments)
    clauses, params, conditions = [], {}, []
    if instruments and not resolved:
        clauses.append("0 = 1")
    if resolved:
        placeholders = []
        for i, ident in enumerate(resolved):
            params[f"instrument{i}"] = ident
            placeholders.append(f":instrument{i}")
        clauses.append("EXISTS (SELECT 1 FROM json_each(d.instruments) j WHERE j.value IN (" + ",".join(placeholders) + "))")
        conditions.append({"key": "instruments", "match": {"any": resolved}})
    if source_types:
        placeholders = []
        for i, source in enumerate(source_types):
            params[f"source{i}"] = source
            placeholders.append(f":source{i}")
        clauses.append("d.source_type IN (" + ",".join(placeholders) + ")")
        conditions.append({"key": "source_type", "match": {"any": source_types}})
    for key, dt, operator, qop in (("start", start, ">=", "gte"), ("end", end, "<=", "lte"), ("known", known, "<=", "lte")):
        if dt:
            column = "known_at" if key == "known" else "occurred_at"
            params[key] = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
            clauses.append(f"d.{column} {operator} :{key}")
            conditions.append({"key": column, "range": {qop: dt.replace(tzinfo=timezone.utc).timestamp()}})
    return " AND ".join(clauses) or "1 = 1", params, conditions


def evidence(doc, excerpt=None):
    data = doc.snapshot
    preview = next((str(data.get(k)) for k in ("notes", "reasoning", "content", "summary", "watch_reason", "details", "headline") if data.get(k)), "")
    if not preview:
        preview = " · ".join(f"{k}: {data[k]}" for k in ("shares", "price", "cost_basis", "status") if data.get(k) is not None)
    return {"evidence_id": f"M{doc.id}", "source_type": doc.source_type,
            "source_id": doc.source_id, "version": doc.id, "title": doc.title,
            "preview": preview[:600], "action": data.get("action"), "state": data.get("status"),
            "operation": doc.operation, "actor": doc.actor, "instruments": doc.instruments,
            "occurred_at": doc.occurred_at.isoformat() + "Z",
            "known_at": doc.known_at.isoformat() + "Z", "time_quality": doc.time_quality,
            "excerpt": excerpt if excerpt is not None else doc.body[:600],
            "url": f"?memory=M{doc.id}", "relations": doc.relations}


def status(db):
    total, indexed = db.execute(select(func.count(MemoryDocument.id),
                                      func.count(MemoryDocument.indexed_at))).one()
    vectors = db.scalar(select(func.count()).select_from(MemoryDocument).where(
        MemoryDocument.vector_profile == backends.profile()))
    failures = db.scalar(select(func.count()).select_from(MemoryDocument).where(MemoryDocument.error.is_not(None)))
    complete = True
    for mapper in Base.registry.mappers:
        model = mapper.class_
        source = SOURCE_TYPES.get(model.__tablename__)
        if source:
            highest = db.scalar(select(func.max(model.id))) or 0
            checkpoint = db.get(MemoryCheckpoint, source)
            if highest > (checkpoint.last_id if checkpoint else 0):
                complete = False
    return {"backfill_complete": complete, "total_documents": total, "indexed_documents": indexed,
            "pending_documents": total-indexed, "vector_documents": vectors,
            "vector_configured": backends.configured(), "vector_errors": failures,
            "last_indexed_at": str(db.scalar(select(func.max(MemoryDocument.indexed_at))) or "")}


def search(db, query, instruments=None, source_types=None, start_at=None, end_at=None, as_of=None, limit=10):
    if not query or not query.strip():
        raise ValueError("A search query is required")
    if len(query) > 2000:
        raise ValueError("Search query must be at most 2000 characters")
    limit = max(1, min(int(limit), 20))
    where, params, qfilter = filters(db, instruments, source_types, start_at, end_at, as_of)
    words = list(dict.fromkeys(tokens(query)))[:48]
    lexical = []
    if words:
        params["query"] = " OR ".join('"' + w + '"' for w in words)
        lexical = [r[0] for r in db.execute(text(f"""SELECT c.id FROM memory_fts
            JOIN memory_chunks c ON c.id = memory_fts.rowid
            JOIN memory_documents d ON d.id = c.document_id
            WHERE memory_fts MATCH :query AND {where}
            ORDER BY bm25(memory_fts), c.id DESC LIMIT 80"""), params)]
    vector_ids, warning = [], None
    mode = "lexical"
    if backends.configured():
        # Release the read transaction before HTTP calls (important with SQLite).
        db.rollback()
        try:
            vector_ids = backends.Qdrant().search(backends.embed([query])[0], qfilter, 80)
            mode = "hybrid"
        except backends.BackendError as exc:
            warning = str(exc)
            mode = "lexical_fallback"
    elif config.MEMORY_VECTOR_ENABLED:
        warning = "Embedding configuration is incomplete"
        mode = "lexical_fallback"
    scores = defaultdict(float)
    for ranking in (lexical, vector_ids):
        for rank, ident in enumerate(ranking, 1):
            scores[ident] += 1 / (60 + rank)
    results, seen_sources, seen_content = [], set(), set()
    if scores:
        placeholders = ",".join(f":candidate{i}" for i in range(len(scores)))
        params.update({f"candidate{i}": ident for i, ident in enumerate(scores)})
        # Never trust stale/vector payloads as authorization for time/source filters.
        allowed = set(db.scalars(text(f"""SELECT c.id FROM memory_chunks c JOIN memory_documents d
            ON d.id = c.document_id WHERE c.id IN ({placeholders}) AND {where}"""), params))
        for ident in sorted(scores, key=lambda x: (-scores[x], -x)):
            if ident not in allowed:
                continue
            chunk = db.get(MemoryChunk, ident)
            doc = db.get(MemoryDocument, chunk.document_id)
            source = (doc.source_type, doc.source_id)
            if source in seen_sources or doc.content_hash in seen_content:
                continue
            seen_sources.add(source)
            seen_content.add(doc.content_hash)
            item = evidence(doc, chunk.body[:1800])
            item["chunk_id"] = ident
            results.append(item)
            if len(results) == limit:
                break
    return {"status": "degraded" if warning else "ok", "mode": mode, "warning": warning,
            "results": results, "coverage": status(db),
            "note": "Ranked evidence, not an exhaustive list. Use timeline/SQL for counts. Imported records have conservative known_at."}


def read(db, evidence_id, as_of=None, offset=0, include_relations=True):
    try:
        ident = int(str(evidence_id).removeprefix("M"))
    except ValueError:
        raise ValueError("Use an evidence ID such as M123") from None
    cutoff = parse_time(as_of)
    doc = db.get(MemoryDocument, ident)
    if not doc or (cutoff and doc.known_at > cutoff):
        return {"status": "not_found"}
    offset = max(0, int(offset))
    result = evidence(doc, doc.body[offset:offset+12000])
    result["status"] = "ok"
    result["next_offset"] = offset+12000 if len(doc.body) > offset+12000 else None
    result["related_evidence"] = []
    if include_relations:
        for link in doc.relations:
            query = select(MemoryDocument).where(MemoryDocument.source_type == link["source_type"],
                                                MemoryDocument.source_id == link["source_id"])
            if cutoff:
                query = query.where(MemoryDocument.known_at <= cutoff)
            related = db.scalar(query.order_by(MemoryDocument.id.desc()).limit(1))
            if related:
                result["related_evidence"].append(evidence(related))
        # Incoming relationships expose user feedback for a recommendation and
        # recommendations for a report. Do not infer execution from acceptance.
        rows = db.scalars(text("""SELECT DISTINCT d.id FROM memory_documents d,
            json_each(d.relations) r WHERE json_extract(r.value, '$.source_type') = :kind
            AND json_extract(r.value, '$.source_id') = :sid
            AND (:cutoff IS NULL OR d.known_at <= :cutoff)
            ORDER BY d.id DESC LIMIT 21"""), {"kind": doc.source_type, "sid": doc.source_id,
                "cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S.%f") if cutoff else None}).all()
        result["relations_truncated"] = len(rows) > 20
        for ident in rows[:20]:
            result["related_evidence"].append(evidence(db.get(MemoryDocument, ident)))
        # A reciprocal link can appear in both directions; show each version once.
        result["related_evidence"] = list({item["evidence_id"]: item
            for item in result["related_evidence"] if item["evidence_id"] != result["evidence_id"]}.values())
    return result


def timeline(db, instrument=None, start_at=None, end_at=None, as_of=None, cursor=0, limit=30, source_types=None):
    where, params, _ = filters(db, [instrument] if instrument else None, source_types, start_at, end_at, as_of)
    limit = max(1, min(int(limit), 100))
    # Keyset on immutable record ID: stable through concurrent writes and backdated trades.
    params.update(cursor=max(0, int(cursor)), limit=limit+1)
    ids = db.scalars(text(f"SELECT d.id FROM memory_documents d WHERE {where} AND d.id > :cursor ORDER BY d.id LIMIT :limit"), params).all()
    results = [evidence(db.get(MemoryDocument, ident)) for ident in ids[:limit]]
    return {"status": "ok", "results": results, "next_cursor": ids[limit-1] if len(ids) > limit else None,
            "order": "recorded sequence; occurred_at is the business event time",
            "note": "Includes revisions, not just unique transactions. Import time is not original availability."}
