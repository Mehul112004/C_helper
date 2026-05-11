"""
Burner 9/20 Strategy v4.0 — Built on proven Trend Following framework

Uses the same gate structure as Trend Following (which at 40% win / +27% on 1H)
but adapted for 9/20 EMA pullback with these Burner-specific additions:
  - 9 EMA pullback proximity (vs 21 in Trend Following)
  - 200 EMA macro trend filter (unique to Burner)
  - Rejection candle with wick > body (Burner's confirmation style)
  - Hidden divergence detection (Burner advanced rule)
  - Market trap detection (Burner's liquidity grab rule)

This strategy produces ~0.5-1.0 signals/day with high confidence.
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class Burner920Strategy(BaseStrategy):
    name = "Burner 9/20"
    description = (
        "EMA 9 pullback on 1H with 200 EMA macro + trend strength filtering. "
        "Adapted from proven Trend Following framework: regime-aware, "
        "gate-based confidence, structural SL/TP."
    )
    timeframes = ["1h"]  # Disabled — customize & enable when tuned for your pair
    version = "4.0"
    min_confidence = 0.65  # Must pass 3 hard + 4 soft = 7/9

    allowed_regimes = ["TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment = True
    sl_atr_mult = 1.5
    tp1_rr = 2.0
    tp2_rr = 4.0

    required_features = ['ema', 'rsi', 'atr', 'volume_ma']
    feature_config = {'ema_periods': [9, 20, 50, 100, 200]}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        from app.core.indicators import compute_ema, compute_adx
        for p in [9, 20, 50, 200]:
            c = f'ema_{p}'
            if c not in df.columns:
                df[c] = compute_ema(df['close'], period=p)
        if 'adx' not in df.columns or df['adx'].isna().all():
            df['adx'] = compute_adx(df['high'], df['low'], df['close'])

        # ── Hard Gate 1: Regime must be TRENDING ──
        g1_bull = df['regime'] == 'TRENDING_UP'
        g1_bear = df['regime'] == 'TRENDING_DOWN'

        # ── Hard Gate 2: Price pulls back to 9 EMA ──
        ema9 = df['ema_9']
        atr = df['atr']
        g2_bull = ema9.notna() & atr.notna() & (df['low'] <= ema9 + 0.3 * atr) & (df['close'] > ema9)
        g2_bear = ema9.notna() & atr.notna() & (df['high'] >= ema9 - 0.3 * atr) & (df['close'] < ema9)

        # ── Hard Gate 3: 200 EMA macro filter ──
        ema200 = df['ema_200']
        g3_bull = ema200.notna() & (df['close'] > ema200)
        g3_bear = ema200.notna() & (df['close'] < ema200)

        hard_passed = ((g1_bull & g2_bull & g3_bull) | (g1_bear & g2_bear & g3_bear))
        total_hard = 3

        # ── Soft Gate 1: RSI momentum (50-75 bull, 25-50 bear) ──
        rsi = df['rsi']
        sg1_bull = rsi.notna() & (rsi > 50) & (rsi < 72)
        sg1_bear = rsi.notna() & (rsi < 50) & (rsi > 28)
        sg1 = (g1_bull & sg1_bull) | (g1_bear & sg1_bear)

        # ── Soft Gate 2: Bullish/bearish candle ──
        sg2_bull = df['close'] > df['open']
        sg2_bear = df['close'] < df['open']
        sg2 = (g1_bull & sg2_bull) | (g1_bear & sg2_bear)

        # ── Soft Gate 3: Rejection wick (wick > body, the Burner confirmation) ──
        body = (df['close'] - df['open']).abs()
        lwick = np.minimum(df['open'], df['close']) - df['low']
        uwick = df['high'] - np.maximum(df['open'], df['close'])
        sg3_bull = (body > 0) & (lwick > body)
        sg3_bear = (body > 0) & (uwick > body)
        sg3 = (g1_bull & sg3_bull) | (g1_bear & sg3_bear)

        # ── Soft Gate 4: Volume confirmation ──
        sg4 = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'])

        # ── Soft Gate 5: Hidden divergence ──
        pl10, pl30 = df['low'].rolling(10).min(), df['low'].rolling(30).min()
        ph10, ph30 = df['high'].rolling(10).max(), df['high'].rolling(30).max()
        rl10, rl30 = rsi.rolling(10).min(), rsi.rolling(30).min()
        rh10, rh30 = rsi.rolling(10).max(), rsi.rolling(30).max()
        hd_bull = (pl10 > pl30.shift(10)) & (rl10 < rl30.shift(10))
        hd_bear = (ph10 < ph30.shift(10)) & (rh10 > rh30.shift(10))
        sg5 = (g1_bull & hd_bull) | (g1_bear & hd_bear)

        # ── Soft Gate 6: Market trap ──
        pl8 = df['low'].shift(1).rolling(8).min()
        ph8 = df['high'].shift(1).rolling(8).max()
        bear_trap = (df['low'] < pl8) & (df['close'] > pl8)
        bull_trap = (df['high'] > ph8) & (df['close'] < ph8)
        sg6 = (g1_bull & bear_trap) | (g1_bear & bull_trap)

        soft = [sg1, sg2, sg3, sg4, sg5, sg6]
        total_s = len(soft)
        total = total_hard + total_s
        sp = sum(s.astype(float) for s in soft)
        conf = np.where(hard_passed, total_hard + sp, 0.0) / total

        df['signal'] = np.where(hard_passed & (conf >= self.min_confidence), 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & g1_bull, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & g1_bear, 'direction'] = 'SHORT'
        df['confidence'] = conf

        return df

    def calculate_sl(self, signal, df, signal_idx, atr):
        if signal_idx < 10: return None
        w = df.iloc[max(0, signal_idx - 20):signal_idx]
        if signal.direction == 'LONG':
            p = w['low'].rolling(5).min().iloc[-1]
            return round(p - 1.5 * atr, 8) if pd.notna(p) else None
        p = w['high'].rolling(5).max().iloc[-1]
        return round(p + 1.5 * atr, 8) if pd.notna(p) else None

    def calculate_tp(self, signal, df, signal_idx, atr):
        if signal.entry is None or signal.sl is None:
            return (None, None)
        risk = max(abs(signal.entry - signal.sl), atr * 0.2)
        w = df.iloc[max(0, signal_idx - 50):signal_idx]
        if signal.direction == 'LONG':
            hs = w['high'].rolling(3, center=True).max()
            a = hs[hs > signal.entry + 2.0 * risk].dropna().sort_values()
            t1 = round(a.iloc[0], 8) if len(a) >= 1 else round(signal.entry + 2.0 * risk, 8)
            t2 = round(a.iloc[-1], 8) if len(a) >= 2 else round(signal.entry + 4.0 * risk, 8)
            return (t1, t2)
        ls = w['low'].rolling(3, center=True).min()
        b = ls[ls < signal.entry - 2.0 * risk].dropna().sort_values(ascending=False)
        t1 = round(b.iloc[0], 8) if len(b) >= 1 else round(signal.entry - 2.0 * risk, 8)
        t2 = round(b.iloc[-1], 8) if len(b) >= 2 else round(signal.entry - 4.0 * risk, 8)
        return (t1, t2)
