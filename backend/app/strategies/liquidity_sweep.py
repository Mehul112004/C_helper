"""
Liquidity Sweep Strategy v3.0 — Gate-Based Engine

Detects stop hunts (liquidity grabs) where smart money pushes price beyond
a key level to trigger stops, then reverses. Classic ICT "turtle soup" setup.

The setup:
  1. Price wicks below a clear swing low (bullish) or above swing high (bearish)
  2. Closes back inside the range (failed breakout = liquidity grab)
  3. Momentum shifts back (strong close, volume, RSI)

Works in ALL regimes but most effective when:
  - Market is ranging (sweeps at boundaries)
  - After a long trend run (sweeps at extremes before reversal)

Replaces: SMC Liquidity Sweep, Volume Climax.

Confidence = fraction of gates passed.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class LiquiditySweepStrategy(BaseStrategy):
    name = "Liquidity Sweep"
    description = (
        "Stop hunt detection — price wicks beyond a key level to trigger stops, "
        "then closes back inside, creating a trap. High-probability reversal setup."
    )
    timeframes = ["4h"]  # Only 4h shows profit; 1h bleed too much
    version = "3.1"
    min_confidence = 0.50  # Lower to get sufficient signals on 4h

    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "CHOPPY"]
    require_htf_alignment = False
    sl_atr_mult = 1.0
    tp1_rr = 1.5
    tp2_rr = 3.0

    required_features = ['ema', 'rsi', 'atr', 'volume_ma']
    feature_config = {
        'ema_periods': [50],
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        # ── Find swing highs and lows (trailing pivots, no lookahead) ──
        pivot_lookback = 10
        # Trailing window: max/min of LAST N bars (excluding current bar)
        rolling_high = df['high'].shift(1).rolling(pivot_lookback, min_periods=3).max()
        rolling_low = df['low'].shift(1).rolling(pivot_lookback, min_periods=3).min()

        # Current bar's high/low against prior pivot
        curr_high = df['high']
        curr_low = df['low']
        curr_close = df['close']

        # ── Gate 1 (HARD): Liquidity sweep pattern ──
        # Bullish sweep: wick goes below prior swing low, close recovers above it
        sweep_bull = (
            (curr_low < rolling_low) &  # Wick below prior pivot low
            (curr_close > rolling_low) &  # Close back above
            (rolling_low.notna())
        )
        # Bearish sweep: wick goes above prior swing high, close drops below it
        sweep_bear = (
            (curr_high > rolling_high) &  # Wick above prior pivot high
            (curr_close < rolling_high) &  # Close back below
            (rolling_high.notna())
        )
        gate_1 = sweep_bull | sweep_bear

        # ── Gate 2 (HARD): Close must be in the right half of the candle ──
        candle_range = df['high'] - df['low']
        g2_bull = (
            (candle_range > 0) &
            ((df['close'] - df['low']) / candle_range > 0.5)  # Close in upper half
        )
        g2_bear = (
            (candle_range > 0) &
            ((df['high'] - df['close']) / candle_range > 0.5)  # Close in lower half
        )
        gate_2 = (sweep_bull & g2_bull) | (sweep_bear & g2_bear)

        # ── Gate 3 (HARD): Volume above 0.8x MA ──
        gate_3 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'] * 0.8)

        hard_passed = gate_1 & gate_2 & gate_3
        total_hard = 3

        # ── Soft Gate 1: RSI extreme ──
        sg1_bull = df['rsi'].notna() & (df['rsi'] < 35)
        sg1_bear = df['rsi'].notna() & (df['rsi'] > 65)
        sg1 = (sweep_bull & sg1_bull) | (sweep_bear & sg1_bear)

        # ── Soft Gate 2: Strong body ──
        body = (df['close'] - df['open']).abs()
        avg_body = body.rolling(10).mean()
        sg2 = (avg_body > 0) & (body > avg_body * 1.5)

        # ── Soft Gate 3: Bullish/bearish candle color ──
        sg3_bull = df['close'] > df['open']
        sg3_bear = df['close'] < df['open']
        sg3 = (sweep_bull & sg3_bull) | (sweep_bear & sg3_bear)

        # ── Soft Gate 4: EMA50 alignment (higher probability) ──
        sg4_bull = df['ema_50'].notna() & (df['close'] > df['ema_50'])
        sg4_bear = df['ema_50'].notna() & (df['close'] < df['ema_50'])
        sg4 = (sweep_bull & sg4_bull) | (sweep_bear & sg4_bear)

        soft_gates = [sg1, sg2, sg3, sg4]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & sweep_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & sweep_bear, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 5:
            return None
        row = df.iloc[signal_idx]
        # SL beyond the wick extreme
        if signal.direction == 'LONG':
            return round(row['low'] - (0.5 * atr), 8)
        else:
            return round(row['high'] + (0.5 * atr), 8)

    def calculate_tp(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> tuple:
        if signal.entry is None or signal.sl is None:
            return (None, None)
        risk = abs(signal.entry - signal.sl)
        if risk <= 0:
            risk = atr * 0.2

        # TP at opposite swing or EMA50
        if signal.direction == 'LONG':
            lookback = df.iloc[max(0, signal_idx - 30):signal_idx + 1]
            highs = lookback['high'].sort_values()
            above = highs[highs > signal.entry + (self.tp1_rr * risk)]
            if len(above) >= 2:
                tp1 = round(above.iloc[0], 8)
                tp2 = round(above.iloc[-1], 8)
            else:
                tp1 = round(signal.entry + self.tp1_rr * risk, 8)
                tp2 = round(signal.entry + self.tp2_rr * risk, 8)
        else:
            lookback = df.iloc[max(0, signal_idx - 30):signal_idx + 1]
            lows = lookback['low'].sort_values(ascending=False)
            below = lows[lows < signal.entry - (self.tp1_rr * risk)]
            if len(below) >= 2:
                tp1 = round(below.iloc[0], 8)
                tp2 = round(below.iloc[-1], 8)
            else:
                tp1 = round(signal.entry - self.tp1_rr * risk, 8)
                tp2 = round(signal.entry - self.tp2_rr * risk, 8)

        return (tp1, tp2)
