from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session

from config import config
from db.models import (
    Base, Holding, Transaction, PriceCache, NewsArticle, FinancialReport,
    AgentSession, AgentToolCall, JobRun, Recommendation, UserAction,
)


engine = create_engine(config.DATABASE_URL, echo=False)


def init_db():
    """Create all tables. Call once at startup."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


# ── Holdings ──────────────────────────────────────────────

def create_holding(session: Session, ticker: str, market: str, shares: float,
                   cost_basis: float, position_type: str = "core",
                   name: str = None) -> Holding:
    holding = Holding(
        ticker=ticker.upper(), market=market.upper(), shares=shares,
        cost_basis=cost_basis, position_type=position_type,
        name=name, status="open",
    )
    session.add(holding)
    session.commit()
    return holding


def get_all_holdings(session: Session) -> list[Holding]:
    return session.query(Holding).all()


def get_open_holdings(session: Session) -> list[Holding]:
    """Active positions only (excludes closed / zero-share rows)."""
    return session.query(Holding).filter(Holding.status == "open").all()


def get_holding_by_ticker(session: Session, ticker: str) -> Optional[Holding]:
    return session.query(Holding).filter(Holding.ticker == ticker.upper()).first()


def update_holding(session: Session, holding_id: int, **kwargs) -> Optional[Holding]:
    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if holding:
        for k, v in kwargs.items():
            setattr(holding, k, v)
        holding.updated_at = datetime.now(timezone.utc)
        session.commit()
    return holding


def delete_holding(session: Session, holding_id: int) -> bool:
    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if holding:
        session.delete(holding)
        session.commit()
        return True
    return False


# ── Transactions ──────────────────────────────────────────

def create_transaction(session: Session, holding_id: int, action: str,
                       shares: float, price: float, notes: str = None,
                       date: datetime = None) -> Transaction:
    txn = Transaction(
        holding_id=holding_id, action=action, shares=shares,
        price=price, notes=notes,
    )
    if date is not None:
        txn.date = date
    session.add(txn)
    session.commit()
    return txn


def get_transactions_for_holding(session: Session, holding_id: int) -> list[Transaction]:
    return session.query(Transaction).filter(
        Transaction.holding_id == holding_id
    ).order_by(desc(Transaction.date)).all()


def get_recent_transactions(session: Session, days: int = 30) -> list[Transaction]:
    """Transactions from the last N days, newest first (holding eagerly usable)."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        session.query(Transaction)
        .filter(Transaction.date >= cutoff)
        .order_by(desc(Transaction.date))
        .all()
    )


def apply_trade(
    session: Session,
    holding_id: int,
    action: str,
    shares: float,
    price: float,
    notes: str = None,
    trade_date: datetime = None,
) -> Transaction:
    """Apply a buy/sell using broker-style average cost.

    Buy: new_cost = (old_shares * old_cost + shares * price) / new_shares;
    reopen closed positions.
    Sell: remaining_cost = (old_shares * old_cost - shares * price) / remaining;
    (matches common CN/HK broker 成本价; selling at a loss raises remaining cost).
    Full exit → shares=0, status=closed.
    """
    action = (action or "").lower().strip()
    if action not in ("buy", "sell"):
        raise ValueError(f"Invalid action: {action}")
    if shares is None or shares <= 0:
        raise ValueError("Shares must be positive")
    if price is None or price <= 0:
        raise ValueError("Price must be positive")

    holding = session.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise ValueError(f"Holding not found: {holding_id}")

    if action == "buy":
        old_shares = float(holding.shares or 0)
        if holding.status == "closed" or old_shares <= 0:
            old_shares = 0.0
        old_cost = float(holding.cost_basis or 0)
        new_shares = old_shares + shares
        if old_shares <= 0:
            new_cost = price
        else:
            new_cost = (old_shares * old_cost + shares * price) / new_shares
        holding.shares = new_shares
        holding.cost_basis = new_cost
        holding.status = "open"
    else:
        old_shares = float(holding.shares or 0)
        old_cost = float(holding.cost_basis or 0)
        if shares > old_shares + 1e-12:
            raise ValueError(
                f"Cannot sell {shares} shares; only {old_shares} available"
            )
        remaining = old_shares - shares
        if remaining < 1e-12:
            remaining = 0.0
            holding.shares = 0.0
            holding.status = "closed"
        else:
            # Broker-style: subtract sale proceeds from total cost, then re-average.
            remaining_total = old_shares * old_cost - shares * price
            holding.shares = remaining
            holding.cost_basis = remaining_total / remaining

    holding.updated_at = datetime.now(timezone.utc)

    txn = Transaction(
        holding_id=holding.id,
        action=action,
        shares=shares,
        price=price,
        notes=notes,
    )
    if trade_date is not None:
        txn.date = trade_date
    session.add(txn)
    session.commit()
    return txn


# ── Price Cache ───────────────────────────────────────────

def upsert_price(session: Session, ticker: str, market: str, date: datetime,
                 close: float, open_price: float = None, high: float = None,
                 low: float = None, volume: float = None, source: str = "") -> PriceCache:
    existing = session.query(PriceCache).filter(
        PriceCache.ticker == ticker.upper(),
        PriceCache.date == date,
    ).first()
    if existing:
        existing.close = close
        existing.open_price = open_price
        existing.high = high
        existing.low = low
        existing.volume = volume
        existing.source = source
        session.commit()
        return existing
    entry = PriceCache(
        ticker=ticker.upper(), market=market.upper(), date=date,
        open_price=open_price, high=high, low=low, close=close,
        volume=volume, source=source,
    )
    session.add(entry)
    session.commit()
    return entry


def get_price_history(session: Session, ticker: str, limit: int = 100) -> list[PriceCache]:
    return session.query(PriceCache).filter(
        PriceCache.ticker == ticker.upper()
    ).order_by(desc(PriceCache.date)).limit(limit).all()


def get_latest_prices(session: Session, holdings: list) -> dict:
    """Return the latest persisted closing price for each holding."""
    prices = {}
    for holding in holdings:
        entry = session.query(PriceCache).filter(
            PriceCache.ticker == holding.ticker.upper(),
            PriceCache.market == holding.market.upper(),
        ).order_by(desc(PriceCache.date)).first()
        prices[(holding.market, holding.ticker)] = entry.close if entry else None
    return prices


# ── News ──────────────────────────────────────────────────

def save_news_article(session: Session, headline: str, source: str = "wallstreetcn",
                      ticker: str = None, url: str = None, published_at: datetime = None,
                      summary: str = None) -> NewsArticle:
    article = NewsArticle(
        ticker=ticker.upper() if ticker else None,
        headline=headline, source=source, url=url,
        published_at=published_at, summary=summary,
    )
    session.add(article)
    session.commit()
    return article


def get_recent_news(session: Session, ticker: str = None, limit: int = 50) -> list[NewsArticle]:
    q = session.query(NewsArticle)
    if ticker:
        q = q.filter(NewsArticle.ticker == ticker.upper())
    return q.order_by(desc(NewsArticle.published_at)).limit(limit).all()


# ── Financial Reports ─────────────────────────────────────

def save_financial_report(session: Session, ticker: str, market: str,
                          report_date: datetime, report_type: str,
                          revenue: float = None, eps: float = None,
                          key_metrics: dict = None) -> FinancialReport:
    report = FinancialReport(
        ticker=ticker.upper(), market=market.upper(),
        report_date=report_date, report_type=report_type,
        revenue=revenue, eps=eps, key_metrics=key_metrics,
    )
    session.add(report)
    session.commit()
    return report


# ── Agent Sessions ────────────────────────────────────────

def create_agent_session(session: Session, triggered_by: str,
                         news_snapshot: dict = None,
                         job_id: str = None,
                         market: str = None) -> AgentSession:
    s = AgentSession(
        triggered_by=triggered_by,
        news_snapshot=news_snapshot,
        job_id=job_id,
        market=market,
    )
    session.add(s)
    session.commit()
    return s


def end_agent_session(
    session: Session,
    session_id: int,
    summary: str = None,
    status: str = "completed",
):
    """Mark an agent session terminal. Late 'completed' does not overwrite 'failed'."""
    s = session.query(AgentSession).filter(AgentSession.id == session_id).first()
    if not s:
        return
    if s.status == "failed" and status == "completed":
        return
    s.status = status
    s.ended_at = datetime.now(timezone.utc)
    if summary is not None:
        s.summary = summary
    session.commit()


def list_analysis_runs(
    session: Session,
    limit: int = 50,
    job_id: Optional[str] = None,
) -> list[dict]:
    """Return agent sessions with recommendation aggregates for the Jobs detail list."""
    query = session.query(AgentSession).order_by(desc(AgentSession.started_at))
    if job_id:
        query = query.filter(AgentSession.job_id == job_id)
    runs = query.limit(limit).all()
    rows = []
    for s in runs:
        recs = s.recommendations or []
        actions = []
        max_conf = None
        pending = 0
        for r in recs:
            actions.append(f"{r.ticker}:{r.action}")
            if max_conf is None or r.confidence > max_conf:
                max_conf = r.confidence
            if r.status == "pending":
                pending += 1
        summary = s.summary or ""
        if len(summary) > 120:
            summary = summary[:117] + "..."
        rows.append({
            "id": s.id,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "job_id": s.job_id,
            "market": s.market,
            "triggered_by": s.triggered_by,
            "status": s.status,
            "rec_count": len(recs),
            "pending_count": pending,
            "actions": ", ".join(actions) if actions else "—",
            "max_confidence": max_conf,
            "summary": summary if summary else "—",
            "tool_count": len(s.tool_calls or []),
        })
    return rows


def get_agent_session_detail(session: Session, session_id: int) -> Optional[dict]:
    """Return one agent session with full summary, recommendations, and tool calls."""
    s = session.query(AgentSession).filter(AgentSession.id == session_id).first()
    if not s:
        return None

    recommendations = sorted(
        s.recommendations or [],
        key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    tool_calls = sorted(
        s.tool_calls or [],
        key=lambda c: c.called_at or datetime.min.replace(tzinfo=timezone.utc),
    )

    return {
        "id": s.id,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "job_id": s.job_id,
        "market": s.market,
        "triggered_by": s.triggered_by,
        "status": s.status,
        "summary": s.summary,
        "recommendations": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "action": r.action,
                "reasoning": r.reasoning,
                "confidence": r.confidence,
                "urgency": r.urgency,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in recommendations
        ],
        "tool_calls": [
            {
                "id": c.id,
                "tool_name": c.tool_name,
                "params": c.params,
                "result_summary": c.result_summary,
                "called_at": c.called_at,
            }
            for c in tool_calls
        ],
    }


def create_job_run(session: Session, job_id: str, job_name: str) -> JobRun:
    """Record that a scheduled job has started."""
    run = JobRun(job_id=job_id, job_name=job_name)
    session.add(run)
    session.commit()
    return run


def finish_job_run(session: Session, run_id: int, status: str,
                   details: str = None):
    """Store a completed, skipped, or failed scheduler job outcome."""
    run = session.query(JobRun).filter(JobRun.id == run_id).first()
    if run:
        run.status = status
        run.details = details
        run.ended_at = datetime.now(timezone.utc)
        session.commit()


def list_job_runs(session: Session, limit: int = 50) -> list[JobRun]:
    """Return the most recent scheduler outcomes for dashboard diagnostics."""
    return session.query(JobRun).order_by(
        desc(JobRun.started_at)
    ).limit(limit).all()


def log_tool_call(session: Session, session_id: int, tool_name: str,
                  params: dict = None, result_summary: str = None) -> AgentToolCall:
    call = AgentToolCall(
        session_id=session_id, tool_name=tool_name,
        params=params, result_summary=result_summary,
    )
    session.add(call)
    session.commit()
    return call


# ── Recommendations ───────────────────────────────────────

def create_recommendation(session: Session, session_id: int, ticker: str,
                          action: str, reasoning: str, confidence: float,
                          urgency: str = "low") -> Recommendation:
    rec = Recommendation(
        session_id=session_id, ticker=ticker.upper(),
        action=action, reasoning=reasoning,
        confidence=confidence, urgency=urgency,
    )
    session.add(rec)
    session.commit()
    return rec


def find_similar_recommendation(
    session: Session,
    ticker: str,
    action: str,
    urgency: str = "low",
    within_days: int = 7,
) -> Optional[Recommendation]:
    """Return an existing rec that would make a new one redundant.

    Prefer an open pending with the same action; else a recent rec with the
    same action + urgency (user already acted/dismissed the same call).
    """
    from datetime import timedelta

    ticker_u = ticker.upper()
    action_n = (action or "").strip().lower()
    urgency_n = (urgency or "low").strip().lower()

    pending = (
        session.query(Recommendation)
        .filter(
            Recommendation.ticker == ticker_u,
            Recommendation.status == "pending",
            Recommendation.action == action_n,
        )
        .order_by(desc(Recommendation.created_at))
        .first()
    )
    if pending:
        return pending

    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    recent = (
        session.query(Recommendation)
        .filter(
            Recommendation.ticker == ticker_u,
            Recommendation.action == action_n,
            Recommendation.urgency == urgency_n,
            Recommendation.created_at >= cutoff,
        )
        .order_by(desc(Recommendation.created_at))
        .first()
    )
    return recent


def get_pending_recommendations(session: Session) -> list[Recommendation]:
    return session.query(Recommendation).filter(
        Recommendation.status == "pending"
    ).order_by(desc(Recommendation.created_at)).all()


def get_recommendation_history(session: Session, ticker: str = None,
                               limit: int = 50) -> list[Recommendation]:
    q = session.query(Recommendation)
    if ticker:
        q = q.filter(Recommendation.ticker == ticker.upper())
    return q.order_by(desc(Recommendation.created_at)).limit(limit).all()


# ── User Actions ──────────────────────────────────────────

def record_user_action(session: Session, recommendation_id: int,
                       action: str, notes: str = None) -> UserAction:
    ua = UserAction(recommendation_id=recommendation_id, action=action, notes=notes)
    session.add(ua)
    rec = session.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
    if rec:
        rec.status = "acted" if action == "accept" else "dismissed"
    session.commit()
    return ua


# ── Watchlist ─────────────────────────────────────────────

def create_watchlist_item(
    session: Session,
    ticker: str,
    market: str,
    name: str = None,
    watch_reason: str = None,
    target_price_low: float = None,
    target_price_high: float = None,
    priority: str = "medium",
) -> "WatchlistItem":
    from db.models import WatchlistItem
    item = WatchlistItem(
        ticker=ticker.upper(),
        market=market.upper(),
        name=name,
        watch_reason=watch_reason,
        target_price_low=target_price_low,
        target_price_high=target_price_high,
        status="watching",
        priority=priority,
    )
    session.add(item)
    session.commit()
    return item


def get_watchlist_items(session: Session, status: str = None) -> list:
    """Return watchlist items, optionally filtered by status."""
    from db.models import WatchlistItem
    q = session.query(WatchlistItem)
    if status:
        q = q.filter(WatchlistItem.status == status)
    return q.order_by(WatchlistItem.priority.desc(), WatchlistItem.created_at.desc()).all()


def get_watchlist_by_ticker(session: Session, ticker: str):
    """Return a watchlist item by ticker, or None."""
    from db.models import WatchlistItem
    return session.query(WatchlistItem).filter(WatchlistItem.ticker == ticker.upper()).first()


def update_watchlist_item(session: Session, item_id: int, **kwargs):
    """Update watchlist item fields. Returns the updated item or None."""
    from db.models import WatchlistItem
    from datetime import datetime, timezone
    item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        for k, v in kwargs.items():
            if v is not None and hasattr(item, k):
                setattr(item, k, v)
        item.updated_at = datetime.now(timezone.utc)
        session.commit()
    return item


def delete_watchlist_item(session: Session, item_id: int) -> bool:
    """Delete a watchlist item. Returns True if deleted."""
    from db.models import WatchlistItem
    item = session.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        session.delete(item)
        session.commit()
        return True
    return False
