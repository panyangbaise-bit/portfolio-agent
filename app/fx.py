"""Compatibility imports; FX provider access lives in adapters.fx."""

from adapters.fx import FX_RATES, get_cny_rates
from domain.markets import currency_for_market

__all__ = ["FX_RATES", "get_cny_rates", "currency_for_market"]
