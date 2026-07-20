"""CN fund info — index map + get_fund_info (mocked akshare)."""

import pandas as pd
import pytest

from adapters.cn_index_map import resolve_csi_index_code
from adapters.cn_market import CNMarketAdapter


def test_resolve_semiconductor_materials_index():
    assert resolve_csi_index_code("中证半导体材料设备主题指数") == "931865"
    assert resolve_csi_index_code(
        "中证半导体材料设备主题指数收益率*95%+人民币活期存款税后利率*5%"
    ) == "931865"


def test_resolve_hs300():
    assert resolve_csi_index_code("沪深300") == "000300"


def test_resolve_unknown_returns_none():
    assert resolve_csi_index_code("不存在的指数XYZ") is None


def test_get_fund_info_020357_shape(monkeypatch):
    overview = pd.DataFrame([{
        "基金全称": "华夏中证半导体材料设备主题交易型开放式指数证券投资基金发起式联接基金",
        "基金简称": "华夏半导体材料设备ETF联接C",
        "基金代码": "020357（前端）",
        "基金类型": "指数型-股票",
        "发行日期": "2023年12月21日",
        "成立日期/规模": "2024年01月23日 / 0.113亿份",
        "净资产规模": "15.70亿元",
        "份额规模": "7.905亿份",
        "基金管理人": "华夏基金",
        "基金托管人": "中信建投",
        "基金经理人": "单宽之",
        "成立来分红": "每份累计0.00元（0次）",
        "管理费率": "0.50%（每年）",
        "托管费率": "0.10%（每年）",
        "销售服务费率": "0.30%（每年）",
        "最高认购费率": "0.00%（前端）",
        "最高申购费率": "0.00%（前端）",
        "最高赎回费率": "1.50%（前端）",
        "业绩比较基准": "中证半导体材料设备主题指数收益率*95%+人民币活期存款税后利率*5%",
        "跟踪标的": "中证半导体材料设备主题指数",
    }])
    fees = pd.DataFrame([
        {"费用类型": "其他费用", "条件或名称": "基金管理费", "费用": 0.5},
        {"费用类型": "其他费用", "条件或名称": "基金托管费", "费用": 0.1},
    ])
    alloc = pd.DataFrame([
        {"资产类型": "股票", "仓位占比": 4.01},
        {"资产类型": "其他", "仓位占比": 92.70},
    ])
    cons = pd.DataFrame([
        {"成分券代码": "002371", "成分券名称": "北方华创"},
        {"成分券代码": "688981", "成分券名称": "中芯国际"},
    ])

    monkeypatch.setattr("adapters.cn_market.ak.fund_overview_em", lambda symbol: overview)
    monkeypatch.setattr(
        "adapters.cn_market.ak.fund_individual_detail_info_xq",
        lambda symbol: fees,
    )
    monkeypatch.setattr(
        "adapters.cn_market.ak.fund_individual_detail_hold_xq",
        lambda symbol, date: alloc,
    )
    monkeypatch.setattr(
        "adapters.cn_market.ak.index_stock_cons_csindex",
        lambda symbol: cons if symbol == "931865" else pd.DataFrame(),
    )

    info = CNMarketAdapter().get_fund_info("020357", top_constituents=10)

    assert info["ticker"] == "020357"
    assert info["fund_kind"] == "etf_feeder"
    assert info["tracked_index"] == "中证半导体材料设备主题指数"
    assert info["tracked_index_code"] == "931865"
    assert info["company"] == "华夏基金"
    assert info["fees"]["基金管理费"] == 0.5
    assert info["asset_allocation"][0]["asset_type"] == "股票"
    assert info["constituents"][0]["code"] == "002371"
    assert info["constituents_source"] == "tracked_index"
    assert any("联接基金" in n for n in info["notes"])
