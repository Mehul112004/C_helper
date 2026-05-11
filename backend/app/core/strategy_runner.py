"""
Strategy Runner v3.0

Orchestrates running strategies against candle data and collecting signals.
Unified DataFrame-based execution for all strategies.

Two modes:
  - Live: run_single_scan() — checks the latest candle for signals
  - Backtest: scan_historical() — walks through all bars collecting signals
"""

import pandas as pd
from typing import Optional, List

from app.core.base_strategy import BaseStrategy, SetupSignal


class StrategyRunner:
    """Executes strategies and collects SetupSignal results."""

    @staticmethod
    def run_single_scan(
        strategy: BaseStrategy,
        symbol: str,
        timeframe: str,
        min_confidence_override: Optional[float] = None,
    ) -> Optional[tuple]:
        """
        Live mode: Execute strategy on the latest candle data.
        Fetches candles from DB, pre-processes, runs generate_signals(),
        extracts the last bar's signal.

        Returns:
            Tuple of (SetupSignal, pre_processed_df) or (None, None).
            The DataFrame is returned for context serialization.
        """
        from app.core.data_utils import get_finalized_candles

        try:
            lookback = strategy.get_required_lookback()
            df = get_finalized_candles(symbol, timeframe, limit=lookback)

            if len(df) < strategy.get_min_candles():
                return None, None

            df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)
            df = strategy.generate_signals(df)

            last = df.iloc[-1]
            if last.get('signal', 0) != 1:
                return None, None

            confidence = last.get('confidence', 0)
            threshold = min_confidence_override or strategy.min_confidence
            if confidence < threshold:
                return None, None

            direction = last.get('direction', None)
            if direction not in ('LONG', 'SHORT'):
                return None, None

            # Entry at next bar's open (realistic) — for live, use current close
            # (the signal just fired, user can enter at market)
            entry = float(last['close'])
            atr_val = float(last['atr']) if 'atr' in df.columns and pd.notna(last.get('atr')) else 0.0

            signal_idx = len(df) - 1

            signal = SetupSignal(
                strategy_name=strategy.name,
                symbol=symbol,
                timeframe=timeframe,
                direction=direction,
                confidence=round(float(confidence), 4),
                entry=entry,
                regime=str(last.get('regime', 'UNKNOWN')),
            )

            if atr_val > 0 and signal_idx >= 5:
                signal.sl = strategy.calculate_sl(signal, df, signal_idx, atr_val)
                tp1, tp2 = strategy.calculate_tp(signal, df, signal_idx, atr_val)
                signal.tp1 = tp1
                signal.tp2 = tp2

            # Build notes from gates
            gates_passed = []
            gates_failed = []
            signal.gates_passed = gates_passed
            signal.gates_failed = gates_failed
            signal.notes = (
                f"{signal.direction} signal. "
                f"Confidence: {confidence:.0%}. "
                f"Regime: {signal.regime}."
            )

            return signal, df

        except Exception as e:
            print(f"[StrategyRunner] Error in {strategy.name}: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    @classmethod
    def scan_historical(
        cls,
        strategies: List[BaseStrategy],
        symbol: str,
        timeframe: str,
        candle_df: pd.DataFrame,
        sr_zones: list = None,
        min_confidence_override: Optional[float] = None,
    ) -> List[SetupSignal]:
        """
        Backtest mode: Walk through the full candle dataset, running each
        strategy once. Pre-processes the DataFrame, runs generate_signals()
        across ALL rows, and extracts SetupSignal objects for every row
        where signal == 1.

        All strategies use the new v3 framework (generate_signals + gate-based).
        """
        signals = []

        for strategy in strategies:
            if timeframe not in strategy.timeframes:
                continue

            try:
                df = candle_df.copy()
                df = strategy.pre_process(df, symbol=symbol, timeframe=timeframe)

                # Inject backtest-computed S/R zones if strategy uses them
                if sr_zones and 'sr' in strategy.required_features:
                    _inject_sr_zones(df, sr_zones)

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

                    # Find integer position of this row in the DataFrame
                    pos_idx = df.index.get_loc(idx)

                    # Entry at next bar's open (handled by BacktestEngine now)
                    # Here we set the signal's entry to the signal bar's close
                    # and BacktestEngine adjusts it to next bar's open
                    entry = float(row['close'])
                    atr_val = float(row['atr']) if 'atr' in df.columns and pd.notna(row.get('atr')) else 0.0

                    regime = str(row.get('regime', 'UNKNOWN'))
                    signal_time = df.iloc[pos_idx]['open_time']

                    signal = SetupSignal(
                        strategy_name=strategy.name,
                        symbol=symbol,
                        timeframe=timeframe,
                        direction=direction,
                        confidence=round(float(confidence), 4),
                        entry=entry,
                        timestamp=signal_time,
                        regime=regime,
                    )

                    if atr_val > 0 and pos_idx >= 5:
                        signal.sl = strategy.calculate_sl(signal, df, pos_idx, atr_val)
                        tp1, tp2 = strategy.calculate_tp(signal, df, pos_idx, atr_val)
                        signal.tp1 = tp1
                        signal.tp2 = tp2

                    if signal.sl is not None and signal.tp1 is not None:
                        signals.append(signal)

            except Exception as e:
                print(f"[StrategyRunner] Error in historical scan for {strategy.name}: {e}")
                import traceback
                traceback.print_exc()
                continue

        return signals


def _inject_sr_zones(df: pd.DataFrame, sr_zones: list, midpoint: int = None):
    """
    Inject pre-computed S/R zones as DataFrame columns (time-aware).

    Zones are only injected from the midpoint of the dataset onward
    to prevent lookahead bias (simulating "zones formed by this point").
    """
    if midpoint is None:
        midpoint = max(100, len(df) // 3)

    supports = [z for z in sr_zones if z.get('zone_type') in ('support', 'both')]
    resistances = [z for z in sr_zones if z.get('zone_type') in ('resistance', 'both')]

    best_support = max(supports, key=lambda z: z.get('strength_score', 0), default=None)
    best_resistance = max(resistances, key=lambda z: z.get('strength_score', 0), default=None)

    if best_support or best_resistance:
        df.loc[df.index[midpoint:], 'sr_active'] = True

    if best_support:
        df.loc[df.index[midpoint:], 'sr_support_upper'] = best_support.get('zone_upper', 0)
        df.loc[df.index[midpoint:], 'sr_support_lower'] = best_support.get('zone_lower', 0)
        df.loc[df.index[midpoint:], 'sr_support_strength'] = best_support.get('strength_score', 0)

    if best_resistance:
        df.loc[df.index[midpoint:], 'sr_resistance_upper'] = best_resistance.get('zone_upper', 0)
        df.loc[df.index[midpoint:], 'sr_resistance_lower'] = best_resistance.get('zone_lower', 0)
        df.loc[df.index[midpoint:], 'sr_resistance_strength'] = best_resistance.get('strength_score', 0)
