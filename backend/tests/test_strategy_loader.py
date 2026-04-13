"""
Unit tests for the StrategyRegistry/Loader.
Tests verify strategy discovery, lookup, enable/disable, and filtering.
These tests do NOT require a database — they test the in-memory registry only.
"""

import pytest
from app.core.base_strategy import BaseStrategy
from app.core.strategy_loader import StrategyRegistry


class TestStrategyRegistry:
    """Tests for the StrategyRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry and load built-in strategies."""
        reg = StrategyRegistry()
        reg.load_builtin_strategies()
        return reg

    def test_load_discovers_all_6(self, registry):
        """Registry should find all 6 built-in strategies."""
        all_strategies = registry.get_all()
        assert len(all_strategies) == 6

        names = {s['name'] for s in all_strategies}
        expected = {
            "EMA Crossover",
            "RSI Reversal",
            "Bollinger Band Squeeze",
            "MACD Momentum",
            "S/R Zone Rejection",
            "S/R Zone Breakout",
        }
        assert names == expected

    def test_get_by_name(self, registry):
        """Can look up a strategy by its name."""
        strategy = registry.get_by_name("EMA Crossover")
        assert strategy is not None
        assert strategy.name == "EMA Crossover"
        assert isinstance(strategy, BaseStrategy)

    def test_get_by_name_not_found(self, registry):
        """Looking up a nonexistent strategy returns None."""
        assert registry.get_by_name("NonExistent") is None

    def test_all_strategies_are_enabled_by_default(self, registry):
        """All strategies should be enabled by default after loading."""
        all_strategies = registry.get_all()
        for s in all_strategies:
            assert s['enabled'] is True

    def test_enable_disable(self, registry):
        """Toggling a strategy updates its in-memory state."""
        assert registry.is_enabled("EMA Crossover") is True

        success = registry.set_enabled("EMA Crossover", False)
        assert success is True
        assert registry.is_enabled("EMA Crossover") is False

        success = registry.set_enabled("EMA Crossover", True)
        assert success is True
        assert registry.is_enabled("EMA Crossover") is True

    def test_enable_nonexistent_returns_false(self, registry):
        """Toggling a nonexistent strategy returns False."""
        assert registry.set_enabled("NonExistent", True) is False

    def test_get_enabled_filters(self, registry):
        """get_enabled() only returns strategies with enabled=True."""
        # Disable two strategies
        registry.set_enabled("EMA Crossover", False)
        registry.set_enabled("RSI Reversal", False)

        enabled = registry.get_enabled()
        enabled_names = {s.name for s in enabled}

        assert "EMA Crossover" not in enabled_names
        assert "RSI Reversal" not in enabled_names
        assert len(enabled) == 4

    def test_all_strategies_have_timeframes(self, registry):
        """Every strategy should declare at least one timeframe."""
        for s in registry.get_all():
            assert len(s['timeframes']) > 0, f"{s['name']} has no timeframes"

    def test_all_strategies_have_descriptions(self, registry):
        """Every strategy should have a non-empty description."""
        for s in registry.get_all():
            assert len(s['description']) > 0, f"{s['name']} has no description"

    def test_strategy_types_are_builtin(self, registry):
        """All loaded strategies should be marked as 'builtin'."""
        for s in registry.get_all():
            assert s['strategy_type'] == 'builtin'

    def test_min_confidence_defaults(self, registry):
        """All strategies should have a min_confidence value."""
        for s in registry.get_all():
            assert 0.0 <= s['min_confidence'] <= 1.0

    def test_set_min_confidence(self, registry):
        """Can update the min_confidence for a strategy."""
        strategy = registry.get_by_name("EMA Crossover")
        original = strategy.min_confidence

        success = registry.set_min_confidence("EMA Crossover", 0.8)
        assert success is True
        assert strategy.min_confidence == 0.8

        # Restore
        registry.set_min_confidence("EMA Crossover", original)

    def test_set_min_confidence_invalid_range(self, registry):
        """Setting min_confidence outside 0-1 should return False."""
        assert registry.set_min_confidence("EMA Crossover", 1.5) is False
        assert registry.set_min_confidence("EMA Crossover", -0.1) is False

    def test_set_min_confidence_nonexistent(self, registry):
        """Setting min_confidence for nonexistent strategy returns False."""
        assert registry.set_min_confidence("NonExistent", 0.5) is False
