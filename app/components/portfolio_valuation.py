"""Portfolio valuation in CNY, including realized gains from closed positions.

Per-row holdings P&L stays on the broker residual cost basis. These helpers
replay the trade ledger with average cost so total return does not drop a
position when it is sold to zero, and does not count a partial sale twice.
"""

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

_EPS = 1e-6


def position_pnl(holding, txns: Iterable, mark_price: float) -> dict:
    """Native-currency P&L for one holding.

    ``method`` is ``average`` when the ledger ends on the current share count,
    ``synthetic_open`` when an open holding has no trades, ``residual_close``
    when a closed holding has sells but no reconcilable buys, and
    ``residual_open`` when the share count was edited outside the ledger.
    """
    shares = float(getattr(holding, "shares", 0) or 0)
    cost = float(getattr(holding, "cost_basis", 0) or 0)
    status = (getattr(holding, "status", None) or "open").lower()
    ordered = _ordered(txns)
    mark = float(mark_price or 0)

    if not ordered:
        if status != "closed" and shares > _EPS:
            unrealized = shares * (mark - cost)
            return _leg(0.0, unrealized, shares * cost, True, "synthetic_open")
        return _leg(0.0, 0.0, 0.0, False, "empty")

    replay = _replay_average_cost(ordered)
    if replay["ok"] and _shares_match(replay["shares"], shares):
        unrealized = 0.0
        if replay["shares"] > _EPS:
            avg = replay["cost_pool"] / replay["shares"]
            unrealized = replay["shares"] * (mark - avg)
        return _leg(
            replay["realized"], unrealized, replay["buy_cash"], True, "average"
        )

    sells = [txn for txn in ordered if _action(txn) == "sell"]
    if shares <= _EPS or status == "closed":
        if not sells:
            return _leg(0.0, 0.0, 0.0, False, "empty")
        last = sells[-1]
        realized = float(last.shares) * (float(last.price) - cost)
        proceeds = sum(float(txn.shares) * float(txn.price) for txn in sells)
        invested = proceeds - realized
        if invested <= _EPS:
            invested = cost * float(last.shares)
        return _leg(realized, 0.0, invested, True, "residual_close")

    unrealized = shares * (mark - cost)
    return _leg(0.0, unrealized, shares * cost, False, "residual_open")


def calculate_portfolio_totals(
    holdings: list,
    prices: dict,
    cny_rates: Dict[str, float],
    transactions: Optional[list] = None,
) -> Optional[dict]:
    """CNY cost, market value, and total return for open and closed holdings.

    Returns ``None`` if a holding's market has no CNY conversion rate.
    ``pnl`` is realized plus unrealized. ``cost`` is cumulative buy cash.
    """
    grouped = _group_transactions(transactions or [])
    total_cost = 0.0
    total_market_value = 0.0
    realized = 0.0
    unrealized = 0.0
    has_live_data = False
    positions: List[dict] = []

    for holding in holdings:
        market = holding.market.upper()
        rate = cny_rates.get(market)
        if rate is None:
            return None

        price = prices.get((holding.market, holding.ticker))
        if price is None:
            price = prices.get((market, holding.ticker))
        live = price is not None
        if price is None:
            price = holding.cost_basis
        elif _is_open(holding):
            has_live_data = True

        holding_id = getattr(holding, "id", None)
        leg = position_pnl(holding, grouped.get(holding_id, []), float(price))
        realized_cny = leg["realized"] * rate
        unrealized_cny = leg["unrealized"] * rate
        invested_cny = leg["invested"] * rate
        realized += realized_cny
        unrealized += unrealized_cny
        total_cost += invested_cny
        if _is_open(holding):
            total_market_value += float(holding.shares or 0) * float(price) * rate

        positions.append({
            "holding_id": holding_id,
            "ticker": holding.ticker,
            "market": holding.market,
            "status": (getattr(holding, "status", None) or "open"),
            "method": leg["method"],
            "realized_pnl": round(leg["realized"], 2),
            "unrealized_pnl": round(leg["unrealized"], 2),
            "total_pnl": round(leg["total"], 2),
            "invested": round(leg["invested"], 2),
            "realized_pnl_cny": round(realized_cny, 2),
            "unrealized_pnl_cny": round(unrealized_cny, 2),
            "total_pnl_cny": round((leg["total"]) * rate, 2),
            "live_price": live,
        })

    pnl = realized + unrealized
    return {
        "cost": total_cost,
        "market_value": total_market_value,
        "pnl": pnl,
        "pnl_pct": pnl / total_cost * 100 if total_cost else 0.0,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "has_live_data": has_live_data,
        "positions": positions,
    }


def _leg(realized: float, unrealized: float, invested: float, reconciled: bool, method: str) -> dict:
    return {
        "realized": realized,
        "unrealized": unrealized,
        "total": realized + unrealized,
        "invested": invested,
        "reconciled": reconciled,
        "method": method,
    }


def _is_open(holding) -> bool:
    status = (getattr(holding, "status", None) or "open").lower()
    return status != "closed" and float(getattr(holding, "shares", 0) or 0) > _EPS


def _group_transactions(transactions: list) -> dict:
    grouped: Dict[Optional[int], list] = {}
    for txn in transactions:
        grouped.setdefault(getattr(txn, "holding_id", None), []).append(txn)
    return grouped


def _ordered(txns: Iterable) -> list:
    return sorted(list(txns), key=lambda txn: (_txn_time(txn), getattr(txn, "id", 0) or 0))


def _txn_time(txn) -> datetime:
    dt = getattr(txn, "date", None) or datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _action(txn) -> str:
    return (getattr(txn, "action", "") or "").lower().strip()


def _shares_match(left: float, right: float) -> bool:
    return abs(left - right) <= max(_EPS, 1e-4 * max(abs(left), abs(right), 1.0))


def _replay_average_cost(txns: list) -> dict:
    shares = 0.0
    cost_pool = 0.0
    realized = 0.0
    buy_cash = 0.0
    for txn in txns:
        qty = float(txn.shares or 0)
        price = float(txn.price or 0)
        if qty <= _EPS or price <= 0:
            return {"ok": False}
        action = _action(txn)
        if action == "buy":
            buy_cash += qty * price
            cost_pool += qty * price
            shares += qty
            continue
        if action != "sell":
            return {"ok": False}
        if qty > shares + 1e-4:
            return {"ok": False}
        avg = cost_pool / shares if shares > _EPS else 0.0
        realized += (price - avg) * qty
        cost_pool -= avg * qty
        shares -= qty
        if shares < _EPS:
            shares = 0.0
            cost_pool = 0.0
    return {
        "ok": True,
        "shares": shares,
        "cost_pool": cost_pool,
        "realized": realized,
        "buy_cash": buy_cash,
    }
