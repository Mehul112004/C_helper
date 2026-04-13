"""
Strategy Registry & Loader
Discovers, loads, and manages the lifecycle of all strategies.
- Discovers built-in strategies from the strategies/ directory on startup
- Syncs with the strategies DB table for enable/disable persistence
- Provides lookup and filtering APIs for the rest of the platform
"""

import importlib
import inspect
import json
import os
from pathlib import Path

from app.core.base_strategy import BaseStrategy


class StrategyRegistry:
    """
    Singleton registry that manages all available strategies.

    On startup:
    1. load_builtin_strategies() — scans app/strategies/ for BaseStrategy subclasses
    2. sync_with_db() — creates DB records for new strategies, loads enabled state for existing ones
    """

    def __init__(self):
        # Internal store: strategy_name → strategy instance
        self._strategies: dict[str, BaseStrategy] = {}
        # Track type: strategy_name → 'builtin' or 'custom'
        self._types: dict[str, str] = {}
        # Enabled state: strategy_name → bool
        self._enabled: dict[str, bool] = {}

    def load_builtin_strategies(self):
        """
        Scan the app/strategies/ directory, import all modules,
        find BaseStrategy subclasses, and register them.
        """
        strategies_dir = Path(__file__).parent.parent / 'strategies'

        if not strategies_dir.exists():
            print(f"[StrategyRegistry] Strategies directory not found: {strategies_dir}")
            return

        for filename in sorted(strategies_dir.iterdir()):
            if filename.suffix != '.py' or filename.name.startswith('_'):
                continue

            module_name = f"app.strategies.{filename.stem}"
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                print(f"[StrategyRegistry] Failed to import {module_name}: {e}")
                continue

            # Find all BaseStrategy subclasses in this module
            for attr_name, attr in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy
                    and not inspect.isabstract(attr)
                ):
                    try:
                        instance = attr()
                        self._strategies[instance.name] = instance
                        self._types[instance.name] = 'builtin'
                        self._enabled[instance.name] = True  # Default to enabled
                        print(f"[StrategyRegistry] Loaded built-in: {instance.name} "
                              f"({', '.join(instance.timeframes)})")
                    except Exception as e:
                        print(f"[StrategyRegistry] Failed to instantiate {attr_name}: {e}")

        print(f"[StrategyRegistry] {len(self._strategies)} strategies loaded.")

    def sync_with_db(self):
        """
        Sync the in-memory registry with the strategies DB table.
        - Creates DB records for strategies not yet in the table
        - Loads enabled state and min_confidence from DB for existing strategies
        """
        from app.models.db import db, Strategy

        for name, instance in self._strategies.items():
            existing = Strategy.query.filter_by(name=name).first()

            if existing:
                # Load persisted state
                self._enabled[name] = existing.enabled
                instance.min_confidence = existing.min_confidence
            else:
                # Create new DB record
                record = Strategy(
                    name=name,
                    description=instance.description,
                    strategy_type=self._types.get(name, 'builtin'),
                    timeframes=json.dumps(instance.timeframes),
                    enabled=True,
                    min_confidence=instance.min_confidence,
                )
                db.session.add(record)

        try:
            db.session.commit()
            print("[StrategyRegistry] DB sync complete.")
        except Exception as e:
            db.session.rollback()
            print(f"[StrategyRegistry] DB sync error: {e}")

    def get_all(self) -> list[dict]:
        """Return all registered strategies with metadata."""
        result = []
        for name, instance in self._strategies.items():
            result.append({
                'name': instance.name,
                'description': instance.description,
                'timeframes': instance.timeframes,
                'version': instance.version,
                'strategy_type': self._types.get(name, 'unknown'),
                'enabled': self._enabled.get(name, True),
                'min_confidence': instance.min_confidence,
            })
        return result

    def get_enabled(self) -> list[BaseStrategy]:
        """Return only currently enabled strategy instances."""
        return [
            instance for name, instance in self._strategies.items()
            if self._enabled.get(name, True)
        ]

    def get_by_name(self, name: str) -> BaseStrategy | None:
        """Look up a strategy by its name string."""
        return self._strategies.get(name)

    def is_enabled(self, name: str) -> bool:
        """Check if a strategy is currently enabled."""
        return self._enabled.get(name, False)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """
        Toggle a strategy on/off. Persists to DB.
        Returns True if the strategy was found and updated, False otherwise.
        """
        if name not in self._strategies:
            return False

        self._enabled[name] = enabled

        # Persist to DB
        try:
            from app.models.db import db, Strategy
            record = Strategy.query.filter_by(name=name).first()
            if record:
                record.enabled = enabled
                db.session.commit()
        except Exception as e:
            print(f"[StrategyRegistry] Error persisting enabled state: {e}")

        return True

    def set_min_confidence(self, name: str, min_confidence: float) -> bool:
        """
        Update the minimum confidence threshold for a strategy. Persists to DB.
        Returns True if the strategy was found and updated, False otherwise.
        """
        if name not in self._strategies:
            return False

        if not 0.0 <= min_confidence <= 1.0:
            return False

        self._strategies[name].min_confidence = min_confidence

        # Persist to DB
        try:
            from app.models.db import db, Strategy
            record = Strategy.query.filter_by(name=name).first()
            if record:
                record.min_confidence = min_confidence
                db.session.commit()
        except Exception as e:
            print(f"[StrategyRegistry] Error persisting min_confidence: {e}")

        return True


# Module-level singleton instance
registry = StrategyRegistry()
