"""Curated CSI / CN index name → code map for fund tracked-index lookup.

Names are matched with normalized substring containment (spaces/suffixes stripped).
"""

from typing import Optional

# Common thematic / broad indices used by A-share index funds and ETF feeders.
CSI_INDEX_NAME_TO_CODE = {
    "沪深300": "000300",
    "中证500": "000905",
    "中证1000": "000852",
    "中证2000": "932000",
    "上证50": "000016",
    "上证180": "000010",
    "创业板指": "399006",
    "科创50": "000688",
    "中证全指": "000985",
    "中证半导体材料设备主题指数": "931865",
    "中证半导体材料设备主题": "931865",
    "中证白酒": "399997",
    "中证医疗": "399989",
    "中证银行": "399986",
    "中证军工": "399967",
    "中证新能源": "399808",
}


def _normalize_index_name(name: str) -> str:
    s = (name or "").strip()
    for suffix in ("收益率", "指数收益率", "指数"):
        if s.endswith(suffix) and suffix != "指数":
            s = s[: -len(suffix)]
    s = s.replace(" ", "").replace("　", "")
    return s


def resolve_csi_index_code(tracked_index_name: Optional[str]) -> Optional[str]:
    """Resolve a Chinese index display name to a CSI index code."""
    if not tracked_index_name:
        return None
    norm = _normalize_index_name(tracked_index_name)
    if not norm:
        return None

    # Prefer longer keys so "中证半导体材料设备主题" beats "中证半导体".
    for key, code in sorted(
        CSI_INDEX_NAME_TO_CODE.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    ):
        key_n = _normalize_index_name(key)
        if key_n in norm or norm in key_n:
            return code
    return None
