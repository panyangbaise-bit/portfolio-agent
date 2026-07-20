# CN Fund / ETF Info Design

**Date:** 2026-07-20  
**Status:** Approved

## Problem

A-share funds/ETF联接 (e.g. `020357`) only expose price/NAV and K-line to the agent. Tracked index, fees, company, and constituents are missing, so analysis is shallow.

## Solution

Add `CNMarketAdapter.get_fund_info(ticker)` and agent tool `get_fund_info(ticker)` that return:

- Overview: name, type, company, manager, scale, benchmark, tracked index, fees (`fund_overview_em` + fee detail)
- Asset allocation when available (`fund_individual_detail_hold_xq`)
- Constituents via tracked CSI index (`index_stock_cons_csindex`) after resolving index name → code
- For `联接` funds: `fund_kind=etf_feeder` and note that constituents approximate the tracked index

## Index resolution

Curated map of common thematic CSI indices (includes `中证半导体材料设备主题指数` → `931865`). Unresolved index → overview still returned; `constituents=[]`.

## Out of scope

- Manual holdings fields
- Auto-trade on recommendations
- Guaranteed stock-level holdings from broken `fund_portfolio_hold_em`
