# Portfolio Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-powered personal portfolio management agent with autonomous reasoning, multi-market data adapters, and a Streamlit dashboard.

**Architecture:** Layered Python application. `adapters/` wrap market data sources behind a common interface. `agent/` uses LangGraph with Anthropic tool-use to run an observe→reason→act→decide loop. `scheduler/` triggers agent activations via APScheduler. `app/` is a Streamlit dashboard. `db/` stores all state in SQLite via SQLAlchemy.

**Tech Stack:** Python 3.11+, Streamlit, LangChain/LangGraph, Anthropic Claude API, SQLAlchemy + SQLite, yfinance, akshare, pycoingecko, APScheduler, python-telegram-bot

---

## Phase 1: Foundation

### Task 1: Project skeleton and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `config.py`

- [ ] **Step 1: Write requirements.txt**

```txt
# UI
streamlit>=1.28.0

# Agent
langchain>=0.3.0
langgraph>=0.2.0
langchain-anthropic>=0.2.0

# Data
yfinance>=0.2.40
akshare>=1.14.0
pycoingecko>=3.1.0
requests>=2.31.0

# Database
sqlalchemy>=2.0.0

# Scheduling
apscheduler>=3.10.0

# Notifications
python-telegram-bot>=20.0

# Config
python-dotenv>=1.0.0
pyyaml>=6.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 3: Write config.py**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent


class Config:
    # Database
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'portfolio.db'}"

    # Anthropic
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-20251001")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Scheduler
    NEWS_POLL_INTERVAL_MINUTES: int = 60

    # News API
    WALLSTREETCN_BASE_URL: str = "https://api-one-wscn.awtmt.com/apiv1"

    # Markets that require trading-day checks (crypto is 24/7)
    TRADING_MARKETS: dict = {
        "US": {"timezone": "America/New_York", "close_hour": 16, "close_minute": 0},
        "CN": {"timezone": "Asia/Shanghai", "close_hour": 15, "close_minute": 0},
        "HK": {"timezone": "Asia/Hong_Kong", "close_hour": 16, "close_minute": 0},
    }


config = Config()
```

- [ ] **Step 4: Create .env.example**

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-5-20251001

# Telegram (optional — leave empty to disable notifications)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.py .env.example
git commit -m "feat: project skeleton with config and dependencies"
```

---

### Task 2: Database models

**Files:**
- Create: `db/__init__.py`
- Create: `db/models.py`

- [ ] **Step 1: Create db package init**

```python
# db/__init__.py
from .models import (
    Base,
    Holding,
    Transaction,
    PriceCache,
    NewsArticle,
    FinancialReport,
    AgentSession,
    AgentToolCall,
    Recommendation,
    UserAction,
)
```

- [ ] **Step 2: Write db/models.py**

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Text, JSON, Enum, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Holding(Base):
    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False)
    position_type: Mapped[str] = mapped_column(String(20), nullable=False, default="core")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    transactions = relationship("Transaction", back_populates="holding", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    holding_id: Mapped[int] = mapped_column(ForeignKey("holdings.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    holding = relationship("Holding", back_populates="transactions")


class PriceCache(Base):
    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="wallstreetcn")
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False)
    report_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key_metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    news_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    tool_calls = relationship("AgentToolCall", back_populates="session", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="session", cascade="all, delete-orphan")


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    called_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session = relationship("AgentSession", back_populates="tool_calls")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    urgency: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session = relationship("AgentSession", back_populates="recommendations")
    user_action = relationship("UserAction", back_populates="recommendation", uselist=False, cascade="all, delete-orphan")


class UserAction(Base):
    __tablename__ = "user_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"), nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    recommendation = relationship("Recommendation", back_populates="user_action")
```

- [ ] **Step 3: Verify models can be imported**

Run: `python -c "from db.models import Base; print('Models OK, tables:', len(Base.metadata.tables))"`
Expected: `Models OK, tables: 8`

- [ ] **Step 4: Commit**

```bash
git add db/
git commit -m "feat: database models — holdings, transactions, caches, agent decision chain"
```

---

### Task 3: Database repository layer

**Files:**
- Create: `db/repository.py`

- [ ] **Step 1: Write db/repository.py**

```python
from datetime import datetime
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
                   cost_basis: float, position_type: str = "core") -> Holding:
    holding = Holding(
        ticker=ticker.upper(), market=market.upper(), shares=shares,
        cost_basis=cost_basis, position_type=position_type,
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
        holding.updated_at = datetime.utcnow()
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
                 close: float, open: float = None, high: float = None,
                 low: float = None, volume: float = None, source: str = "") -> PriceCache:
    existing = session.query(PriceCache).filter(
        PriceCache.ticker == ticker.upper(),
        PriceCache.date == date,
    ).first()
    if existing:
        existing.close = close
        existing.open = open
        existing.high = high
        existing.low = low
        existing.volume = volume
        session.commit()
        return existing
    entry = PriceCache(
        ticker=ticker.upper(), market=market.upper(), date=date,
        open=open, high=high, low=low, close=close,
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
        s.ended_at = datetime.utcnow()
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
```

- [ ] **Step 2: Verify repository imports**

Run: `python -c "from db.repository import init_db, get_session; print('Repository OK')"`
Expected: `Repository OK`

- [ ] **Step 3: Commit**

```bash
git add db/repository.py
git commit -m "feat: database repository layer with CRUD for all 8 tables"
```

---

## Phase 2: Data Adapters

### Task 4: Market adapter base class

**Files:**
- Create: `adapters/__init__.py`
- Create: `adapters/base.py`

- [ ] **Step 1: Write adapters/base.py**

```python
from abc import ABC, abstractmethod
from typing import Optional


class MarketAdapter(ABC):
    """Common interface for all market data sources.

    Each market gets its own adapter implementing these methods.
    The adapter handles all data-source-specific logic (ticker format,
    API calls, error handling) and returns normalized dicts.
    """

    @abstractmethod
    def get_price(self, ticker: str) -> dict:
        """Return current price info.

        Returns: {ticker, price, currency, change_pct, volume, timestamp}
        """
        ...

    @abstractmethod
    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        """Return historical K-line data.

        period: "1mo" | "3mo" | "6mo" | "1y" | "5y"
        Returns: [{date, open, high, low, close, volume}, ...]
        """
        ...

    @abstractmethod
    def get_financials(self, ticker: str) -> dict:
        """Return latest financial report data.

        Returns: {ticker, report_date, revenue, revenue_growth, eps,
                  pe_ratio, pb_ratio, roe, ...}
        """
        ...

    @abstractmethod
    def get_market_snapshot(self) -> dict:
        """Return broad market index overview.

        Returns: {index_name, current, change_pct, ytd_change, ...}
        """
        ...


class AdapterRegistry:
    """Route market code to the right adapter."""

    def __init__(self):
        self._adapters: dict[str, MarketAdapter] = {}

    def register(self, market: str, adapter: MarketAdapter):
        self._adapters[market.upper()] = adapter

    def get(self, market: str) -> MarketAdapter:
        adapter = self._adapters.get(market.upper())
        if adapter is None:
            raise ValueError(f"No adapter registered for market: {market}")
        return adapter

    @property
    def markets(self) -> list[str]:
        return list(self._adapters.keys())


# Global registry — populated at startup
registry = AdapterRegistry()
```

- [ ] **Step 2: Verify adapter base imports**

Run: `python -c "from adapters.base import MarketAdapter, AdapterRegistry, registry; print('Base OK')"`
Expected: `Base OK`

- [ ] **Step 3: Commit**

```bash
git add adapters/
git commit -m "feat: market adapter base class and registry"
```

---

### Task 5: US market adapter (yfinance)

**Files:**
- Create: `adapters/us_market.py`

- [ ] **Step 1: Write adapters/us_market.py**

```python
from datetime import datetime
from typing import Optional
import yfinance as yf

from adapters.base import MarketAdapter


class USMarketAdapter(MarketAdapter):
    """US stock data via yfinance."""

    MARKET = "US"

    def get_price(self, ticker: str) -> dict:
        stock = yf.Ticker(ticker)
        info = stock.info
        fast = stock.fast_info
        return {
            "ticker": ticker.upper(),
            "price": fast.get("lastPrice") or info.get("currentPrice"),
            "currency": info.get("currency", "USD"),
            "change_pct": self._safe_pct(info.get("regularMarketChangePercent")),
            "volume": info.get("regularMarketVolume"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        if df.empty:
            return []
        return [
            {
                "date": idx.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]

    def get_financials(self, ticker: str) -> dict:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "ticker": ticker.upper(),
            "report_date": self._safe_date(info.get("lastFiscalYearEnd")),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": self._safe_pct(info.get("revenueGrowth")),
            "eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe": self._safe_pct(info.get("returnOnEquity")),
            "profit_margins": self._safe_pct(info.get("profitMargins")),
            "earnings_date_next": self._safe_date(info.get("earningsDate")),
            "dividend_yield": self._safe_pct(info.get("dividendYield")),
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_market_snapshot(self) -> dict:
        spx = yf.Ticker("^GSPC")
        info = spx.fast_info
        return {
            "index_name": "S&P 500",
            "current": info.get("lastPrice"),
            "change_pct": self._safe_pct(info.get("regularMarketChangePercent")),
            "ytd_change": self._safe_pct(self._calc_ytd(spx)),
        }

    @staticmethod
    def _safe_pct(value) -> Optional[float]:
        if value is None:
            return None
        try:
            v = float(value)
            return round(v, 2) if abs(v) < 100 else v  # yfinance sometimes returns 100x
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_date(value) -> Optional[str]:
        if value is None:
            return None
        try:
            ts = int(value) if not isinstance(value, (int, float)) else value
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            return str(value)[:10]

    @staticmethod
    def _calc_ytd(stock) -> Optional[float]:
        try:
            df = stock.history(period="ytd")
            if len(df) >= 2:
                return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
        except Exception:
            pass
        return None
```

- [ ] **Step 2: Test adapter with a real ticker**

Run: `python -c "
from adapters.us_market import USMarketAdapter
a = USMarketAdapter()
p = a.get_price('AAPL')
print('AAPL price:', p['price'], p['currency'])
k = a.get_kline('AAPL', '1mo')
print('K-line rows:', len(k))
f = a.get_financials('AAPL')
print('PE ratio:', f['pe_ratio'])
print('US adapter OK')
"`

- [ ] **Step 3: Commit**

```bash
git add adapters/us_market.py
git commit -m "feat: US market adapter via yfinance"
```

---

### Task 6: CN market adapter (akshare — A-shares + HK)

**Files:**
- Create: `adapters/cn_market.py`

- [ ] **Step 1: Write adapters/cn_market.py**

```python
from datetime import datetime
from typing import Optional
import akshare as ak

from adapters.base import MarketAdapter


class CNMarketAdapter(MarketAdapter):
    """A-share market data via akshare."""

    MARKET = "CN"

    def get_price(self, ticker: str) -> dict:
        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == ticker]
            if row.empty:
                raise ValueError(f"Ticker {ticker} not found")
            r = row.iloc[0]
            return {
                "ticker": ticker,
                "price": float(r["最新价"]),
                "currency": "CNY",
                "change_pct": float(r["涨跌幅"]),
                "volume": float(r["成交量"]) if "成交量" in r else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get CN price for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        mapping = {"1mo": "monthly", "3mo": "quarterly", "6mo": "halfyear", "1y": "yearly", "5y": "yearly"}
        freq = mapping.get(period, "daily")
        try:
            df = ak.stock_zh_a_hist(symbol=ticker, period=freq, adjust="qfq")
            if df.empty:
                return []
            return [
                {
                    "date": str(row["日期"])[:10],
                    "open": float(row["开盘"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                    "close": float(row["收盘"]),
                    "volume": float(row["成交量"]) if "成交量" in row else None,
                }
                for _, row in df.tail(90).iterrows()
            ]
        except Exception as e:
            raise RuntimeError(f"Failed to get CN kline for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        try:
            df = ak.stock_financial_abstract_ths(symbol=ticker, indicator="按报告期")
            if df.empty:
                return {"ticker": ticker, "note": "no financial data available"}
            latest = df.iloc[0]
            return {
                "ticker": ticker,
                "report_date": str(latest.get("报告期", ""))[:10],
                "revenue": self._safe_float(latest.get("营业总收入")),
                "revenue_growth": self._safe_float(latest.get("营业总收入同比增长")),
                "eps": self._safe_float(latest.get("基本每股收益")),
                "roe": self._safe_float(latest.get("净资产收益率")),
                "profit_margin": self._safe_float(latest.get("销售净利率")),
            }
        except Exception as e:
            return {"ticker": ticker, "error": str(e)}

    def get_market_snapshot(self) -> dict:
        try:
            df = ak.stock_zh_index_daily(symbol="sh000001")
            if df.empty:
                return {"index_name": "上证指数", "error": "no data"}
            latest = df.iloc[-1]
            return {
                "index_name": "上证指数",
                "current": float(latest["close"]),
                "change_pct": round(float(latest.get("pct_chg", 0)), 2),
            }
        except Exception as e:
            return {"index_name": "上证指数", "error": str(e)}

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None or value == "" or value == "--":
            return None
        try:
            return round(float(value), 2)
        except (ValueError, TypeError):
            return None


class HKMarketAdapter(MarketAdapter):
    """Hong Kong market data via akshare."""

    MARKET = "HK"

    def get_price(self, ticker: str) -> dict:
        try:
            df = ak.stock_hk_spot_em()
            row = df[df["代码"] == ticker]
            if row.empty:
                raise ValueError(f"Ticker {ticker} not found")
            r = row.iloc[0]
            return {
                "ticker": ticker,
                "price": float(r["最新价"]),
                "currency": "HKD",
                "change_pct": float(r["涨跌幅"]),
                "volume": float(r["成交量"]) if "成交量" in r else None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get HK price for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        try:
            df = ak.stock_hk_hist(symbol=ticker, period="daily", adjust="qfq")
            if df.empty:
                return []
            return [
                {
                    "date": str(row["日期"])[:10],
                    "open": float(row["开盘"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                    "close": float(row["收盘"]),
                    "volume": float(row["成交量"]) if "成交量" in row else None,
                }
                for _, row in df.tail(90).iterrows()
            ]
        except Exception as e:
            raise RuntimeError(f"Failed to get HK kline for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        return {"ticker": ticker, "note": "HK financials via akshare limited; use manual input or alternative source"}

    def get_market_snapshot(self) -> dict:
        try:
            df = ak.stock_hk_index_daily_em()
            if df.empty:
                return {"index_name": "恒生指数", "error": "no data"}
            latest = df.iloc[-1]
            return {
                "index_name": "恒生指数",
                "current": float(latest.get("close", 0) or latest.get("收盘", 0)),
            }
        except Exception as e:
            return {"index_name": "恒生指数", "error": str(e)}
```

- [ ] **Step 2: Quick smoke test for CN adapter**

Run: `python -c "
from adapters.cn_market import CNMarketAdapter
a = CNMarketAdapter()
try:
    snap = a.get_market_snapshot()
    print('CN market snapshot:', snap.get('current', snap.get('error')))
except Exception as e:
    print(f'CN adapter test skipped (network?): {e}')
print('CN adapter module OK')
"`

- [ ] **Step 3: Commit**

```bash
git add adapters/cn_market.py
git commit -m "feat: CN and HK market adapters via akshare"
```

---

### Task 7: Crypto adapter (CoinGecko)

**Files:**
- Create: `adapters/crypto.py`

- [ ] **Step 1: Write adapters/crypto.py**

```python
from datetime import datetime
from typing import Optional
from pycoingecko import CoinGeckoAPI

from adapters.base import MarketAdapter


cg = CoinGeckoAPI()

# CoinGecko ID mapping for common tickers
TICKER_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
}


class CryptoAdapter(MarketAdapter):
    """Crypto data via CoinGecko free API."""

    MARKET = "CRYPTO"

    def _get_id(self, ticker: str) -> str:
        return TICKER_TO_ID.get(ticker.upper(), ticker.lower())

    def get_price(self, ticker: str) -> dict:
        coin_id = self._get_id(ticker)
        try:
            data = cg.get_price(
                ids=coin_id,
                vs_currencies="usd",
                include_market_cap=True,
                include_24hr_vol=True,
                include_24hr_change=True,
            )
            info = data.get(coin_id, {})
            return {
                "ticker": ticker.upper(),
                "price": info.get("usd"),
                "currency": "USD",
                "change_pct": round(info.get("usd_24h_change", 0), 2),
                "volume": info.get("usd_24h_vol"),
                "market_cap": info.get("usd_market_cap"),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"CoinGecko price failed for {ticker}: {e}")

    def get_kline(self, ticker: str, period: str = "3mo") -> list[dict]:
        coin_id = self._get_id(ticker)
        days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "5y": 1825}
        days = days_map.get(period, 90)
        try:
            data = cg.get_coin_market_chart_by_id(id=coin_id, vs_currency="usd", days=days)
            prices = data.get("prices", [])
            total_volumes = data.get("total_volumes", [])
            return [
                {
                    "date": datetime.fromtimestamp(p[0] / 1000).strftime("%Y-%m-%d"),
                    "price": p[1],
                    "volume": total_volumes[i][1] if i < len(total_volumes) else None,
                }
                for i, p in enumerate(prices)
                if i % max(1, len(prices) // 100) == 0
            ]
        except Exception as e:
            raise RuntimeError(f"CoinGecko kline failed for {ticker}: {e}")

    def get_financials(self, ticker: str) -> dict:
        coin_id = self._get_id(ticker)
        try:
            data = cg.get_coin_by_id(id=coin_id)
            market = data.get("market_data", {})
            return {
                "ticker": ticker.upper(),
                "name": data.get("name", coin_id),
                "market_cap": market.get("market_cap", {}).get("usd"),
                "total_volume": market.get("total_volume", {}).get("usd"),
                "fdv": market.get("fully_diluted_valuation", {}).get("usd"),
                "circulating_supply": market.get("circulating_supply"),
                "total_supply": market.get("total_supply"),
                "max_supply": market.get("max_supply"),
                "ath": market.get("ath", {}).get("usd"),
                "ath_change_pct": round(market.get("ath_change_percentage", {}).get("usd", 0), 2),
                "genesis_date": data.get("genesis_date"),
                "categories": data.get("categories", [])[:5],
            }
        except Exception as e:
            return {"ticker": ticker.upper(), "error": str(e)}

    def get_market_snapshot(self) -> dict:
        try:
            data = cg.get_global()
            mkt = data.get("data", {})
            return {
                "index_name": "Crypto Total Market",
                "current": mkt.get("total_market_cap", {}).get("usd"),
                "change_pct": round(mkt.get("market_cap_change_percentage_24h_usd", 0), 2),
                "btc_dominance": round(mkt.get("market_cap_percentage", {}).get("btc", 0), 2),
                "active_cryptocurrencies": mkt.get("active_cryptocurrencies"),
            }
        except Exception as e:
            return {"index_name": "Crypto Market", "error": str(e)}
```

- [ ] **Step 2: Smoke test crypto adapter**

Run: `python -c "
from adapters.crypto import CryptoAdapter
a = CryptoAdapter()
try:
    p = a.get_price('BTC')
    print('BTC price:', p.get('price', p.get('error')))
except Exception as e:
    print(f'Crypto adapter test skipped: {e}')
print('Crypto adapter module OK')
"`

- [ ] **Step 3: Commit**

```bash
git add adapters/crypto.py
git commit -m "feat: crypto adapter via CoinGecko"
```

---

### Task 8: News adapter (WallStreetCN)

**Files:**
- Create: `adapters/news.py`

- [ ] **Step 1: Write adapters/news.py**

```python
from datetime import datetime
from typing import Optional
import requests

from config import config


class WallStreetCNAdapter:
    """News adapter for 华尔街见闻 API."""

    BASE = config.WALLSTREETCN_BASE_URL

    def get_headlines(self, limit: int = 10) -> list[dict]:
        """Top carousel headlines."""
        url = f"{self.BASE}/content/carousel/information-flow"
        try:
            resp = requests.get(url, params={"channel": "global", "limit": limit}, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("items", [])
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] headlines fetch failed: {e}")
            return []

    def get_latest_news(self, limit: int = 10) -> list[dict]:
        """Latest information flow."""
        url = f"{self.BASE}/content/information-flow"
        try:
            resp = requests.get(
                url, params={"channel": "global", "accept": "article", "limit": limit}, timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("items", [])
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] latest fetch failed: {e}")
            return []

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search articles by keyword (use ticker or Chinese name)."""
        url = f"{self.BASE}/search/article"
        try:
            resp = requests.get(url, params={"query": query, "limit": limit}, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("items", [])
            return self._parse_items(items)
        except Exception as e:
            print(f"[news] search failed for '{query}': {e}")
            return []

    def get_hot_articles(self) -> list[dict]:
        """Trending hot articles."""
        url = f"{self.BASE}/content/articles/hot"
        try:
            resp = requests.get(url, params={"period": "all"}, timeout=10)
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("day_items", [])
            return self._parse_items(items, is_hot=True)
        except Exception as e:
            print(f"[news] hot articles failed: {e}")
            return []

    def search_ticker_news(self, ticker: str, days: int = 7) -> list[dict]:
        """Search news for a specific ticker."""
        results = self.search(query=ticker, limit=5)
        cutoff = datetime.utcnow().timestamp() - (days * 86400)
        return [r for r in results if r.get("published_at", 0) >= cutoff]

    @staticmethod
    def _parse_items(items: list, is_hot: bool = False) -> list[dict]:
        parsed = []
        for item in items:
            resource = item if is_hot else item.get("resource", item)
            ts = resource.get("display_time", 0)
            parsed.append({
                "title": resource.get("title", ""),
                "uri": resource.get("uri", ""),
                "url": f"https://wallstreetcn.com/articles/{resource.get('uri', '')}" if resource.get("uri") else "",
                "summary": (resource.get("content_short") or "")[:200],
                "published_at": datetime.fromtimestamp(ts).isoformat() if ts else None,
                "author": (resource.get("author") or {}).get("display_name", ""),
            })
        return parsed


# Singleton
news_adapter = WallStreetCNAdapter()
```

- [ ] **Step 2: Test news adapter**

Run: `python -c "
from adapters.news import news_adapter
try:
    headlines = news_adapter.get_headlines(3)
    print(f'Headlines: {len(headlines)}')
    if headlines:
        print(f'  First: {headlines[0][\"title\"][:60]}')
    results = news_adapter.search('苹果', 3)
    print(f'Search for 苹果: {len(results)} results')
except Exception as e:
    print(f'News adapter test (may need network): {e}')
print('News adapter OK')
"`

- [ ] **Step 4: Commit**

```bash
git add adapters/news.py
git commit -m "feat: news adapter for WallStreetCN API"
```

---

## Phase 3: Agent Engine

### Task 9: Agent system prompt

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/system_prompt.py`

- [ ] **Step 1: Write agent/system_prompt.py**

```python
SYSTEM_PROMPT = """你是一个个人投资组合管理 agent，服务于一位采用"核心+卫星"混合策略的投资者。

## 你的角色

你的目标不是频繁交易，而是在关键信息出现时，提供有依据的仓位调整建议。你必须通过调用工具来获取数据——绝不假装知道实时行情。

## 投资策略

用户持仓分为两类，分析时必须区分：

**核心仓 (Core) — 长期持有（数月~数年）：**
- 分析维度：宏观经济格局、行业景气度、基本面（营收/利润率/ROE/护城河）、长期趋势
- 重点关注：利率环境、行业政策、竞争格局、估值分位数
- K线周期偏好：3mo ~ 1y

**卫星仓 (Satellite) — 短期操作（数天~数周）：**
- 分析维度：技术指标（均线/量价/MACD）、资金流向、市场情绪、短期催化
- 重点关注：新闻事件驱动、技术面突破/破位、财报预期
- K线周期偏好：1mo ~ 3mo

## 工作流程

每次激活时，遵循以下步骤：
1. 先调用 get_portfolio() 了解当前持仓
2. 查看最新新闻：get_market_headlines() 和 search_ticker_news()
3. 根据新闻和持仓情况，判断需要深入查询哪些标的的数据
4. 按需调用 get_price、get_kline、get_financials
5. 综合信息，生成建议

**重要原则：**
- 核心仓重点查长周期 K 线（3mo-1y）+ 财报基本面
- 卫星仓重点查短周期 K 线（1mo-3mo）+ 技术指标
- 不要每次都全量拉所有标的的数据——只查有新闻或异常的标的
- 财报季前后，优先查 financials

## 输出规范

每条分析结果必须包含：
- action: buy_add（加仓）| reduce（减仓）| hold（持有）| watch（关注）
- ticker: 标的代码
- position_type: core | satellite
- reasoning: 推理链（2-4句话，说明从哪些信息推到了什么结论）
- confidence: 0.0-1.0（你对建议的确信程度）
- urgency: low | medium | high
- time_horizon: 建议适用的时间范围
- risk_note: 需要注意的风险点（可选）

## 禁止事项

- 不预测具体价格点位
- 不推荐杠杆或衍生品操作
- 不给无数据支撑的建议（每条结论必须有 tool 返回的数据支撑）
- 单次输出不超过 3 个标的的建议
- 不假装知道实时数据——所有行情数据必须通过工具获取

## 特殊场景

- **无异常时**：输出简短健康确认，说明 "今日盘后检查：所有持仓正常，无需调整"
- **重大事件时**：优先分析受影响标的，标注 urgency=high
- **用户提问时**：优先回答用户关心的标的，但也要检查组合整体状况
"""

AFTER_MARKET_PROMPT_EXTRA = """
## 当前任务：{market}市场盘后分析

请对 {market} 市场的所有持仓进行例行盘后分析。
对于每个持仓标的：
- 核心仓：关注基本面变化、长期趋势、估值水平
- 卫星仓：关注技术指标、短期走势、资金流向

即使没有异常，也要输出每个标的的状态确认。
"""

NEWS_TRIGGER_PROMPT_EXTRA = """
## 当前任务：新闻事件分析

以下是最新抓取的相关新闻，请分析对持仓的影响：
{news_summary}

请逐一判断这些新闻是否对持仓有实质影响。无影响的跳过，有影响的深入分析。
"""
```

- [ ] **Step 2: Commit**

```bash
git add agent/
git commit -m "feat: agent system prompt — core/satellite analysis framework in Chinese"
```

---

### Task 10: Agent tools (LangChain tool definitions)

**Files:**
- Create: `agent/tools.py`

- [ ] **Step 1: Write agent/tools.py**

```python
"""LangChain tool definitions for the portfolio agent.

Each tool wraps an adapter method or DB query, presenting a clean
interface to the LLM. The agent does not know about adapters, markets,
or databases — it just calls these functions.
"""

from datetime import datetime
from typing import Optional

from langchain.tools import tool

from db.repository import (
    get_session, get_all_holdings, get_holding_by_ticker,
    create_recommendation, get_recommendation_history as db_get_rec_history,
    upsert_price,
)
from adapters.base import registry as adapter_registry
from adapters.news import news_adapter


# ── Portfolio Tools ───────────────────────────────────────

@tool
def get_portfolio() -> list[dict]:
    """获取当前所有持仓列表，包括每个标的的代码、市场、股数、成本价和仓位类型。

    Returns:
        list[dict]: 持仓列表，每项含 ticker, market, shares, cost_basis, position_type, pnl_pct, weight_pct
    """
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        total_value = 0.0
        values = []
        for h in holdings:
            try:
                adapter = adapter_registry.get(h.market)
                price_data = adapter.get_price(h.ticker)
                current_price = price_data.get("price", 0) or 0
            except Exception:
                current_price = h.cost_basis
            market_value = h.shares * current_price
            total_value += market_value
            pnl_pct = ((current_price - h.cost_basis) / h.cost_basis * 100) if h.cost_basis else 0
            values.append({
                "ticker": h.ticker,
                "market": h.market,
                "shares": h.shares,
                "cost_basis": h.cost_basis,
                "current_price": round(current_price, 2),
                "position_type": h.position_type,
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(market_value, 2),
                "holding_id": h.id,
            })

        for v in values:
            v["weight_pct"] = round(v["market_value"] / total_value * 100, 2) if total_value > 0 else 0

        return values
    finally:
        session.close()


@tool
def get_holding(ticker: str) -> dict:
    """获取单个标的的持仓详情。

    Args:
        ticker: 标的代码，如 AAPL, 600519, 0700.HK, BTC

    Returns:
        dict: 持仓详情，含 ticker, market, shares, cost_basis, position_type, current_price, pnl_pct
    """
    session = get_session()
    try:
        h = get_holding_by_ticker(session, ticker.upper())
        if not h:
            return {"error": f"未找到标的: {ticker}"}
        try:
            adapter = adapter_registry.get(h.market)
            price_data = adapter.get_price(h.ticker)
            current_price = price_data.get("price", 0) or 0
        except Exception:
            current_price = h.cost_basis
        pnl_pct = ((current_price - h.cost_basis) / h.cost_basis * 100) if h.cost_basis else 0
        return {
            "ticker": h.ticker,
            "market": h.market,
            "shares": h.shares,
            "cost_basis": h.cost_basis,
            "current_price": round(current_price, 2),
            "position_type": h.position_type,
            "pnl_pct": round(pnl_pct, 2),
            "holding_id": h.id,
        }
    finally:
        session.close()


# ── Market Data Tools ─────────────────────────────────────

@tool
def get_price(ticker: str, market: str) -> dict:
    """获取标的当前价格和日内变动。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO

    Returns:
        dict: 含 ticker, price, currency, change_pct, volume, timestamp
    """
    adapter = adapter_registry.get(market)
    return adapter.get_price(ticker)


@tool
def get_kline(ticker: str, market: str, period: str = "3mo") -> list[dict]:
    """获取标的历史K线数据。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO
        period: 时间周期 — 1mo, 3mo, 6mo, 1y, 5y

    Returns:
        list[dict]: K线数据列表，每项含 date, open, high, low, close, volume
    """
    adapter = adapter_registry.get(market)
    return adapter.get_kline(ticker, period)


@tool
def get_financials(ticker: str, market: str) -> dict:
    """获取标的最近财报数据，包括营收、EPS、PE、ROE等基本面指标。

    Args:
        ticker: 标的代码
        market: 市场代码 — US, CN, HK, 或 CRYPTO

    Returns:
        dict: 含 ticker, report_date, revenue, revenue_growth, eps, pe_ratio, pb_ratio, roe 等
    """
    adapter = adapter_registry.get(market)
    return adapter.get_financials(ticker)


@tool
def get_market_snapshot(market: str) -> dict:
    """获取市场大盘指数概览。

    Args:
        market: 市场代码 — US (S&P 500), CN (上证指数), HK (恒生指数), CRYPTO (总市值)

    Returns:
        dict: 含 index_name, current, change_pct 等
    """
    adapter = adapter_registry.get(market)
    return adapter.get_market_snapshot()


# ── News Tools ────────────────────────────────────────────

@tool
def search_ticker_news(ticker: str, days: int = 7) -> list[dict]:
    """搜索与某个标的相关的最近新闻。

    Args:
        ticker: 标的代码
        days: 搜索最近几天的新闻，默认7天

    Returns:
        list[dict]: 新闻列表，每项含 title, url, summary, published_at
    """
    return news_adapter.search_ticker_news(ticker, days)


@tool
def get_market_headlines() -> list[dict]:
    """获取最新的市场头条和要闻。

    Returns:
        list[dict]: 新闻列表，每项含 title, url, summary, published_at, author
    """
    headlines = news_adapter.get_headlines(10)
    latest = news_adapter.get_latest_news(10)
    seen = set()
    merged = []
    for item in headlines + latest:
        key = item.get("title", "")
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:15]


# ── Recommendation Tools ──────────────────────────────────

@tool
def get_recommendation_history(ticker: Optional[str] = None, limit: int = 20) -> list[dict]:
    """获取历史建议记录。

    Args:
        ticker: 可选，指定标的代码来过滤
        limit: 返回条数，默认20

    Returns:
        list[dict]: 历史建议列表
    """
    session = get_session()
    try:
        recs = db_get_rec_history(session, ticker=ticker, limit=limit)
        return [
            {
                "id": r.id,
                "ticker": r.ticker,
                "action": r.action,
                "reasoning": r.reasoning,
                "confidence": r.confidence,
                "urgency": r.urgency,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recs
        ]
    finally:
        session.close()


@tool
def save_recommendation(
    ticker: str,
    action: str,
    reasoning: str,
    confidence: float,
    urgency: str = "low",
    session_id: int = 0,
) -> dict:
    """保存一条投资建议到数据库。每次分析完成后调用此工具保存结论。

    Args:
        ticker: 标的代码
        action: 建议操作 — buy_add, reduce, hold, watch
        reasoning: 推理链条（2-4句话）
        confidence: 置信度 0.0-1.0
        urgency: 紧迫度 — low, medium, high
        session_id: agent会话ID（自动传入，无需手动填写）

    Returns:
        dict: 保存成功的确认信息
    """
    db_session = get_session()
    try:
        rec = create_recommendation(
            db_session, session_id=session_id,
            ticker=ticker, action=action, reasoning=reasoning,
            confidence=confidence, urgency=urgency,
        )
        return {
            "status": "saved",
            "recommendation_id": rec.id,
            "ticker": rec.ticker,
            "action": rec.action,
        }
    finally:
        db_session.close()


# ── Tool Collection ───────────────────────────────────────

ALL_TOOLS = [
    get_portfolio,
    get_holding,
    get_price,
    get_kline,
    get_financials,
    get_market_snapshot,
    search_ticker_news,
    get_market_headlines,
    get_recommendation_history,
    save_recommendation,
]
```

- [ ] **Step 2: Verify tools import and have proper signatures**

Run: `python -c "
from agent.tools import ALL_TOOLS
for t in ALL_TOOLS:
    print(f'  {t.name}: {t.description[:50]}...')
print(f'Total tools: {len(ALL_TOOLS)}')
"`

- [ ] **Step 3: Commit**

```bash
git add agent/tools.py
git commit -m "feat: LangChain tool definitions — 10 tools wrapping adapters and DB"
```

---

### Task 11: Agent session management

**Files:**
- Create: `agent/session.py`

- [ ] **Step 1: Write agent/session.py**

```python
"""Agent session management — tracks each agent activation and its tool calls."""

from datetime import datetime
from typing import Optional

from db.repository import (
    get_session, create_agent_session, end_agent_session,
    log_tool_call,
)


class AgentSessionManager:
    """Wraps a DB agent session. Records tool calls transparently."""

    def __init__(self, triggered_by: str, news_snapshot: Optional[dict] = None):
        self.triggered_by = triggered_by
        self.news_snapshot = news_snapshot
        self.session_id: Optional[int] = None
        self._tool_call_count = 0

    def start(self) -> int:
        db = get_session()
        try:
            s = create_agent_session(db, self.triggered_by, self.news_snapshot)
            self.session_id = s.id
            return self.session_id
        finally:
            db.close()

    def record_tool_call(self, tool_name: str, params: dict = None, result_summary: str = None):
        if not self.session_id:
            return
        self._tool_call_count += 1
        db = get_session()
        try:
            log_tool_call(db, self.session_id, tool_name, params, result_summary)
        finally:
            db.close()

    def finish(self):
        if self.session_id:
            db = get_session()
            try:
                end_agent_session(db, self.session_id)
            finally:
                db.close()

    def snapshot_news_for_context(self, news_items: list[dict]) -> str:
        """Format recent news into a context string for the agent prompt."""
        if not news_items:
            return "无最新相关新闻。"
        lines = []
        for item in news_items[:10]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            ts = item.get("published_at", "")
            lines.append(f"- [{ts}] {title}")
            if summary:
                lines.append(f"  摘要: {summary}")
        return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add agent/session.py
git commit -m "feat: agent session manager — tracks sessions and tool calls in DB"
```

---

### Task 12: LangGraph agent graph

**Files:**
- Create: `agent/graph.py`

- [ ] **Step 1: Write agent/graph.py**

```python
"""LangGraph state graph for the portfolio agent.

Defines the ReAct-style agent loop:
  agent_node (LLM reasoning + tool selection)
    → tool_node (execute tool)
    → agent_node (continue reasoning with tool result)
    → END

The graph terminates when the agent produces a final response
without calling additional tools.
"""

from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from config import config
from agent.system_prompt import SYSTEM_PROMPT
from agent.tools import ALL_TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: int
    triggered_by: str
    extra_context: str


def build_agent_graph() -> StateGraph:
    """Build and compile the LangGraph agent graph."""

    llm = ChatAnthropic(
        model=config.ANTHROPIC_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=4096,
    )

    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState) -> dict:
        """Agent reasoning node. Calls the LLM with tools bound."""
        messages = state["messages"]

        # Ensure system prompt is first
        has_system = any(isinstance(m, SystemMessage) for m in messages)
        if not has_system:
            prompt = SYSTEM_PROMPT
            extra = state.get("extra_context", "")
            if extra:
                prompt = prompt + "\n\n" + extra
            messages = [SystemMessage(content=prompt)] + list(messages)

        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(ALL_TOOLS)

    def should_continue(state: AgentState) -> str:
        """Decide whether to call tools or end."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    # Build graph
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# Singleton — compiled at import time
agent_graph = build_agent_graph()
```

- [ ] **Step 2: Verify graph compiles without errors**

Run: `python -c "from agent.graph import agent_graph; print('Graph compiled OK:', type(agent_graph).__name__)"`

- [ ] **Step 3: Commit**

```bash
git add agent/graph.py
git commit -m "feat: LangGraph ReAct agent graph with tool-calling loop"
```

---

### Task 13: Agent core (orchestrator)

**Files:**
- Create: `agent/core.py`

- [ ] **Step 1: Write agent/core.py**

```python
"""Agent core orchestrator — ties together session, graph, and tools."""

from datetime import datetime
from typing import Optional

from langchain_core.messages import HumanMessage

from agent.graph import agent_graph
from agent.session import AgentSessionManager
from agent.system_prompt import (
    AFTER_MARKET_PROMPT_EXTRA,
    NEWS_TRIGGER_PROMPT_EXTRA,
)
from adapters.news import news_adapter


def run_after_market_analysis(market: str) -> str:
    """Run the daily post-market analysis for a given market.

    Called by the scheduler after each market closes.
    Returns a summary string for logging/notifications.
    """
    session = AgentSessionManager(triggered_by="schedule")
    session.start()

    market_names = {"US": "美股", "CN": "A股", "HK": "港股", "CRYPTO": "加密货币"}
    market_name = market_names.get(market, market)

    context = AFTER_MARKET_PROMPT_EXTRA.format(market=market_name)
    message = HumanMessage(content=f"请对{market_name}市场的持仓进行盘后分析。")

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "schedule",
        "extra_context": context,
    })

    session.finish()

    last_msg = result["messages"][-1]
    return last_msg.content if hasattr(last_msg, "content") else str(last_msg)


def run_news_triggered_analysis(news_items: list[dict]) -> Optional[str]:
    """Run analysis triggered by hourly news polling.

    Only activates if news items appear relevant to holdings.
    Returns analysis text or None if no action needed.
    """
    if not news_items:
        return None

    session = AgentSessionManager(
        triggered_by="event",
        news_snapshot={"count": len(news_items), "sample": news_items[:5]},
    )
    session.start()

    summary = session.snapshot_news_for_context(news_items)
    context = NEWS_TRIGGER_PROMPT_EXTRA.format(news_summary=summary)
    message = HumanMessage(content="请查看最新新闻，判断是否有需要关注的持仓标的，并给出分析。")

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "event",
        "extra_context": context,
    })

    session.finish()

    last_msg = result["messages"][-1]
    return last_msg.content if hasattr(last_msg, "content") else str(last_msg)


def run_ad_hoc_query(question: str) -> str:
    """Run agent analysis for a user's ad-hoc question from the dashboard.

    Args:
        question: The user's free-text question

    Returns:
        Agent's response text
    """
    session = AgentSessionManager(triggered_by="manual")
    session.start()

    message = HumanMessage(content=question)

    result = agent_graph.invoke({
        "messages": [message],
        "session_id": session.session_id,
        "triggered_by": "manual",
        "extra_context": "",
    })

    session.finish()

    last_msg = result["messages"][-1]
    return last_msg.content if hasattr(last_msg, "content") else str(last_msg)


def poll_news_for_portfolio(tickers: list[str]) -> list[dict]:
    """Hourly news poll: search for each ticker, return all matching articles.

    Args:
        tickers: List of ticker symbols from the portfolio

    Returns:
        Combined list of news articles found
    """
    all_news = []
    seen = set()
    for ticker in tickers:
        articles = news_adapter.search_ticker_news(ticker, days=1)
        for a in articles:
            key = a.get("title", "")
            if key and key not in seen:
                seen.add(key)
                a["related_ticker"] = ticker
                all_news.append(a)
    return all_news
```

- [ ] **Step 2: Verify agent core imports**

Run: `python -c "from agent.core import run_after_market_analysis, run_ad_hoc_query, poll_news_for_portfolio; print('Agent core OK')"`

- [ ] **Step 3: Commit**

```bash
git add agent/core.py
git commit -m "feat: agent core orchestrator — after-market, news-triggered, ad-hoc analysis"
```

---

## Phase 4: Automation

### Task 14: Market calendar & triggers

**Files:**
- Create: `scheduler/__init__.py`
- Create: `scheduler/triggers.py`

- [ ] **Step 1: Write scheduler/triggers.py**

```python
"""Market trading calendar and timezone-aware trigger logic."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from config import config


def is_market_closed(market: str) -> bool:
    """Check if market just closed (within last 30 minutes).

    Used to determine when to fire post-market analysis.
    Crypto always returns True (24/7 market).
    """
    if market == "CRYPTO":
        current = datetime.now(ZoneInfo("Asia/Shanghai"))
        return current.hour == 21 and current.minute < 30

    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return False

    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)

    # Skip weekends
    if now.weekday() >= 5:
        return False

    close_hour = market_info["close_hour"]
    close_minute = market_info["close_minute"]

    return (
        now.hour == close_hour
        and close_minute <= now.minute < close_minute + 30
    )


def get_next_market_close(market: str) -> datetime | None:
    """Calculate the next market close time in local time.

    Returns None for markets without a defined schedule.
    """
    if market == "CRYPTO":
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now >= target:
            from datetime import timedelta
            target = target + timedelta(days=1)
        return target

    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return None

    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)

    close = now.replace(
        hour=market_info["close_hour"],
        minute=market_info["close_minute"],
        second=0, microsecond=0,
    )

    # If already past close, go to next weekday
    from datetime import timedelta
    if now >= close:
        close = close + timedelta(days=1)

    while close.weekday() >= 5:
        close = close + timedelta(days=1)

    return close


def is_trading_day(market: str) -> bool:
    """Check if today is a trading day for the given market."""
    if market == "CRYPTO":
        return True
    market_info = config.TRADING_MARKETS.get(market)
    if not market_info:
        return True
    tz = ZoneInfo(market_info["timezone"])
    now = datetime.now(tz)
    return now.weekday() < 5
```

- [ ] **Step 2: Commit**

```bash
git add scheduler/
git commit -m "feat: market calendar and trigger logic"
```

---

### Task 15: Scheduler jobs

**Files:**
- Create: `scheduler/jobs.py`

- [ ] **Step 1: Write scheduler/jobs.py**

```python
"""Scheduler job definitions — what runs when the scheduler fires."""

from datetime import datetime
import logging

from db.repository import get_session, get_all_holdings
from agent.core import (
    run_after_market_analysis,
    run_news_triggered_analysis,
    poll_news_for_portfolio,
)
from notifier.telegram import notify

logger = logging.getLogger(__name__)


def job_after_market_us():
    """美股盘后分析 — scheduled at 16:30 EST daily."""
    logger.info("Starting US after-market analysis...")
    try:
        result = run_after_market_analysis("US")
        logger.info(f"US analysis done: {result[:100]}...")
        notify(f"🇺🇸 美股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"US analysis failed: {e}")


def job_after_market_cn():
    """A股盘后分析 — scheduled at 15:30 CST daily."""
    logger.info("Starting CN after-market analysis...")
    try:
        result = run_after_market_analysis("CN")
        logger.info(f"CN analysis done: {result[:100]}...")
        notify(f"🇨🇳 A股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"CN analysis failed: {e}")


def job_after_market_hk():
    """港股盘后分析 — scheduled at 16:30 HKT daily."""
    logger.info("Starting HK after-market analysis...")
    try:
        result = run_after_market_analysis("HK")
        logger.info(f"HK analysis done: {result[:100]}...")
        notify(f"🇭🇰 港股盘后分析\n\n{result}")
    except Exception as e:
        logger.error(f"HK analysis failed: {e}")


def job_after_market_crypto():
    """Crypto daily analysis — scheduled at 21:00 CST daily."""
    logger.info("Starting crypto daily analysis...")
    try:
        result = run_after_market_analysis("CRYPTO")
        logger.info(f"Crypto analysis done: {result[:100]}...")
        notify(f"🪙 Crypto每日分析\n\n{result}")
    except Exception as e:
        logger.error(f"Crypto analysis failed: {e}")


def job_hourly_news_poll():
    """每小时新闻轮询 — scheduled every hour."""
    logger.info("Running hourly news poll...")
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        tickers = [h.ticker for h in holdings]
    finally:
        session.close()

    if not tickers:
        logger.info("No holdings, skipping news poll.")
        return

    try:
        news_items = poll_news_for_portfolio(tickers)
        logger.info(f"Found {len(news_items)} news items for {len(tickers)} tickers")

        if news_items:
            result = run_news_triggered_analysis(news_items)
            if result:
                notify(f"📰 新闻事件分析\n\n{result}")
            else:
                logger.info("No significant news impact detected.")
    except Exception as e:
        logger.error(f"News poll failed: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add scheduler/jobs.py
git commit -m "feat: scheduler jobs — after-market analysis and hourly news poll"
```

---

### Task 16: Scheduler configuration (APScheduler)

**Files:**
- Create: `scheduler/cron.py`

- [ ] **Step 1: Write scheduler/cron.py**

```python
"""APScheduler configuration — starts and manages all scheduled jobs."""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.jobs import (
    job_after_market_us,
    job_after_market_cn,
    job_after_market_hk,
    job_after_market_crypto,
    job_hourly_news_poll,
)

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    """Start the background scheduler with all jobs configured.

    Called once at application startup.
    """
    global _scheduler

    if _scheduler is not None:
        logger.warning("Scheduler already running.")
        return

    _scheduler = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1},
    )

    # After-market analysis for each market
    # US: 16:30 EST = 07:30 UTC (winter) or 07:30 UTC (summer ~ 16:30 EDT = 20:30 UTC)
    # Using local timezone-aware scheduling
    _scheduler.add_job(
        job_after_market_us,
        trigger=CronTrigger(hour=7, minute=30, timezone="Asia/Shanghai"),
        id="us_after_market",
        name="美股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_cn,
        trigger=CronTrigger(hour=15, minute=30, timezone="Asia/Shanghai"),
        id="cn_after_market",
        name="A股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_hk,
        trigger=CronTrigger(hour=16, minute=30, timezone="Asia/Hong_Kong"),
        id="hk_after_market",
        name="港股盘后分析",
    )

    _scheduler.add_job(
        job_after_market_crypto,
        trigger=CronTrigger(hour=21, minute=0, timezone="Asia/Shanghai"),
        id="crypto_daily",
        name="Crypto每日分析",
    )

    # Hourly news poll
    _scheduler.add_job(
        job_hourly_news_poll,
        trigger=CronTrigger(minute=0),
        id="hourly_news",
        name="每小时新闻轮询",
    )

    _scheduler.start()
    logger.info("Scheduler started with 5 jobs.")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped.")


def get_scheduler_status() -> list[dict]:
    """Return status of all scheduled jobs for the dashboard."""
    if not _scheduler:
        return []
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else "paused",
        })
    return jobs
```

- [ ] **Step 2: Verify scheduler imports**

Run: `python -c "from scheduler.cron import start_scheduler, stop_scheduler; print('Scheduler module OK')"`

- [ ] **Step 3: Commit**

```bash
git add scheduler/cron.py
git commit -m "feat: APScheduler configuration with 5 cron jobs"
```

---

### Task 17: Telegram notifier

**Files:**
- Create: `notifier/__init__.py`
- Create: `notifier/telegram.py`

- [ ] **Step 1: Write notifier/telegram.py**

```python
"""Telegram Bot notification sender."""

import logging
from datetime import datetime

from config import config

logger = logging.getLogger(__name__)

_initialized = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def notify(message: str):
    """Send a Telegram notification. No-op if Telegram is not configured.

    Args:
        message: Plain text or markdown message body
    """
    if not _initialized:
        logger.debug("Telegram not configured, skipping notification.")
        return

    try:
        import requests

        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
        else:
            logger.info("Telegram notification sent.")
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")


def send_welcome():
    """Send a startup notification."""
    notify(f"🤖 <b>Portfolio Agent 已启动</b>\n<code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>")


def send_urgent_recommendation(ticker: str, action: str, reasoning: str, confidence: float):
    """Send a high-urgency recommendation as a formatted Telegram message."""
    action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
    emoji = action_emoji.get(action, "ℹ️")

    msg = (
        f"{emoji} <b>建议操作</b>\n\n"
        f"<b>标的：</b>{ticker}\n"
        f"<b>建议：</b>{action}\n"
        f"<b>置信度：</b>{confidence:.0%}\n\n"
        f"<b>理由：</b>\n{reasoning}"
    )
    notify(msg)
```

- [ ] **Step 2: Verify notifier imports**

Run: `python -c "from notifier.telegram import notify; notify('test — this will only send if Telegram is configured'); print('Notifier OK')"`

- [ ] **Step 3: Commit**

```bash
git add notifier/
git commit -m "feat: Telegram bot notifier"
```

---

## Phase 5: Streamlit Dashboard

### Task 18: Streamlit entry point

**Files:**
- Create: `app/__init__.py`
- Create: `app/main.py`

- [ ] **Step 1: Write app/main.py**

```python
"""Streamlit entry point — initializes DB, adapters, scheduler, and serves pages."""

import sys
import logging
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from db.repository import init_db
from adapters.base import registry
from adapters.us_market import USMarketAdapter
from adapters.cn_market import CNMarketAdapter, HKMarketAdapter
from adapters.crypto import CryptoAdapter
from scheduler.cron import start_scheduler, stop_scheduler
from notifier.telegram import send_welcome

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def init():
    """Initialize all subsystems once at startup."""

    # DB
    init_db()
    logger.info("Database initialized.")

    # Adapters
    registry.register("US", USMarketAdapter())
    registry.register("CN", CNMarketAdapter())
    registry.register("HK", HKMarketAdapter())
    registry.register("CRYPTO", CryptoAdapter())
    logger.info(f"Adapters registered: {registry.markets}")

    # Scheduler
    start_scheduler()
    logger.info("Scheduler started.")

    # Notify
    send_welcome()


# ── Streamlit App ─────────────────────────────────────────

st.set_page_config(
    page_title="Portfolio Agent",
    page_icon="📊",
    layout="wide",
)

# Initialize once per session
if "initialized" not in st.session_state:
    init()
    st.session_state["initialized"] = True


# Navigation
pages = {
    "Dashboard": "app/pages/dashboard.py",
    "Holdings": "app/pages/holdings.py",
    "History": "app/pages/history.py",
}

st.sidebar.title("📊 Portfolio Agent")
st.sidebar.caption("AI-Powered Investment Assistant")

page = st.sidebar.radio("Navigation", list(pages.keys()), label_visibility="collapsed")

# Run selected page
page_path = pages[page]
with open(page_path) as f:
    exec(f.read())

# Cleanup on stop
import atexit
atexit.register(stop_scheduler)
```

- [ ] **Step 2: Commit**

```bash
git add app/main.py
git commit -m "feat: Streamlit entry point with init sequence and navigation"
```

---

### Task 19: UI components

**Files:**
- Create: `app/components/__init__.py`
- Create: `app/components/kpi_cards.py`
- Create: `app/components/holdings_table.py`
- Create: `app/components/recommendation_card.py`

- [ ] **Step 1: Write app/components/kpi_cards.py**

```python
import streamlit as st
from db.repository import get_session, get_all_holdings, get_pending_recommendations


def render_kpi_cards():
    """Render the top-row KPI metric cards."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        pending = get_pending_recommendations(session)
    finally:
        session.close()

    total_value = 0.0
    total_cost = 0.0
    for h in holdings:
        total_cost += h.shares * h.cost_basis
        total_value += h.shares * h.cost_basis  # will be updated with live prices later

    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost else 0

    cols = st.columns(4)
    with cols[0]:
        st.metric("Total Value", f"¥{total_value:,.0f}", delta=f"+¥{pnl:,.0f}" if pnl >= 0 else f"-¥{abs(pnl):,.0f}")
    with cols[1]:
        st.metric("Today's P&L", f"{pnl_pct:+.1f}%")
    with cols[2]:
        st.metric("Pending Recs", str(len(pending)) + (" ⚠️" if len(pending) > 0 else ""))
    with cols[3]:
        # Simple risk gauge based on pending recommendations
        high_urgency = [r for r in pending if r.urgency == "high"]
        risk = "⚠️ High" if high_urgency else ("Moderate" if pending else "✅ Low")
        st.metric("Risk Level", risk)
```

- [ ] **Step 2: Write app/components/holdings_table.py**

```python
import streamlit as st
import pandas as pd
from db.repository import get_session, get_all_holdings


def render_holdings_table():
    """Render the holdings data table grouped by position type."""
    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info("No holdings yet. Add your first position in the Holdings page.")
        return

    rows = []
    for h in holdings:
        pnl_pct = 0.0
        rows.append({
            "Ticker": h.ticker,
            "Market": h.market,
            "Type": "🔵 Core" if h.position_type == "core" else "🟠 Satellite",
            "Shares": h.shares,
            "Cost Basis": h.cost_basis,
            "P&L %": pnl_pct,
        })

    df = pd.DataFrame(rows)

    # Split by type
    core = df[df["Type"].str.contains("Core")]
    satellite = df[df["Type"].str.contains("Satellite")]

    st.subheader("🔵 Core Holdings")
    if not core.empty:
        st.dataframe(core.drop(columns=["Type"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No core holdings.")

    st.subheader("🟠 Satellite Holdings")
    if not satellite.empty:
        st.dataframe(satellite.drop(columns=["Type"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No satellite holdings.")
```

- [ ] **Step 3: Write app/components/recommendation_card.py**

```python
import streamlit as st
from db.repository import get_session, get_pending_recommendations, record_user_action


def render_recommendations():
    """Render the latest agent recommendations as cards with accept/dismiss buttons."""
    session = get_session()
    try:
        recommendations = get_pending_recommendations(session)
    finally:
        session.close()

    if not recommendations:
        st.info("No pending recommendations. Agent is monitoring your portfolio.")
        return

    action_colors = {
        "buy_add": "🟢",
        "reduce": "🔴",
        "hold": "🟡",
        "watch": "👀",
    }

    st.subheader("💡 Agent Recommendations")
    for rec in recommendations:
        emoji = action_colors.get(rec.action, "ℹ️")
        with st.container():
            cols = st.columns([1, 8, 1, 1])
            with cols[0]:
                st.markdown(f"### {emoji}")
            with cols[1]:
                st.markdown(f"**{rec.ticker}** — *{rec.action}*")
                st.caption(f"Confidence: {rec.confidence:.0%} | Urgency: {rec.urgency} | {rec.created_at.strftime('%Y-%m-%d %H:%M')}")
                st.write(rec.reasoning)
            with cols[2]:
                if st.button("✅ Accept", key=f"accept_{rec.id}"):
                    db = get_session()
                    try:
                        record_user_action(db, rec.id, "accept")
                    finally:
                        db.close()
                    st.rerun()
            with cols[3]:
                if st.button("❌ Dismiss", key=f"dismiss_{rec.id}"):
                    db = get_session()
                    try:
                        record_user_action(db, rec.id, "dismiss")
                    finally:
                        db.close()
                    st.rerun()
            st.divider()
```

- [ ] **Step 4: Commit**

```bash
git add app/components/
git commit -m "feat: UI components — KPI cards, holdings table, recommendation cards"
```

---

### Task 20: Dashboard page

**Files:**
- Create: `app/pages/__init__.py`
- Create: `app/pages/dashboard.py`

- [ ] **Step 1: Write app/pages/dashboard.py**

```python
"""Main dashboard — KPI overview, holdings, recommendations."""

import streamlit as st
from app.components.kpi_cards import render_kpi_cards
from app.components.holdings_table import render_holdings_table
from app.components.recommendation_card import render_recommendations

st.title("📊 Portfolio Dashboard")
st.caption("AI-powered investment portfolio management")

render_kpi_cards()

st.divider()

col_left, col_right = st.columns([3, 2])

with col_left:
    render_holdings_table()

with col_right:
    st.subheader("💬 Ask Agent")
    user_question = st.text_area("Question", placeholder="e.g., 现在该加仓什么？科技股风险大吗？", label_visibility="collapsed")
    if st.button("Send to Agent", type="primary"):
        if user_question:
            with st.spinner("Agent is thinking..."):
                from agent.core import run_ad_hoc_query
                response = run_ad_hoc_query(user_question)
                st.success("Agent response:")
                st.write(response)
        else:
            st.warning("Please enter a question.")

st.divider()

render_recommendations()
```

- [ ] **Step 2: Commit**

```bash
git add app/pages/dashboard.py
git commit -m "feat: dashboard page — KPIs, holdings, ask-agent, recommendations"
```

---

### Task 21: Holdings management page

**Files:**
- Create: `app/pages/holdings.py`

- [ ] **Step 1: Write app/pages/holdings.py**

```python
"""Holdings management — add, edit, delete positions."""

import streamlit as st
from db.repository import (
    get_session, get_all_holdings, create_holding,
    update_holding, delete_holding, create_transaction,
)

st.title("📋 Holdings Management")

tab_add, tab_edit, tab_history = st.tabs(["Add Position", "Edit / Delete", "Transaction History"])

# ── Add Position ──────────────────────────────────────────

with tab_add:
    st.subheader("➕ Add New Position")

    with st.form("add_holding_form"):
        col1, col2 = st.columns(2)
        with col1:
            ticker = st.text_input("Ticker Symbol", placeholder="e.g., AAPL, 600519, BTC")
            market = st.selectbox("Market", ["US", "CN", "HK", "CRYPTO"])
        with col2:
            shares = st.number_input("Shares / Quantity", min_value=0.0, step=1.0)
            cost_basis = st.number_input("Cost Basis (per share)", min_value=0.0, step=0.01)

        position_type = st.radio("Position Type", ["core", "satellite"], horizontal=True,
                                  help="核心仓=长期持有 | 卫星仓=短期交易")

        submitted = st.form_submit_button("Add Position", type="primary")
        if submitted:
            if not ticker or shares <= 0 or cost_basis <= 0:
                st.error("Please fill in all fields correctly.")
            else:
                session = get_session()
                try:
                    holding = create_holding(
                        session, ticker=ticker.upper(), market=market,
                        shares=shares, cost_basis=cost_basis,
                        position_type=position_type,
                    )
                    create_transaction(
                        session, holding.id, action="buy",
                        shares=shares, price=cost_basis,
                        notes="Initial position added.",
                    )
                    st.success(f"Added {ticker.upper()} — {shares} shares at {cost_basis}")
                finally:
                    session.close()

# ── Edit / Delete ─────────────────────────────────────────

with tab_edit:
    st.subheader("✏️ Edit or Delete Positions")

    session = get_session()
    try:
        holdings = get_all_holdings(session)
    finally:
        session.close()

    if not holdings:
        st.info("No holdings to edit.")
    else:
        for h in holdings:
            with st.expander(f"{h.ticker} — {h.shares} shares @ {h.cost_basis} ({h.position_type})"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_shares = st.number_input("Shares", value=float(h.shares), key=f"shares_{h.id}")
                with col2:
                    new_cost = st.number_input("Cost Basis", value=float(h.cost_basis), key=f"cost_{h.id}")
                with col3:
                    new_type = st.selectbox("Type", ["core", "satellite"],
                                            index=0 if h.position_type == "core" else 1,
                                            key=f"type_{h.id}")

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("💾 Update", key=f"update_{h.id}"):
                        session = get_session()
                        try:
                            update_holding(session, h.id,
                                           shares=new_shares, cost_basis=new_cost,
                                           position_type=new_type)
                            st.success(f"Updated {h.ticker}")
                            st.rerun()
                        finally:
                            session.close()
                with col_b:
                    if st.button("🗑️ Delete", key=f"delete_{h.id}", type="secondary"):
                        session = get_session()
                        try:
                            delete_holding(session, h.id)
                            st.success(f"Deleted {h.ticker}")
                            st.rerun()
                        finally:
                            session.close()

# ── Transaction History ───────────────────────────────────

with tab_history:
    st.subheader("📜 Transaction History")
    from db.repository import get_transactions_for_holding
    session = get_session()
    try:
        holdings = get_all_holdings(session)
        if not holdings:
            st.info("No transactions yet.")
        for h in holdings:
            txns = get_transactions_for_holding(session, h.id)
            if txns:
                st.caption(f"**{h.ticker}**")
                for t in txns:
                    st.text(f"  {t.date.strftime('%Y-%m-%d')} — {t.action}: {t.shares} shares @ {t.price}")
    finally:
        session.close()
```

- [ ] **Step 2: Commit**

```bash
git add app/pages/holdings.py
git commit -m "feat: holdings management page — add, edit, delete, transaction history"
```

---

### Task 22: History page

**Files:**
- Create: `app/pages/history.py`

- [ ] **Step 1: Write app/pages/history.py**

```python
"""History — past recommendations and decision audit trail."""

import streamlit as st
from db.repository import get_session, get_recommendation_history, get_pending_recommendations

st.title("📜 Decision History")
st.caption("Full audit trail of agent recommendations and your actions")

session = get_session()
try:
    all_recs = get_recommendation_history(session, limit=100)
finally:
    session.close()

if not all_recs:
    st.info("No recommendations yet. Agent will start analyzing once you add holdings.")
else:
    for rec in all_recs:
        action_emoji = {"buy_add": "🟢", "reduce": "🔴", "hold": "🟡", "watch": "👀"}
        emoji = action_emoji.get(rec.action, "ℹ️")

        status_color = {
            "pending": "orange",
            "acted": "green",
            "dismissed": "gray",
        }

        with st.container():
            cols = st.columns([1, 7])
            with cols[0]:
                st.markdown(f"### {emoji}")
            with cols[1]:
                st.markdown(
                    f"**{rec.ticker}** — `{rec.action}` | "
                    f"Confidence: {rec.confidence:.0%} | "
                    f"Urgency: :{status_color.get(rec.status, 'gray')}[{rec.urgency}] | "
                    f"Status: :{status_color.get(rec.status, 'gray')}[{rec.status}]"
                )
                st.caption(rec.created_at.strftime("%Y-%m-%d %H:%M"))
                st.write(rec.reasoning)
            st.divider()
```

- [ ] **Step 2: Commit**

```bash
git add app/pages/history.py
git commit -m "feat: history page — past recommendations with audit trail"
```

---

### Task 23: Integration test & launch script

**Files:**
- Create: `run.sh`

- [ ] **Step 1: Write run.sh**

```bash
#!/bin/bash
# Launch script for Portfolio Agent

set -e

cd "$(dirname "$0")"

echo "=================================="
echo "  📊 Portfolio Agent"
echo "=================================="

# Ensure .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copy .env.example to .env and fill in your keys."
    echo ""
    echo "Required: ANTHROPIC_API_KEY"
    echo "Optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    exit 1
fi

echo "🚀 Starting Streamlit..."
streamlit run app/main.py --server.port 8501
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x run.sh`

- [ ] **Step 3: Commit**

```bash
git add run.sh
git commit -m "feat: launch script and integration complete"
```

---

## Final Checklist

After all tasks are complete, verify:

- [ ] `pip install -r requirements.txt` succeeds
- [ ] `python -c "from config import config; print(config.DATABASE_URL)"` works
- [ ] `python -c "from db.models import Base; from db.repository import init_db; init_db(); print('DB OK')"` works
- [ ] `python -c "from adapters.us_market import USMarketAdapter; a=USMarketAdapter(); print(a.get_price('AAPL'))"` works
- [ ] `python -c "from adapters.news import news_adapter; print(len(news_adapter.get_headlines(3)))"` works
- [ ] `python -c "from agent.tools import ALL_TOOLS; print(len(ALL_TOOLS))"` returns 10
- [ ] `python -c "from agent.graph import agent_graph; print(type(agent_graph).__name__)"` works
- [ ] `python -c "from scheduler.cron import start_scheduler; print('Scheduler OK')"` works
- [ ] `streamlit run app/main.py` launches the dashboard on port 8501
