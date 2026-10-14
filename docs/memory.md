# Investment memory / 投资记忆

SQLite remains the authoritative store. The Memory page and the agent share hybrid retrieval, immutable evidence IDs (`M123`), source reading and paginated instrument timelines. Full-text search works without an embedding provider. Qdrant is optional and explicitly enabled.

## What is captured

- Recommendations and their status changes; accepts/dismissals and reasons.
- Analysis summaries and news snapshots, monthly/exit reviews, run outcomes.
- Holding and transaction changes, watchlist changes and trading discipline versions.
- New user messages at send time and assistant messages at turn completion, including A2A.
- Persisted news articles and financial reports.

Business writes and immutable snapshots commit in the same SQLite transaction. `memory_documents` also serves as the durable indexing outbox. Indexing never makes network requests inside a business transaction. Tool logs, including memory search results, are deliberately excluded from ingestion; they remain available in the operations session detail.

The UI's former holding delete action now archives the position. Its ledger is retained, but archived positions and their transactions are excluded from current portfolio return calculations, preserving the previous removal behavior. Watchlist removal also archives the row. Closing a position by selling it remains a normal, non-archived holding and keeps contributing to return calculations.

## Low-memory deployment

No local embedding or reranking model is loaded. The worker runs one thread, imports 25 source records and builds up to 8 document indexes per pass, then embeds at most one document in batches of 4 chunks. Default interval: 30 seconds. Long reports are streamed in bounded batches; unchanged chunks reuse persisted embeddings. Failures retry with exponential backoff capped at one hour.

1. Deploy the Python code using the normal app deployment. Startup creates the new tables/column and imports historical records incrementally. Existing business records are not rewritten by backfill.
2. Optionally start Qdrant:

   ```sh
   docker compose -f deploy/qdrant-compose.yml up -d
   ```

   The pinned Qdrant service binds only `127.0.0.1:6333`, with an initial 600 MiB container limit and 0.75 CPU limit. These are resource guardrails, not capacity guarantees. Collection vectors, HNSW and payloads use disk storage. Observe total host memory during imports and concurrent scheduled jobs. Storage lives in a named Docker volume; don't delete it during routine upgrades.

3. Configure `.env` (independent of the DeepSeek chat API):

   ```dotenv
   MEMORY_VECTOR_ENABLED=true
   MEMORY_EMBEDDING_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
   MEMORY_EMBEDDING_API_KEY=your-key
   MEMORY_EMBEDDING_MODEL=qwen3.7-text-embedding-flash
   MEMORY_EMBEDDING_DIMENSIONS=1024
   MEMORY_QDRANT_URL=http://127.0.0.1:6333
   MEMORY_BATCH_SIZE=4
   MEMORY_INTERVAL_SECONDS=30
   ```

   The provider must support `POST <base>/embeddings` with `model`, `input`, `dimensions` and `encoding_format="float"` and return `data[{index, embedding}]`. For the selected Bailian model, use 1024 dimensions (also supports 768, 512, 256) and no more than 20 inputs per request; the default batch remains 4. Replace `<WorkspaceId>` with the real workspace ID and copy the matching endpoint from the console. The documented model region is Beijing; the server being in Virginia does not determine the API region. The key must match the workspace/region. `DASHSCOPE_API_KEY` is accepted if `MEMORY_EMBEDDING_API_KEY` is empty. For another provider that rejects the dimensions parameter, set `MEMORY_EMBEDDING_SEND_DIMENSIONS=false` and configure its actual output size. Enabling vectors sends indexed text and search queries to this configured provider. No provider or key is selected automatically.

4. Restart the application. Check the Memory page's import/full-text/vector counts. Without configuration it uses full-text mode; outages show degraded mode rather than claiming that no history exists.

FTS5 must be available in SQLite (`SELECT sqlite_version(); CREATE VIRTUAL TABLE ... USING fts5(...)`). Ubuntu's normal Python SQLite build includes it. Chinese retrieval uses character bigrams plus intact Latin/code tokens, with exact market/code/name filters; it does not require a tokenizer model. Hybrid ranking uses reciprocal rank fusion. Search does not infer that similarly timed transactions executed a recommendation.

## Maintenance

From the project directory and its Python environment:

```sh
python -m memory status
python -m memory backfill --batches 100   # local import/full-text only; resumable
python -m memory index --batches 10       # also creates external embeddings
```

Keep only one vector indexing process active (normally the app worker). SQLite import/full-text batches serialize writes; vector upserts and cache writes are idempotent. The CLI should normally be used while the app worker is stopped (`MEMORY_ENABLED=false` disables that background worker, not auditing). A model, endpoint, dimensions or chunk-format change produces a new collection suffix and cache namespace. This prevents mixing incompatible vectors. Old collections remain available for rollback and must be removed manually once no longer needed.

Back up the SQLite database using SQLite's backup API (or while stopped) and the Qdrant volume/snapshot. To rebuild all derived indexes, stop the worker, delete rows in `memory_chunks` and `memory_fts`, set `memory_documents.indexed_at`, `vector_profile`, `retry_at`, `error` to NULL and `attempts` to 0, and delete the corresponding Qdrant collection. Keep `memory_documents`, original business tables and optionally `memory_embeddings`; resume the worker. Never restore a mismatched Qdrant snapshot and assume it is authoritative: final evidence and time filters are always checked against SQLite.

## Time, versions and limits

- `occurred_at` is business event time; `known_at` is when this snapshot became available to the system. `as_of` filters the latter, including linked evidence.
- Imported historical records conservatively use import time as `known_at` and are marked `imported`. Original overwritten/deleted history cannot be reconstructed. Consequently, strict historical `as_of` queries may exclude imported records; this is shown rather than inventing historical availability.
- Old concatenated conversations are imported as legacy session snapshots; they are not assigned invented per-message timestamps. New messages are timestamped separately.
- An evidence ID identifies an immutable version, not necessarily the present state. Read the latest portfolio tools for current positions and `read_memory("current_discipline")` for current rules.
- Search returns relevant snippets, not all records. Timeline uses stable recorded-ID pagination and includes revisions; counts of timeline rows are not counts of unique trades. Use structured ledger tools for exact totals and returns.
- Instrument tags use market + ticker. Known names/codes in reports are matched deterministically. Ambiguous markets stay `?:TICKER`, and implied entities may require semantic search without an instrument filter. There is no LLM entity extraction or inferred trade/recommendation linkage.
- Accepted recommendations are not evidence of executed trades. User text, generated analysis and external sources keep separate authorship.
- Ordinary removal is archival, not privacy erasure. No permanent-erasure UI is introduced in this version.
- Single-portfolio app, sharing its existing authentication boundary; multi-user isolation is not implemented.

## Validation

`tests/test_memory.py` covers transaction rollback, version preservation, archive semantics, Chinese/code filtering, recommendation/feedback links, historical cutoffs (including stale vector candidates), restartable backfill, separate conversation turns, pagination, vector retry/cache behavior, UI interaction and explicit failure reporting. Optional real-Qdrant integration uses synthetic evidence and a local fake embedding HTTP endpoint; it verifies transport/filtering, not a production embedding model's semantic quality.

Bailian references: [model capabilities and dimensions](https://help.aliyun.com/zh/model-studio/qwen3-7-text-embedding-flash), [embedding HTTP API and workspace endpoint](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api). No live Bailian request has been made without workspace credentials.

API references: [Qdrant collections](https://api.qdrant.tech/api-reference/collections/create-collection), [query points](https://api.qdrant.tech/api-reference/search/query-points), [SQLite FTS5](https://www.sqlite.org/fts5.html).

## 中文部署摘要

升级后无需配置 API 即可使用全文记忆搜索，历史导入会在后台逐步完成。要启用语义搜索，启动上述 Qdrant 容器并填写独立的 Embedding 接口、模型、维度和密钥，再设置 `MEMORY_VECTOR_ENABLED=true` 并重启。2 GiB 服务器不加载本地模型；容器资源限额只是起点，仍需观察导入和盘后分析同时运行时的峰值。

记忆库保留建议、反馈理由、分析、交易、持仓和关注变更、纪律版本、对话、已存新闻和财报。引用 `M编号` 可以打开对应版本及关联记录。历史导入数据会标记“无法确认原始可获知时间”，严格复盘不会把它冒充当时已知的信息。

百炼配置默认模型为 `qwen3.7-text-embedding-flash`、1024 维，单批 4 条。请从百炼控制台复制对应业务空间的兼容接口地址，填写 `MEMORY_EMBEDDING_BASE_URL`；密钥填写 `MEMORY_EMBEDDING_API_KEY`（也兼容 `DASHSCOPE_API_KEY`）。正式启用还需 `MEMORY_VECTOR_ENABLED=true`。北京业务空间地址示例见上文；不要根据服务器所在地域猜测模型接口地址。
