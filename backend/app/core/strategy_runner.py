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
        htf_candles: list[Candle] = None,
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
            signal = strategy.scan(symbol, timeframe, candles, indicators, sr_zones, htf_candles=htf_candles)

            if signal is None:
                return None

            # Apply minimum confidence filter
            threshold = min_confidence_override if min_confidence_override is not None else strategy.min_confidence
            if signal.confidence < threshold:
                return None

            # Populate defaults
            atr = indicators.atr_14 if indicators.atr_14 is not None else 0.0

            if signal.entry is None:
                signal.entry = candles[-1].close

            if signal.sl is None and atr > 0:
                signal.sl = strategy.calculate_sl(signal, candles, atr)

            if (signal.tp1 is None or signal.tp2 is None) and atr > 0:
                tp1, tp2 = strategy.calculate_tp(signal, candles, atr, sr_zones=sr_zones)
                if signal.tp1 is None:
                    signal.tp1 = tp1
                if signal.tp2 is None:
                    signal.tp2 = tp2

            return signal

        except Exception as e:
            print(f"[StrategyRunner] Error in {strategy.name}: {e}")
            return None

    @staticmethod
    def run_mtf_scan(
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        ltf_candles: list[Candle],
        ltf_indicators: Indicators,
        current_price: float,
        min_confidence_override: Optional[float] = None,
    ) -> Optional[SetupSignal]:
        """
        Execute a single MTF trigger evaluation with safety wrapping.

        Calls strategy.evaluate_trigger() (not scan()) so strategies that
        have been migrated to the MTF system use their cached HTF context.

        Same safety wrapping as run_single_scan():
        - Exception handling
        - Confidence filter
        - SL/TP default population
        - Tags context_tf / execution_tf on the signal

        Returns:
            A fully populated SetupSignal or None
        """
        try:
            signal = strategy.evaluate_trigger(
                symbol, timeframe, ltf_candles, ltf_indicators, current_price
            )

            if signal is None:
                return None

            threshold = min_confidence_override if min_confidence_override is not None else strategy.min_confidence
            if signal.confidence < threshold:
                return None

            signal.context_tf = signal.context_tf or strategy.context_tf
            signal.execution_tf = signal.execution_tf or strategy.execution_tf

            atr = ltf_indicators.atr_14 if ltf_indicators.atr_14 is not None else 0.0

            if signal.entry is None:
                signal.entry = current_price

            if signal.sl is None and atr > 0:
                signal.sl = strategy.calculate_sl(signal, ltf_candles, atr)

            if (signal.tp1 is None or signal.tp2 is None) and atr > 0:
                tp1, tp2 = strategy.calculate_tp(signal, ltf_candles, atr)
                if signal.tp1 is None:
                    signal.tp1 = tp1
                if signal.tp2 is None:
                    signal.tp2 = tp2

            return signal

        except Exception as e:
            print(f"[StrategyRunner] Error in MTF {strategy.name}: {e}")
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
        htf_candle_df: pd.DataFrame = None,
        htf_indicator_series: dict = None,
        htf_boundaries: set = None,
    ) -> list[SetupSignal]:
        """
        Walk through a historical candle dataset bar-by-bar, running all
        applicable strategies at each bar close. Returns all signals generated.

        Used for testing and backtesting.

        MTF support: When htf_candle_df, htf_indicator_series, and htf_boundaries
        are provided, HTF context is updated at each HTF candle boundary with
        lookahead prevention, and MTF strategies are routed through
        run_mtf_scan() (calls evaluate_trigger) instead of run_single_scan()
        (calls scan).

        Args:
            strategies: List of strategy instances to run
            symbol: Trading pair
            timeframe: Candle timeframe
            candle_df: DataFrame with OHLCV data sorted by open_time ascending
            indicator_series: Full indicator series dict from IndicatorService.compute_all()
            sr_zones: S/R zones for this symbol (applied uniformly to all bars)
            min_confidence_override: Optional per-session confidence threshold
            htf_candle_df: Optional HTF candle DataFrame for MTF context updates
            htf_indicator_series: Optional HTF indicator series for MTF context
            htf_boundaries: Optional set of LTF bar indices where HTF context should update

        Returns:
            List of all SetupSignal objects generated across the walk
        """
        signals = []

        # Convert DataFrame rows to Candle objects
        candle_objects = [Candle.from_df_row(row) for _, row in candle_df.iterrows()]

        # Build HTF candle objects and a LTF-index → HTF-index mapping for boundary lookups
        htf_candle_objects = None
        htf_close_map = {}
        if htf_candle_df is not None and htf_boundaries is not None:
            htf_candle_objects = [Candle.from_df_row(row) for _, row in htf_candle_df.iterrows()]
            htf_times = htf_candle_df['open_time'].values
            for boundary_idx in htf_boundaries:
                ltf_time = candle_df.iloc[boundary_idx]['open_time']
                for htf_idx, htf_time in enumerate(htf_times):
                    if htf_time == ltf_time and htf_idx > 0:
                        htf_close_map[boundary_idx] = htf_idx - 1
                        break

        MIN_HISTORY_CANDLES = 50
        start_idx = MIN_HISTORY_CANDLES

        for idx in range(start_idx, len(candle_objects)):
            # Build the candle window (last 50 candles up to and including idx)
            window_start = max(0, idx - 49)
            window = candle_objects[window_start: idx + 1]

            # Build indicators snapshot for this bar
            indicators = cls.prepare_indicators_snapshot(indicator_series, idx)

            # HTF context update at boundaries
            if htf_boundaries is not None and idx in htf_boundaries:
                for strategy in strategies:
                    if strategy.has_mtf_support() and htf_candle_objects is not None:
                        htf_candle_idx = htf_close_map.get(idx, -1)
                        if htf_candle_idx < 0:
                            continue
                        htf_window = htf_candle_objects[:htf_candle_idx + 1]
                        htf_indicators = cls.prepare_indicators_snapshot(
                            htf_indicator_series, htf_candle_idx
                        )
                        strategy.update_context(
                            symbol, htf_window, htf_indicators, sr_zones
                        )

            for strategy in strategies:
                # Skip strategies that don't operate on this timeframe
                if timeframe not in strategy.timeframes:
                    continue

                # Use MTF path only if context was actually updated (HTF data available).
                # When backtesting without HTF data (htf_boundaries is None), fall back
                # to the legacy scan() path so strategies still produce signals.
                ctx_available = (
                    htf_boundaries is not None
                    and strategy.has_mtf_support()
                    and strategy._context_state.last_updated is not None
                )

                if ctx_available:
                    signal = cls.run_mtf_scan(
                        strategy=strategy,
                        symbol=symbol,
                        timeframe=timeframe,
                        ltf_candles=window,
                        ltf_indicators=indicators,
                        current_price=candle_objects[idx].close,
                        min_confidence_override=min_confidence_override,
                    )
                else:
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
