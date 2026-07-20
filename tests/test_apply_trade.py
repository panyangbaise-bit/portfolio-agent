"""apply_trade — weighted-average buys, sells, close/reopen."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Base
from db.repository import apply_trade, create_holding, get_open_holdings


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


def test_buy_weighted_average_cost(session):
    h = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    apply_trade(session, h.id, "buy", shares=10, price=120.0)
    session.refresh(h)
    assert h.shares == 20
    assert h.cost_basis == 110.0
    assert h.status == "open"


def test_sell_partial_broker_cost_rises_on_loss(session):
    """Sell below cost: remaining avg cost rises (broker-style)."""
    h = create_holding(session, "AAPL", "US", shares=300, cost_basis=65.217)
    apply_trade(session, h.id, "sell", shares=100, price=52.0)
    session.refresh(h)
    assert h.shares == 200
    assert round(h.cost_basis, 3) == 71.825
    assert h.status == "open"


def test_sell_partial_broker_cost_falls_on_gain(session):
    h = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    apply_trade(session, h.id, "sell", shares=4, price=130.0)
    session.refresh(h)
    assert h.shares == 6
    # (10*100 - 4*130) / 6 = 480/6 = 80
    assert h.cost_basis == 80.0
    assert h.status == "open"


def test_sell_to_closed(session):
    h = create_holding(session, "AAPL", "US", shares=10, cost_basis=100.0)
    apply_trade(session, h.id, "sell", shares=10, price=90.0)
    session.refresh(h)
    assert h.shares == 0.0
    assert h.status == "closed"
    assert get_open_holdings(session) == []


def test_reopen_closed_via_buy(session):
    h = create_holding(session, "AAPL", "US", shares=5, cost_basis=100.0)
    apply_trade(session, h.id, "sell", shares=5, price=90.0)
    apply_trade(session, h.id, "buy", shares=3, price=80.0)
    session.refresh(h)
    assert h.shares == 3
    assert h.cost_basis == 80.0
    assert h.status == "open"


def test_oversell_raises(session):
    h = create_holding(session, "AAPL", "US", shares=2, cost_basis=50.0)
    with pytest.raises(ValueError, match="Cannot sell"):
        apply_trade(session, h.id, "sell", shares=3, price=50.0)
