from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session

from config import config
from db.models import (
    Base, Holding, Transaction, PriceCache, NewsArticle, FinancialReport,
    AgentSession, AgentToolCall, Recommendation, UserAction,
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
        name=name,
    )
    session.add(holding)
    session.commit()
    return holding


def get_all_holdings(session: Session) -> list[Holding]:
    return session.query(Holding).all()


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
                       shares: float, price: float, notes: str = None) -> Transaction:
    txn = Transaction(
        holding_id=holding_id, action=action, shares=shares,
        price=price, notes=notes,
    )
    session.add(txn)
    session.commit()
    return txn


def get_transactions_for_holding(session: Session, holding_id: int) -> list[Transaction]:
    return session.query(Transaction).filter(
        Transaction.holding_id == holding_id
    ).order_by(desc(Transaction.date)).all()


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
                         news_snapshot: dict = None) -> AgentSession:
    s = AgentSession(triggered_by=triggered_by, news_snapshot=news_snapshot)
    session.add(s)
    session.commit()
    return s


def end_agent_session(session: Session, session_id: int):
    s = session.query(AgentSession).filter(AgentSession.id == session_id).first()
    if s:
        s.status = "completed"
        s.ended_at = datetime.now(timezone.utc)
        session.commit()


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
