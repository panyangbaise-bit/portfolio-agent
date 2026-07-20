# CN Fund Info Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Give the agent `get_fund_info` for A-share funds/ETF联接: overview + tracked-index constituents.

**Architecture:** Extend `CNMarketAdapter` with `get_fund_info`; small CSI index name→code map; LangChain tool + system prompt nudge.

**Tech Stack:** akshare (`fund_overview_em`, `fund_individual_detail_info_xq`, `fund_individual_detail_hold_xq`, `index_stock_cons_csindex`)

---

### Task 1: Index map + adapter method

**Files:**
- Create: `adapters/cn_index_map.py`
- Modify: `adapters/cn_market.py`
- Test: `tests/test_cn_fund_info.py`

- [ ] Implement map + `get_fund_info`
- [ ] Unit tests with mocked akshare responses shaped like `020357`

### Task 2: Agent tool + prompt

**Files:**
- Modify: `agent/tools.py`, `agent/system_prompt.py`, `CLAUDE.md`

- [ ] Register `get_fund_info`
- [ ] Prompt: CN fund/ETF/联接 prefer this tool before financials
