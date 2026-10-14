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

No local embedding or reranking model is loaded. The worker runs one thread, imports 50 source records and builds up to 50 document indexes per pass, then embeds up to 4 documents, sequentially, with at most 20 chunks per HTTP request. Default interval: 10 seconds after the pass finishes. Short documents do not fill a request; increasing the chunk batch alone does not accelerate full-text indexing. Long reports are streamed in bounded batches; unchanged chunks reuse persisted embeddings. Failures retry with exponential backoff capped at one hour.

1. Deploy the Python code using the normal app deployment. Startup creates the new tables/column and imports historical records incrementally. Existing business records are not rewritten by backfill.
2. Install Qdrant as a native systemd service (Ubuntu 24.04, no Docker required):

   ```sh
   sudo bash deploy/setup-qdrant.sh
   curl --fail http://127.0.0.1:6333/healthz
   sudo systemctl status portfolio-qdrant --no-pager
   ```

   Requires `curl`, `ca-certificates`, `tar`, `sha256sum` and running systemd. If missing, install with `sudo apt-get install curl ca-certificates tar coreutils`. The installer downloads the pinned official v1.18.0 Linux binary for x86_64/aarch64, verifies its SHA-256, and installs it under `/opt/portfolio-qdrant/v1.18.0`. It preserves customized configuration/service files and refuses to overwrite a different binary. Repeated runs do not restart an active service. `sudo env SKIP_START=1 bash deploy/setup-qdrant.sh` installs without starting it.

   Configuration: `/etc/portfolio-qdrant/config.yaml`. Persistent data and snapshots: `/var/lib/portfolio-qdrant` (owned by systemd's isolated dynamic service user; access backups as root). Logs: `sudo journalctl -u portfolio-qdrant -n 50 --no-pager`. The service starts at boot, binds only `127.0.0.1:6333`, disables gRPC, and sets `MemoryHigh=500M`, `MemoryMax=600M`, `CPUQuota=75%`. Limits are guardrails, not capacity guarantees; observe total host memory during imports and concurrent scheduled jobs. Vectors, HNSW and payloads use disk storage. Do not expose port 6333 in the cloud firewall.

   The installer does not alter the app, `.env`, or existing data. To apply a deliberate Qdrant config change, use `sudo systemctl restart portfolio-qdrant`; verify health afterward. To disable it, `sudo systemctl disable --now portfolio-qdrant` leaves its data intact. If Qdrant was already running in Docker, retain that deployment until its collection snapshots have been restored and verified in the native service; do not point an already-indexed app at an empty store. The old compose file remains an optional alternative, not a prerequisite.

3. Configure `.env` (independent of the DeepSeek chat API):

   ```dotenv
   MEMORY_VECTOR_ENABLED=true
   MEMORY_EMBEDDING_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
   MEMORY_EMBEDDING_API_KEY=your-key
   MEMORY_EMBEDDING_MODEL=qwen3.7-text-embedding-flash
   MEMORY_EMBEDDING_DIMENSIONS=1024
   MEMORY_QDRANT_URL=http://127.0.0.1:6333
   MEMORY_BATCH_SIZE=20
   MEMORY_IMPORT_BATCH_SIZE=50
   MEMORY_LEXICAL_BATCH_SIZE=50
   MEMORY_VECTOR_DOCUMENT_BATCH_SIZE=4
   MEMORY_INTERVAL_SECONDS=10
   ```

   The provider must support `POST <base>/embeddings` with `model`, `input`, `dimensions` and `encoding_format="float"` and return `data[{index, embedding}]`. For the selected Bailian model, use 1024 dimensions (also supports 768, 512, 256) and no more than 20 inputs per request; the default maximum batch is 20. Replace `<WorkspaceId>` with the real workspace ID and copy the matching endpoint from the console. The documented model region is Beijing; the server being in Virginia does not determine the API region. The key must match the workspace/region. `DASHSCOPE_API_KEY` is accepted if `MEMORY_EMBEDDING_API_KEY` is empty. For another provider that rejects the dimensions parameter, set `MEMORY_EMBEDDING_SEND_DIMENSIONS=false` and configure its actual output size. Enabling vectors sends indexed text and search queries to this configured provider. No provider or key is selected automatically.

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

Back up the SQLite database using SQLite's backup API (or while stopped) and the Qdrant data directory/snapshot. To rebuild all derived indexes, stop the worker, delete rows in `memory_chunks` and `memory_fts`, set `memory_documents.indexed_at`, `vector_profile`, `retry_at`, `error` to NULL and `attempts` to 0, and delete the corresponding Qdrant collection. Keep `memory_documents`, original business tables and optionally `memory_embeddings`; resume the worker. Never restore a mismatched Qdrant snapshot and assume it is authoritative: final evidence and time filters are always checked against SQLite.

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

升级后无需配置 API 即可使用全文记忆搜索，历史导入会在后台逐步完成。要启用语义搜索，运行上述原生安装脚本启动 Qdrant并填写独立的 Embedding 接口、模型、维度和密钥，再设置 `MEMORY_VECTOR_ENABLED=true` 并重启。2 GiB 服务器不加载本地模型；systemd 资源限额只是起点，仍需观察导入和盘后分析同时运行时的峰值。

记忆库保留建议、反馈理由、分析、交易、持仓和关注变更、纪律版本、对话、已存新闻和财报。引用 `M编号` 可以打开对应版本及关联记录。历史导入数据会标记“无法确认原始可获知时间”，严格复盘不会把它冒充当时已知的信息。

百炼配置默认模型为 `qwen3.7-text-embedding-flash`、1024 维，单次 Embedding 请求最多 20 个文本片段。请从百炼控制台复制对应业务空间的兼容接口地址，填写 `MEMORY_EMBEDDING_BASE_URL`；密钥填写 `MEMORY_EMBEDDING_API_KEY`（也兼容 `DASHSCOPE_API_KEY`）。正式启用还需 `MEMORY_VECTOR_ENABLED=true`。北京业务空间地址示例见上文；不要根据服务器所在地域猜测模型接口地址。

### 调整已有服务器的导入速度

已有 `.env` 中的值优先于新默认值，需要手动更新以下配置，然后重启 Portfolio Agent：

```dotenv
MEMORY_IMPORT_BATCH_SIZE=50
MEMORY_LEXICAL_BATCH_SIZE=50
MEMORY_VECTOR_DOCUMENT_BATCH_SIZE=4
MEMORY_BATCH_SIZE=20
MEMORY_INTERVAL_SECONDS=10
```

前三项分别是每轮导入原始记录数、建立全文索引的文档数、建立向量索引的文档数；`MEMORY_BATCH_SIZE` 是单次 Embedding 请求的片段数上限，不是文档数。前两项允许 1–200，向量文档数允许 1–20，Embedding 片段数允许 1–20，间隔至少 5 秒。索引仍为单线程串行，避免同时发起大量请求。每轮耗时另计，截图里的 883 篇全文积压在没有新增和耗时的理想情况下约需 18 轮，实际还受历史导入、长报告和向量请求影响，不能保证 3 分钟完成。

向量计数为 0 并不一定是 batch 小：检查 Qdrant 健康状态、百炼接口/密钥和 `python -m memory status` 中的失败数量。失败有退避等待，增大 batch 不会修复连接或认证问题；可以查看 `journalctl -u portfolio-agent` 的 `Memory vector indexing delayed` 记录。已生成的缓存向量和完成的全文索引会保留。

后续重试的错误会区分 `Embedding unavailable (...)` 和 `Qdrant unavailable (...)`，日志也会记录这一脱敏原因。前者需要检查服务器到百炼的网络和接口；后者检查本机 Qdrant 状态、重启次数及内存。已有 `Service unavailable (...)` 错误会在下一次重试时更新，不必清空索引。`vector_errors` 是当前带错误记录的文档数，不是累计失败次数；成功后会清除。退避最长一小时，重启应用不会重置已保存的重试时间。
