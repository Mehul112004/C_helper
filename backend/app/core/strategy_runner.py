"""
Strategy Runner
Orchestrates running strategies against candle data and collecting SetupSignal results.
Used by both the live scanner (Phase 4) and the backtester (Phase 7).
"""

import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.data_utils import get_finalized_candles


class StrategyRunner:
    """
    Runs strategies against candle datasets and collects SetupSignal results.
    Handles exception safety, signal validation, and default SL/TP population.

    Two execution paths:
      - Legacy: run_single_scan() / scan_historical() — Candle-object based
      - Phase 2: run_single_scan_v2() / scan_historical_v2() — DataFrame based
    """

    # ── Legacy: Candle-object based ──

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

        MIN_HISTORY_CANDLES = 50
        start_idx = MIN_HISTORY_CANDLES

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

    # ── Phase 2: DataFrame-based ──

    @staticmethod
    def _df_row_to_candles(df: pd.DataFrame, lookback: int = 50) -> list[Candle]:
        """Convert the last N DataFrame rows to Candle objects for SL/TP calc."""
        window = df.iloc[-lookback:]
        return [Candle.from_df_row(row) for _, row in window.iterrows()]

    @staticmethod
    def _df_slice_to_candles(df: pd.DataFrame, start_idx: int, end_idx: int) -> list[Candle]:
        """Convert a slice of DataFrame rows to Candle objects."""
        window = df.iloc[start_idx: end_idx + 1]
        return [Candle.from_df_row(row) for _, row in window.iterrows()]

    @staticmethod
    def run_single_scan_v2(
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        min_confidence_override: Optional[float] = None,
    ) -> Optional[SetupSignal]:
        """
        Phase 2 execution path (live mode).
        Uses DataFrame-based pipeline with feature extraction.
        """
        from app.core.base_strategy import SetupSignal

        try:
            # 1. Fetch data
            lookback = strategy.get_required_lookback()
            df = get_finalized_candles(symbol, timeframe, limit=lookback)

            if len(df) < strategy.get_min_candles():
                return None

            # 2. Pre-process (adds feature columns)
            df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)

            # 3. Generate signals
            df = strategy.generate_signals(df)

            # 4. Extract last row
            last = df.iloc[-1]
            if last.get('signal', 0) != 1:
                return None

            confidence = last.get('confidence', 0)
            threshold = min_confidence_override or strategy.min_confidence
            if confidence < threshold:
                return None

            direction = last.get('direction', None)
            if direction not in ('LONG', 'SHORT'):
                return None

            entry = float(last['close'])
            atr_val = float(last['atr']) if 'atr' in df.columns and pd.notna(last.get('atr')) else 0.0

            # Convert last N rows to Candle objects for SL/TP calculators
            candles = StrategyRunner._df_row_to_candles(df, lookback=min(50, len(df)))

            signal = SetupSignal(
                strategy_name=strategy.name,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=round(float(confidence), 4),
                entry=entry,
            )

            if atr_val > 0:
                signal.sl = strategy.calculate_sl(signal, candles, atr_val)
                tp1, tp2 = strategy.calculate_tp(signal, candles, atr_val)
                signal.tp1 = tp1
                signal.tp2 = tp2

            return signal

        except Exception as e:
            print(f"[StrategyRunner v2] Error in {strategy.name}: {e}")
            return None

    @classmethod
    def scan_historical_v2(
        cls,
        strategies: list[BaseStrategy],
        symbol: str,
        timeframe: str,
        candle_df: pd.DataFrame,
        min_confidence_override: Optional[float] = None,
    ) -> list[SetupSignal]:
        """
        Phase 2 backtester path.

        Pre-processes the full DataFrame once per strategy, generates signals
        across all rows, then extracts SetupSignal objects for every row
        where signal == 1.
        """
        signals = []

        for strategy in strategies:
            if timeframe not in strategy.timeframes:
                continue

            try:
                df = candle_df.copy()
                df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)
                df = strategy.generate_signals(df)

                # Extract signals from all rows
                signal_rows = df[df['signal'] == 1]

                for idx, row in signal_rows.iterrows():
                    confidence = row.get('confidence', 0)
                    threshold = min_confidence_override or strategy.min_confidence
                    if confidence < threshold:
                        continue

                    direction = row.get('direction', None)
                    if direction not in ('LONG', 'SHORT'):
                        continue

                    entry = float(row['close'])
                    atr_val = float(row['atr']) if 'atr' in df.columns and pd.notna(row.get('atr')) else 0.0

                    # Convert label index to integer position
                    pos_idx = df.index.get_loc(idx)
                    window_start = max(0, pos_idx - 49)
                    candles = cls._df_slice_to_candles(df, window_start, pos_idx)

                    signal = SetupSignal(
                        strategy_name=strategy.name,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction=direction,
                        confidence=round(float(confidence), 4),
                        entry=entry,
                        timestamp=df.iloc[pos_idx]['open_time'],
                    )

                    if atr_val > 0:
                        signal.sl = strategy.calculate_sl(signal, candles, atr_val)
                        tp1, tp2 = strategy.calculate_tp(signal, candles, atr_val)
                        signal.tp1 = tp1
                        signal.tp2 = tp2

                    signals.append(signal)

            except Exception as e:
                print(f"[StrategyRunner v2 historical] Error in {strategy.name}: {e}")
                continue

        return signals
