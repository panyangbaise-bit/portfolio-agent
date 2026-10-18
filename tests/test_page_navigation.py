"""Exercise actual page routing and reruns against an isolated empty ledger."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_all_pages_render_and_can_be_revisited(monkeypatch):
    from config import config
    from db.repository import engine, init_db
    from memory.indexer import initialize

    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr("runtime.start_services", lambda: None)
    init_db()
    initialize(engine)
    main = Path(__file__).resolve().parents[1] / "app/main.py"
    app = AppTest.from_file(str(main), default_timeout=15).run()
    assert not app.exception
    for page in (
        "holdings",
        "watchlist",
        "recommendations",
        "jobs",
        "history",
        "memory",
        "dashboard",
        "holdings",
    ):
        app.sidebar.radio(key="nav_page").set_value(page).run()
        assert not app.exception, f"Page {page} failed: {app.exception}"
        assert app.sidebar.radio(key="nav_page").value == page
