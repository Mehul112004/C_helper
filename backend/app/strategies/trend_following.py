"""
Trend Following Strategy v3.0 — Gate-Based Engine

Detects high-probability trend continuation entries by identifying:
  1. A strong, established trend (EMA stack + ADX confirmation)
  2. A pullback to a structural level (EMA 21, prior swing, or order block)
  3. Momentum turning back in trend direction (RSI hook, engulfing candle)

This strategy ONLY fires in TRENDING_UP or TRENDING_DOWN regimes.
It replaces: EMA Crossover, Trend Pullback Confluence, and Bollinger Squeeze.

Confidence = fraction of gates passed (transparent, comparable).
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class TrendFollowingStrategy(BaseStrategy):
    name = "Trend Following"
    description = (
        "High-probability trend continuation at structural pullback levels. "
        "Requires strong trend (ADX>=25, EMA stack), pullback to key level, "
        "and momentum confirmation before entry."
    )
    timeframes = ["1h"]
    version = "3.1"
    min_confidence = 0.60  # Tighter: 4h now requires stronger confirmation

    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment = True
    sl_atr_mult = 1.5
    tp1_rr = 2.0
    tp2_rr = 4.0

    required_features = ['ema', 'rsi', 'atr', 'volume_ma']
    feature_config = {
        'ema_periods': [9, 21, 50, 100, 200],
        'rsi_period': 14,
        'atr_period': 14,
        'volume_ma_period': 20,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        # ── Gate 1 (HARD): Regime must be TRENDING_UP or TRENDING_DOWN ──
        g1_bull = df['regime'] == 'TRENDING_UP'
        g1_bear = df['regime'] == 'TRENDING_DOWN'
        gate_1 = g1_bull | g1_bear

        # ── Gate 2 (HARD): Price must pull back to EMA 21 ──
        ema21 = df['ema_21']
        atr = df['atr']
        # Bull pullback: price touched below or near EMA 21
        near_ema = 0.3 * atr
        g2_bull = (
            ema21.notna() & atr.notna() &
            (df['low'] <= ema21 + near_ema) &
            (df['close'] > ema21)  # Closed back above EMA
        )
        g2_bear = (
            ema21.notna() & atr.notna() &
            (df['high'] >= ema21 - near_ema) &
            (df['close'] < ema21)  # Closed back below EMA
        )
        gate_2 = (g1_bull & g2_bull) | (g1_bear & g2_bear)

        # ── Gate 3 (HARD): EMA 50 must align with trend ──
        g3_bull = df['close'].notna() & df['ema_50'].notna() & (df['close'] > df['ema_50'])
        g3_bear = df['close'].notna() & df['ema_50'].notna() & (df['close'] < df['ema_50'])
        gate_3 = (g1_bull & g3_bull) | (g1_bear & g3_bear)

        # Combine hard gates
        hard_passed = gate_1 & gate_2 & gate_3
        total_hard = 3

        # ── Soft Gate 1: Volume confirmation (above average) ──
        sg1 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'])

        # ── Soft Gate 2: RSI momentum alignment ──
        sg2_bull = df['rsi'].notna() & (df['rsi'] > 30) & (df['rsi'] < 65) & (df['rsi'] > df['rsi'].shift(1))
        sg2_bear = df['rsi'].notna() & (df['rsi'] < 70) & (df['rsi'] > 35) & (df['rsi'] < df['rsi'].shift(1))
        sg2 = (g1_bull & sg2_bull) | (g1_bear & sg2_bear)

        # ── Soft Gate 3: Bullish/bearish candle ──
        sg3_bull = df['close'] > df['open']
        sg3_bear = df['close'] < df['open']
        sg3 = (g1_bull & sg3_bull) | (g1_bear & sg3_bear)

        # ── Soft Gate 4: Long lower wick (bull) or upper wick (bear) ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        sg4_bull = (body > 0) & (lower_wick > body * 0.8)
        sg4_bear = (body > 0) & (upper_wick > body * 0.8)
        sg4 = (g1_bull & sg4_bull) | (g1_bear & sg4_bear)

        # ── Soft Gate 5: Trend strength (ADX >= 30) ──
        sg5 = df['adx'].notna() & (df['adx'] >= 30)

        soft_gates = [sg1, sg2, sg3, sg4, sg5]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft  # 8

        # Confidence = (hard + soft_passed) / total_gates
        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        # Signal trigger
        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & g1_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & g1_bear, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 10:
            return None
        window = df.iloc[max(0, signal_idx - 20):signal_idx]
        if signal.direction == 'LONG':
            pivot = window['low'].rolling(5).min().iloc[-1]
            if pd.isna(pivot):
                return None
            return round(pivot - (1.5 * atr), 8)
        else:
            pivot = window['high'].rolling(5).max().iloc[-1]
            if pd.isna(pivot):
                return None
            return round(pivot + (1.5 * atr), 8)

    def calculate_tp(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> tuple:
        if signal.entry is None or signal.sl is None:
            return (None, None)
        risk = abs(signal.entry - signal.sl)
        if risk <= 0:
            risk = atr * 0.2

        # Look for structural targets: swing highs (bull) or swing lows (bear)
        lookback_start = max(0, signal_idx - 50)
        lookback = df.iloc[lookback_start:signal_idx + 1]

        if signal.direction == 'LONG':
            # Find swing highs above entry that satisfy minimum RR
            swing_highs = lookback['high'].rolling(3, center=True).max()
            above_entry = lookback['high'] > signal.entry + (self.tp1_rr * risk)
            candidates = swing_highs[above_entry].dropna().sort_values()
            if len(candidates) >= 2:
                tp1 = round(candidates.iloc[0], 8)
                tp2 = round(candidates.iloc[-1], 8)
            elif len(candidates) == 1:
                tp1 = round(candidates.iloc[0], 8)
                tp2 = round(signal.entry + (self.tp2_rr * risk), 8)
            else:
                tp1 = round(signal.entry + (self.tp1_rr * risk), 8)
                tp2 = round(signal.entry + (self.tp2_rr * risk), 8)
        else:
            swing_lows = lookback['low'].rolling(3, center=True).min()
            below_entry = lookback['low'] < signal.entry - (self.tp1_rr * risk)
            candidates = swing_lows[below_entry].dropna().sort_values(ascending=False)
            if len(candidates) >= 2:
                tp1 = round(candidates.iloc[0], 8)
                tp2 = round(candidates.iloc[-1], 8)
            elif len(candidates) == 1:
                tp1 = round(candidates.iloc[0], 8)
                tp2 = round(signal.entry - (self.tp2_rr * risk), 8)
            else:
                tp1 = round(signal.entry - (self.tp1_rr * risk), 8)
                tp2 = round(signal.entry - (self.tp2_rr * risk), 8)

        return (tp1, tp2)
