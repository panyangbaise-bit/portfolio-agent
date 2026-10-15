from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

from db.models import Base
from db.repository import get_trading_discipline, save_trading_discipline


def test_rules_survive_new_sessions_and_can_be_updated_or_cleared():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert get_trading_discipline(db) is None
        save_trading_discipline(db, "  先止损，再开仓。\n避免冲动交易。  ")
    with Session(engine) as db:
        assert get_trading_discipline(db).content == "先止损，再开仓。\n避免冲动交易。"
        save_trading_discipline(db, "Updated rule")
    with Session(engine) as db:
        assert get_trading_discipline(db).content == "Updated rule"
        save_trading_discipline(db, "")
        assert get_trading_discipline(db).content == ""


def test_migration_adds_memo_table_to_existing_database():
    from db.migrate import migrate

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Base.metadata.tables["trading_discipline"].drop(engine)
    migrate(engine)
    migrate(engine)
    assert "trading_discipline" in inspect(engine).get_table_names()
    with Session(engine) as db:
        save_trading_discipline(db, "Persisted after migration")
        assert get_trading_discipline(db).content == "Persisted after migration"


def test_memo_ui_saves_and_restores_rules_on_new_page_session(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.components.trading_discipline.get_session", lambda: Session(engine))
    source = "from app.components.trading_discipline import render_trading_discipline\nrender_trading_discipline()"
    app = AppTest.from_string(source).run()
    assert not app.exception
    assert len(app.button) == 0
    app.text_area[0].set_value("每次开仓先确定止损。").run()
    assert not app.exception
    fresh = AppTest.from_string(source).run()
    assert fresh.text_area[0].value == "每次开仓先确定止损。"
