"""
Key Level Reversal Strategy v3.0 — Gate-Based Engine

Detects high-probability reversals at key support/resistance levels:
  1. Price approaches a significant level (S/R zone, round number, prior swing)
  2. Shows strong rejection (long wick, engulfing candle, volume spike)
  3. Momentum shifts in reversal direction (RSI reversal)

Works in RANGING and CHOPPY regimes — catches the edges of ranges.
Replaces: RSI Reversal, SR Rejection, Fibonacci Retracement.

Confidence = fraction of gates passed.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class KeyLevelReversalStrategy(BaseStrategy):
    name = "Key Level Reversal"
    description = (
        "Reversal at key support/resistance levels with strong rejection. "
        "Price approaches a structural level, shows wick/engulfing rejection, "
        "and RSI confirms momentum shift."
    )
    timeframes = []  # Under development — too few signals to be useful yet
    version = "3.1"
    min_confidence = 0.60

    allowed_regimes = ["RANGING", "CHOPPY", "TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment = False
    sl_atr_mult = 1.5  # Wider SL to avoid being stopped out on retests
    tp1_rr = 2.0
    tp2_rr = 4.0

    required_features = ['ema', 'rsi', 'atr', 'volume_ma', 'sr', 'fvg']
    feature_config = {
        'ema_periods': [50],
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        # ── Gate 1 (HARD): Price at a key level ──
        # Key level = S/R zone, major EMA (50, 200), or round number proximity
        atr = df['atr']
        near_ema50 = atr.notna() & df['ema_50'].notna() & (
            (df['low'] <= df['ema_50']) & (df['high'] >= df['ema_50'])
        )

        # S/R zone proximity
        near_sr = pd.Series(False, index=df.index)
        if 'sr_active' in df.columns:
            has_support = df.get('sr_support_lower', pd.Series(np.nan)).notna()
            has_resistance = df.get('sr_resistance_upper', pd.Series(np.nan)).notna()
            near_sr_support = has_support & atr.notna() & (
                (df['low'] <= df['sr_support_upper']) &
                (df['low'] >= df['sr_support_lower'] - 0.3 * atr)
            )
            near_sr_resist = has_resistance & atr.notna() & (
                (df['high'] >= df['sr_resistance_lower']) &
                (df['high'] <= df['sr_resistance_upper'] + 0.3 * atr)
            )
            near_sr = near_sr_support | near_sr_resist

        gate_1 = near_ema50 | near_sr
        # Determine which direction to trade
        at_support = near_sr_support | (
            near_ema50 & (df['close'] < df['ema_50'])
        )
        at_resistance = near_sr_resist | (
            near_ema50 & (df['close'] > df['ema_50'])
        )

        # ── Gate 2 (HARD): Strong rejection candle ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        candle_range = df['high'] - df['low']
        range_ok = candle_range > 0

        # Bullish rejection at support: long lower wick (2x body), close in upper 40%
        g2_bull = (
            range_ok & (body > 0) &
            (lower_wick > body * 1.5) &  # Long lower wick (1.5x body)
            ((df['close'] - df['low']) / candle_range > 0.6)  # Close in upper 40%
        )
        # Bearish rejection at resistance
        g2_bear = (
            range_ok & (body > 0) &
            (upper_wick > body * 1.5) &
            ((df['high'] - df['close']) / candle_range > 0.6)
        )

        gate_2 = (at_support & g2_bull) | (at_resistance & g2_bear)

        # ── Gate 3 (HARD): Not against strong trend ──
        # Don't buy support in strong downtrend (adx >= 30, price below EMA50)
        strong_bear = df['adx'].notna() & (df['adx'] >= 30) & (df['close'] < df['ema_50'])
        strong_bull = df['adx'].notna() & (df['adx'] >= 30) & (df['close'] > df['ema_50'])
        g3_bull = ~strong_bear  # Don't buy into strong downtrend
        g3_bear = ~strong_bull  # Don't sell into strong uptrend
        gate_3 = (at_support & g3_bull) | (at_resistance & g3_bear)

        hard_passed = gate_1 & gate_2 & gate_3
        total_hard = 3

        # ── Soft Gate 1: Volume spike ──
        sg1 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'] * 1.3)

        # ── Soft Gate 2: RSI extreme ──
        sg2_bull = df['rsi'].notna() & (df['rsi'] < 40)
        sg2_bear = df['rsi'].notna() & (df['rsi'] > 60)
        sg2 = (at_support & sg2_bull) | (at_resistance & sg2_bear)

        # ── Soft Gate 3: Body strength (engulfing) ──
        avg_body = body.rolling(10).mean()
        sg3 = (avg_body > 0) & (body > avg_body * 1.5)

        # ── Soft Gate 4: FVG present (adds confluence) ──
        sg4 = df.get('fvg_active', pd.Series(False)).astype(bool)

        soft_gates = [sg1, sg2, sg3, sg4]
        total_soft = len(soft_gates)
        total_gates = total_hard + total_soft

        soft_passed = sum(sg.astype(float) for sg in soft_gates)
        confidence = np.where(hard_passed, (total_hard + soft_passed) / total_gates, 0.0)

        df['signal'] = np.where(hard_passed & (confidence >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & at_support, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & at_resistance, 'direction'] = 'SHORT'
        df['confidence'] = confidence

        return df

    def calculate_sl(self, signal: SetupSignal, df: pd.DataFrame,
                     signal_idx: int, atr: float) -> float:
        if signal_idx < 5:
            return None
        # Place SL beyond the rejection wick with wider buffer
        row = df.iloc[signal_idx]
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

        # TP at nearest opposing level (EMA50 or swing)
        if signal.direction == 'LONG':
            ema_target = df.iloc[signal_idx]['ema_50']
            if pd.notna(ema_target) and ema_target > signal.entry + (self.tp1_rr * risk):
                tp1 = round(ema_target, 8)
            else:
                tp1 = round(signal.entry + self.tp1_rr * risk, 8)
            tp2 = round(signal.entry + self.tp2_rr * risk, 8)
        else:
            ema_target = df.iloc[signal_idx]['ema_50']
            if pd.notna(ema_target) and ema_target < signal.entry - (self.tp1_rr * risk):
                tp1 = round(ema_target, 8)
            else:
                tp1 = round(signal.entry - self.tp1_rr * risk, 8)
            tp2 = round(signal.entry - self.tp2_rr * risk, 8)

        return (tp1, tp2)
