"""
Breakout & Retest Strategy v3.0 — Gate-Based Engine

Detects break of structure (BOS) with successful retest as entry.
This is the "smart money" style entry:
  1. Price breaks a structural level (swing high/low or S/R zone)
  2. Pulls back to retest the broken level
  3. Shows rejection at the level (wick, engulfing)
  4. Continues in the breakout direction

Works in ALL regimes but strongest in CHOPPY→TRENDING transitions.
Replaces: SMC Structure Shift, SR Breakout.

Confidence = fraction of gates passed.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class BreakoutRetestStrategy(BaseStrategy):
    name = "Breakout & Retest"
    description = (
        "Break of structure with successful retest. "
        "Price breaks a key level, pulls back to retest it, "
        "shows rejection, and continues in breakout direction."
    )
    timeframes = ["4h"]  # Only 4h is profitable for breakouts
    version = "3.1"
    min_confidence = 0.55  # Standard threshold

    # Only fire in trending markets — breakouts in ranges are false breaks
    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment = True
    sl_atr_mult = 1.5
    tp1_rr = 2.0
    tp2_rr = 4.0

    required_features = ['ema', 'rsi', 'atr', 'volume_ma', 'choch']
    feature_config = {
        'ema_periods': [50],
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        # ── Gate 1 (HARD): Recent bullish or bearish structure break ──
        # A "break" = body close beyond prior 20-bar high (bull) or low (bear)
        rolling_high_20 = df['high'].rolling(20).max()
        rolling_low_20 = df['low'].rolling(20).min()

        # Break detected within last 5 bars
        broke_up = (
            (df['close'] > rolling_high_20.shift(1)) &
            (df['close'].shift(1) <= rolling_high_20.shift(2))
        )
        broke_down = (
            (df['close'] < rolling_low_20.shift(1)) &
            (df['close'].shift(1) >= rolling_low_20.shift(2))
        )

        # Recent break (within last 5 candles)
        recent_break_up = broke_up.rolling(5, min_periods=1).max().astype(bool)
        recent_break_down = broke_down.rolling(5, min_periods=1).max().astype(bool)

        gate_1 = recent_break_up | recent_break_down
        is_bull = recent_break_up

        # ── Gate 2 (HARD): Price must be retesting the broken level ──
        # Retest = price comes back to within 0.5 ATR of the broken level
        atr = df['atr']
        near_high = atr.notna() & (df['low'] <= rolling_high_20.shift(1) + 0.3 * atr)
        near_low = atr.notna() & (df['high'] >= rolling_low_20.shift(1) - 0.3 * atr)
        gate_2 = (recent_break_up & near_high) | (recent_break_down & near_low)

        # ── Gate 3 (HARD): Price must be rejecting from the retest ──
        # Bull retest rejection: wick below level, close back above
        g3_bull = (
            near_high & (df['low'] <= rolling_high_20.shift(1)) &
            (df['close'] > df['open'])  # Bullish close
        )
        g3_bear = (
            near_low & (df['high'] >= rolling_low_20.shift(1)) &
            (df['close'] < df['open'])  # Bearish close
        )
        gate_3 = g3_bull | g3_bear

        # Combine hard gates
        hard_passed = gate_1 & gate_2 & gate_3
        total_hard = 3

        # ── Soft Gate 1: Volume above average (institutional activity) ──
        sg1 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'] * 1.2)

        # ── Soft Gate 2: RSI confirms momentum ──
        sg2_bull = df['rsi'].notna() & (df['rsi'] > 40) & (df['rsi'] < 70) & (df['rsi'] > df['rsi'].shift(2))
        sg2_bear = df['rsi'].notna() & (df['rsi'] < 60) & (df['rsi'] > 30) & (df['rsi'] < df['rsi'].shift(2))
        sg2 = (is_bull & sg2_bull) | (~is_bull & sg2_bear)

        # ── Soft Gate 3: Strong rejection wick ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        sg3_bull = (body > 0) & (lower_wick > body * 1.0)
        sg3_bear = (body > 0) & (upper_wick > body * 1.0)
        sg3 = (is_bull & sg3_bull) | (~is_bull & sg3_bear)

        # ── Soft Gate 4: EMA50 alignment ──
        sg4_bull = df['ema_50'].notna() & (df['close'] > df['ema_50'])
        sg4_bear = df['ema_50'].notna() & (df['close'] < df['ema_50'])
        sg4 = (is_bull & sg4_bull) | (~is_bull & sg4_bear)

        soft_gates = [sg1, sg2, sg3, sg4]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & is_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & ~is_bull, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 10:
            return None
        window = df.iloc[max(0, signal_idx - 10):signal_idx + 1]
        if signal.direction == 'LONG':
            pivot = window['low'].min()
            return round(pivot - (1.5 * atr), 8)
        else:
            pivot = window['high'].max()
            return round(pivot + (1.5 * atr), 8)

    def calculate_tp(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> tuple:
        if signal.entry is None or signal.sl is None:
            return (None, None)
        risk = abs(signal.entry - signal.sl)
        if risk <= 0:
            risk = atr * 0.2

        lookback = df.iloc[max(0, signal_idx - 50):signal_idx + 1]
        if signal.direction == 'LONG':
            above = lookback['high'][lookback['high'] > signal.entry + (self.tp1_rr * risk)]
            above = above.sort_values()
            if len(above) >= 2:
                return (round(above.iloc[0], 8), round(above.iloc[-1], 8))
            return (round(signal.entry + self.tp1_rr * risk, 8),
                    round(signal.entry + self.tp2_rr * risk, 8))
        else:
            below = lookback['low'][lookback['low'] < signal.entry - (self.tp1_rr * risk)]
            below = below.sort_values(ascending=False)
            if len(below) >= 2:
                return (round(below.iloc[0], 8), round(below.iloc[-1], 8))
            return (round(signal.entry - self.tp1_rr * risk, 8),
                    round(signal.entry - self.tp2_rr * risk, 8))
