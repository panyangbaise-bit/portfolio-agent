"""Fast, read-only ledger queries shared by A2A and GPT Actions.

No live provider calls: values are explicitly ledger values, not live quotes.
"""

from datetime import date, datetime, timedelta, timezone

from db.models import Holding, Transaction
from db.repository import get_session
from domain.markets import MARKET_CURRENCIES

MARKETS = frozenset(MARKET_CURRENCIES)


def _integer(value, name, default, minimum, maximum):
    if value is None:
        return default
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValueError(f"{name} must be an integer")
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _time(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def read_query(operation, params=None):
    params = dict(params or {})
    allowed = {"ticker", "market", "limit", "offset"}
    if operation == "holdings":
        allowed.add("status")
    elif operation == "transactions":
        allowed.update({"start_date", "end_date", "action"})
    else:
        raise ValueError("Supported operations: holdings, transactions")
    if set(params) - allowed:
        raise ValueError("Unknown filters: " + ", ".join(sorted(set(params) - allowed)))
    for key, value in params.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"{key} must be a scalar value")
    limit = _integer(params.get("limit"), "limit", 25, 1, 100)
    offset = _integer(params.get("offset"), "offset", 0, 0, 1_000_000)
    market = str(params.get("market") or "").upper()
    ticker = str(params.get("ticker") or "").strip().upper()
    if market and market not in MARKETS:
        raise ValueError("market must be US, CN, HK or CRYPTO")
    if len(ticker) > 20:
        raise ValueError("ticker is too long")
    with get_session() as db:
        if operation == "holdings":
            query = db.query(Holding).filter(Holding.status != "archived")
            status = params.get("status") or "open"
            if status not in {"open", "closed", "all"}:
                raise ValueError("status must be open, closed or all")
            if status != "all":
                query = query.filter(Holding.status == status)
        else:
            query = (
                db.query(Transaction, Holding).join(Holding).filter(Holding.status != "archived")
            )
            action = params.get("action")
            if action:
                if action not in {"buy", "sell"}:
                    raise ValueError("action must be buy or sell")
                query = query.filter(Transaction.action == action)
            start, end = params.get("start_date"), params.get("end_date")
            try:
                start = date.fromisoformat(start) if start else None
                end = date.fromisoformat(end) if end else None
            except (TypeError, ValueError):
                raise ValueError("Dates must use YYYY-MM-DD") from None
            if start and end and start > end:
                raise ValueError("start_date must not be after end_date")
            if start:
                query = query.filter(
                    Transaction.date >= datetime.combine(start, datetime.min.time())
                )
            if end:
                if end == date.max:
                    raise ValueError("end_date is out of range")
                query = query.filter(
                    Transaction.date
                    < datetime.combine(end + timedelta(days=1), datetime.min.time())
                )
        if ticker:
            query = query.filter(Holding.ticker == ticker)
        if market:
            query = query.filter(Holding.market == market)
        total = query.count()
        query = (
            query.order_by(Holding.id)
            if operation == "holdings"
            else query.order_by(Transaction.date.desc(), Transaction.id.desc())
        )
        rows = query.offset(offset).limit(limit).all()
        if operation == "holdings":
            items = [
                {
                    "holding_id": h.id,
                    "ticker": h.ticker,
                    "name": h.name,
                    "market": h.market,
                    "currency": MARKET_CURRENCIES.get(h.market),
                    "shares": h.shares,
                    "cost_basis": h.cost_basis,
                    "position_type": h.position_type,
                    "status": h.status,
                    "updated_at": _time(h.updated_at),
                }
                for h in rows
            ]
        else:
            items = [
                {
                    "transaction_id": txn.id,
                    "holding_id": h.id,
                    "ticker": h.ticker,
                    "name": h.name,
                    "market": h.market,
                    "currency": MARKET_CURRENCIES.get(h.market),
                    "action": txn.action,
                    "shares": txn.shares,
                    "price": txn.price,
                    "amount": round(txn.shares * txn.price, 8),
                    "date": _time(txn.date),
                    "notes": (txn.notes or "")[:500],
                }
                for txn, h in rows
            ]
    return {
        "operation": operation,
        "source": "portfolio_ledger",
        "read_only": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(items) if offset + len(items) < total else None,
        "notes": "Ledger only; cost_basis is broker residual unit cost, not a live quote or total return. Amounts use each row's currency. Date filters are inclusive UTC calendar dates. Archived holdings are excluded.",
    }
