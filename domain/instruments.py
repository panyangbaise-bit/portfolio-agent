"""Resolve CN namespaces without guessing across overlapping security codes."""


def resolve_cn_symbol(value: str) -> tuple[str, str]:
    """Explicit prefixes disambiguate stock, OTC fund, ETF and index symbols.

    Bare 000/001/002/003 codes overlap stocks, funds and indices. Never fall
    through to another asset class when a provider fails.
    """
    value = value.strip().lower()
    if ":" in value:
        kind, code = value.split(":", 1)
        if kind not in {"stock", "fund", "etf", "index"}:
            raise ValueError("CN prefix must be stock:, fund:, etf: or index:")
    else:
        code = value
        if code.startswith(("000", "001", "002", "003", "399")):
            raise ValueError(
                f"Ambiguous CN symbol {code}; specify index:{code}, stock:{code} "
                f"or fund:{code}. 科创50请用 index:000688。"
            )
        if code.startswith(("51", "56", "58", "15", "16")):
            kind = "etf"
        elif code.startswith("0"):
            kind = "fund"
        elif code.startswith(("60", "68", "30", "4", "8", "92")):
            kind = "stock"
        else:
            raise ValueError(f"Unknown CN asset type for {code}; use an explicit prefix")
    if not code.isdigit() or len(code) != 6:
        raise ValueError("CN symbols must contain a six-digit code")
    return kind, code
