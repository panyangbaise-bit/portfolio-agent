# Trace-driven research improvements

Implemented from the three 2026-10-19 public trace reviews. No database migration
is required. Existing tool names and persisted raw evidence remain available.

## 1. Data correctness

- CN symbols have explicit namespaces: `index:000688`, `stock:000001`,
  `fund:000001`, `etf:510050`. Ambiguous bare codes such as `000688` now return an
  actionable error. They never fall through to an unrelated fund on failure.
  Existing ambiguous symbols need qualification when querying; unambiguous
  existing examples such as `020357`, `011613`, `600519` remain supported.
- Index and exchange-fund candles use their respective providers. Returned
  candles identify the resolved code and asset type.
- NAV series cannot supply volume or intraday-pattern evidence. Model views
  explicitly mark those capabilities unavailable. Conditions must be reported
  as unknown, rather than false, when the required data is missing.
- News provider failures remain errors; partial headline results retain a
  coverage warning. Ledger queries reject unsupported comma-separated tickers.
- US quote retrieval time is separate from observation time. Unknown observation
  time remains null. Financial fields declare their individual periods/units;
  a fiscal-year-end date does not turn TTM or forward metrics into annual results.

## 2. Search and evidence coverage

- Web search is available directly for company disclosures, independent sources,
  conflicting reports and time-sensitive facts. The old WSCN-only restriction
  was removed from both the system prompt and tool description.
- Before the next model call, the graph detects empty/error ticker searches,
  missing summaries/dates, and holding-specific gaps identified during polling.
  It issues up to two automatic `web_search` calls per user turn, prioritizing
  known securities and merging Chinese/English aliases. Attempts, including
  failures, consume this automatic budget. The model may still make further
  targeted searches when material claims need verification.
- Automatic queries exclude WSCN to seek an independent source. Search snippets
  are discovery evidence, not proof that the underlying full disclosure was read.
  Provider configuration/authentication failures remain visible to the model.
- Polling maps common ticker aliases to Chinese names, preserves coverage gaps,
  and prioritizes holding news over generic headlines before applying the
  20-item context cap. WSCN keyword URL variants share a citation identity.
- The prompt separates persistent user constraints, past agent opinions,
  external facts and actual saved recommendation IDs. Historical claims about
  earnings dates, litigation and forecasts require current verification.

## 3. Context, execution and notifications

- Only model-facing tool messages are compacted. Full graph state and tool logs
  retain source evidence for audit and chart generation. Kline views contain
  recent 20 bars, moving averages, window extrema, latest data and limitations.
  `get_kline(detail="full")` is an additive escape hatch for older specific dates.
- General recommendation-history views retain the latest two entries per
  ticker, every pending recommendation and all user feedback reasons. A query
  specifying a ticker retains full returned details. This view is not a complete
  ledger and must not be used to count historical actions.
- Successful market tool results can be reused in the same turn (quotes: 60s;
  candles/financials: 300s), including a single ticker from a completed batch.
  Failures are not cached. Reuse preserves the original execution time.
- Entirely read-only batches run with at most four workers, preserving response
  order, provider error handling and per-call timeouts. Batches containing writes
  remain sequential. The existing repeated-call guard still applies.
- Horizontal chart lines may omit `end_price`; it defaults to `start_price`.
  Trend lines still require both endpoints.
- News tasks record an explicit `set_news_notification` decision. A nonempty
  report alone does not trigger a push. Positive decisions must cite observed
  source IDs. Missing decisions and failed delivery produce failed job records.
- Processed article fingerprints are retained in the existing session JSON
  snapshot for 24 hours. Changed holdings or changed article content invalidate
  deduplication; unresolved coverage gaps always remain eligible for retry.
  Events become processed only after successful delivery or an explicit quiet
  decision. Failed sends remain eligible for the next scheduled run.

## Validation

Run `make check` for Ruff, formatting and the isolated pytest suite. Added
regressions cover index/fund ambiguity, provider failure versus no results,
unsupported ledger batches, automatic web-search escalation, context evidence
preservation, quote-cache freshness, concurrent reads, sequential writes and
notification/deduplication behavior. Tests do not call live financial/search APIs
or send Telegram messages.

Offline projection of the original trace tool messages (characters, not tokens):

| Trace (Asia/Shanghai) | Original tool text | Model-facing tool text | Reduction |
| --- | ---: | ---: | ---: |
| 2026-10-19 12:00 | 97,296 | 47,946 | 50.7% |
| 2026-10-19 15:30 | 53,793 | 21,698 | 59.7% |
| 2026-10-19 20:00 | 73,759 | 29,710 | 59.7% |

These measurements only apply the context projection to saved tool messages;
they are not new model runs and do not measure search quality, billed tokens,
latency or notification volume after deployment. Production checks should inspect
independent source coverage, unsupported claims, actual search errors, total
input tokens and explicit notification decisions on new traces.
