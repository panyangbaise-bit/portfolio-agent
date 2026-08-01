from pathlib import Path


def test_dashboard_auto_refreshes_only_kpi_fragment():
    source = Path("app/views/dashboard.py").read_text()

    assert "@st.fragment(run_every=60)" in source
    assert source.index("render_holdings_table(") > source.index(
        "render_live_kpi_snapshot()"
    )
