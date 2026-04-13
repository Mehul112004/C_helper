"""
Strategy Runner
Orchestrates running strategies against candle data and collecting SetupSignal results.
Used by both the live scanner (Phase 4) and the backtester (Phase 7).
"""

import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class StrategyRunner:
    """
    Runs strategies against candle datasets and collects SetupSignal results.
    Handles exception safety, signal validation, and default SL/TP population.
    """

    @staticmethod
    def prepare_indicators_snapshot(
        series_dict: dict,
        idx: int,
    ) -> Indicators:
        """
        Build an Indicators dataclass from full indicator series at a specific candle index.

        Args:
            series_dict: Dict of indicator name → list of values (from IndicatorService
                         compute_all with include_series=True). Each entry is a list of
                         {time, value} dicts.
            idx: The candle index to extract values for.

        Returns:
            Indicators instance with current + previous bar values populated.
        """
        return Indicators.from_series(series_dict, idx)

    @staticmethod
    def run_single_scan(
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        candles: list[Candle],
        indicators: Indicators,
        sr_zones: list[dict],
        min_confidence_override: Optional[float] = None,
    ) -> Optional[SetupSignal]:
        """
        Execute a single strategy scan with safety wrapping.

        Wraps strategy.scan() with:
        - Exception handling (bad strategies don't crash the engine)
        - Signal validation (direction, confidence bounds)
        - Default SL/TP population if the strategy didn't provide them
        - Minimum confidence filtering

        Args:
            strategy: The strategy instance to run
            symbol: Trading pair
            timeframe: Candle timeframe
            candles: Recent candle history (most recent last)
            indicators: Current indicator snapshot
            sr_zones: S/R zones near current price
            min_confidence_override: If provided, overrides the strategy's min_confidence
                                     (used for per-session threshold configuration)

        Returns:
            A fully populated SetupSignal or None
        """
        try:
            signal = strategy.scan(symbol, timeframe, candles, indicators, sr_zones)

            if signal is None:
                return None

            # Validate signal
            if signal.direction not in ("LONG", "SHORT"):
                print(f"[StrategyRunner] Invalid direction from {strategy.name}: {signal.direction}")
                return None

            # Apply minimum confidence filter
            threshold = min_confidence_override if min_confidence_override is not None else strategy.min_confidence
            if signal.confidence < threshold:
                return None

            # Populate defaults
            atr = indicators.atr_14 or 0

            if signal.entry is None:
                signal.entry = candles[-1].close

            if signal.sl is None and atr > 0:
                signal.sl = strategy.calculate_sl(signal, candles, atr)

            if (signal.tp1 is None or signal.tp2 is None) and atr > 0:
                tp1, tp2 = strategy.calculate_tp(signal, candles, atr)
                if signal.tp1 is None:
                    signal.tp1 = tp1
                if signal.tp2 is None:
                    signal.tp2 = tp2

            return signal

        except Exception as e:
            print(f"[StrategyRunner] Error in {strategy.name}: {e}")
            return None

    @classmethod
    def scan_historical(
        cls,
        strategies: list[BaseStrategy],
        symbol: str,
        timeframe: str,
        candle_df: pd.DataFrame,
        indicator_series: dict,
        sr_zones: list[dict],
        min_confidence_override: Optional[float] = None,
    ) -> list[SetupSignal]:
        """
        Walk through a historical candle dataset bar-by-bar, running all
        applicable strategies at each bar close. Returns all signals generated.

        Used for testing and backtesting.

        Args:
            strategies: List of strategy instances to run
            symbol: Trading pair
            timeframe: Candle timeframe
            candle_df: DataFrame with OHLCV data sorted by open_time ascending
            indicator_series: Full indicator series dict from IndicatorService.compute_all()
            sr_zones: S/R zones for this symbol (applied uniformly to all bars)
            min_confidence_override: Optional per-session confidence threshold

        Returns:
            List of all SetupSignal objects generated across the walk
        """
        signals = []

        # Convert DataFrame rows to Candle objects
        candle_objects = [Candle.from_df_row(row) for _, row in candle_df.iterrows()]

        # Need at least 50 candles for strategies to have enough history
        start_idx = max(50, 0)

        for idx in range(start_idx, len(candle_objects)):
            # Build the candle window (last 50 candles up to and including idx)
            window_start = max(0, idx - 49)
            window = candle_objects[window_start: idx + 1]

            # Build indicators snapshot for this bar
            indicators = cls.prepare_indicators_snapshot(indicator_series, idx)

            for strategy in strategies:
                # Skip strategies that don't operate on this timeframe
                if timeframe not in strategy.timeframes:
                    continue

                signal = cls.run_single_scan(
                    strategy=strategy,
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=window,
                    indicators=indicators,
                    sr_zones=sr_zones,
                    min_confidence_override=min_confidence_override,
                )

                if signal:
                    # Override timestamp to the bar's time (not current wall time)
                    signal.timestamp = candle_objects[idx].open_time
                    signals.append(signal)

        return signals
