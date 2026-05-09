"""
Zone Manager
Central in-memory cache of ContextState per (symbol, strategy_name).
Provides fast zone proximity checks to skip evaluate_trigger() in no-man's-land.
"""

import threading
from typing import Optional

from app.core.base_strategy import ActiveZone, ContextState


class ZoneManager:
    """
    Thread-safe singleton cache for HTF context states.

    Used by the execution stream to quickly check whether price is near
    any known ActiveZone before calling evaluate_trigger().
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], ContextState] = {}

    def update(self, symbol: str, strategy_name: str, state: ContextState) -> None:
        key = (symbol, strategy_name)
        # Store a copy to prevent cross-symbol contamination from
        # shared singleton strategy instances.
        copy = ContextState(
            regime=state.regime,
            active_zones=list(state.active_zones),
            indicators_snapshot=dict(state.indicators_snapshot),
            last_updated=state.last_updated,
            htf_candle_count=state.htf_candle_count,
        )
        with self._lock:
            self._cache[key] = copy

    def get_context(self, symbol: str, strategy_name: str) -> Optional[ContextState]:
        key = (symbol, strategy_name)
        with self._lock:
            return self._cache.get(key)

    def get_active_zones(self, symbol: str, strategy_name: str) -> list:
        ctx = self.get_context(symbol, strategy_name)
        if ctx is None:
            return []
        return ctx.active_zones

    def is_price_near_zone(self, symbol: str, strategy_name: str, price: float) -> bool:
        if price <= 0:
            return False
        zones = self.get_active_zones(symbol, strategy_name)
        if not zones:
            return False
        threshold = price * 0.02
        for zone in zones:
            if zone.contains_price(price):
                return True
            if zone.distance_to(price) <= threshold:
                return True
        return False

    def invalidate_symbol(self, symbol: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._cache if k[0] == symbol]
            for k in keys_to_remove:
                del self._cache[k]


zone_manager = ZoneManager()
