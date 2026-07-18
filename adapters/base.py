from abc import ABC, abstractmethod


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
