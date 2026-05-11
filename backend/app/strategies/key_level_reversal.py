"""
Key Level Reversal Strategy v4.1 — High-Conviction 15m Reversals

Only fires on 15m timeframe where reversals at proven levels have
the best statistical edge. Gates are strict to ensure quality.

Requirements (6 gates, need ≥5 to fire):
  G1: Proven level — 4+ touches of this swing level in last 50 bars
  G2: Engulfing rejection — body > 2x prior body (decisive momentum shift)
  G3: RSI extreme — < 30 (bull) or > 70 (bear)
  G4: Volume spike — > 2x average (institutions stepping in)
  G5: Trend weakening — ADX declining over last 10 bars
  G6: Close beyond level — price holds the key level after rejection

Confidence = gates_passed / 6 (must reach 0.85 = 5+ gates)
"""

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy, SetupSignal


class KeyLevelReversalStrategy(BaseStrategy):
    name = "Key Level Reversal"
    description = (
        "15m high-conviction reversal at proven levels. "
        "4+ touches, engulfing 2x, RSI extreme, volume 2x, "
        "weakening trend, close beyond level."
    )
    timeframes = ["15m"]
    version = "4.2"
    min_confidence = 0.70

    allowed_regimes = ["RANGING", "CHOPPY", "TRENDING_UP", "TRENDING_DOWN"]
    require_htf_alignment = False  # Reversals are inherently counter-trend
    sl_atr_mult = 1.5
    tp1_rr = 2.0
    tp2_rr = 4.0

    required_features = ['rsi', 'atr', 'volume_ma']
    feature_config = {}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        from app.core.indicators import compute_adx
        if 'adx' not in df.columns or df['adx'].isna().all():
            df['adx'] = compute_adx(df['high'], df['low'], df['close'])

        cl, lo, hi, op, vo = df['close'], df['low'], df['high'], df['open'], df['volume']
        a, r, vm, ax = df['atr'], df['rsi'], df['volume_ma'], df['adx']

        ok = a.notna() & r.notna() & vm.notna()
        if not ok.any():
            return df

        # ═══ G1: Proven level — 4+ touches in last 50 bars ═══
        sh20 = hi.shift(1).rolling(20, min_periods=5).max()
        sl20 = lo.shift(1).rolling(20, min_periods=5).min()
        near_hi = (hi >= sh20 - 0.3 * a) & (hi <= sh20 + 0.3 * a)
        near_lo = (lo <= sl20 + 0.3 * a) & (lo >= sl20 - 0.3 * a)
        hit_c = near_hi.rolling(50, min_periods=1).sum()
        lit_c = near_lo.rolling(50, min_periods=1).sum()
        at_res = near_hi & (hit_c >= 4)
        at_sup = near_lo & (lit_c >= 4)
        g1 = at_res | at_sup

        # ═══ G2: Engulfing rejection — body > 2x prior body ═══
        body = (cl - op).abs()
        pb = body.shift(1)
        eng = (body > 0) & (pb > 0) & (body > pb * 2.0)
        cr = hi - lo
        g2l = eng & (cl > op) & (cr > 0) & ((cl - lo) / cr > 0.6)
        g2s = eng & (cl < op) & (cr > 0) & ((hi - cl) / cr > 0.6)
        g2 = (at_sup & g2l) | (at_res & g2s)

        # ═══ G3: RSI extreme ═══
        g3l = r < 30
        g3s = r > 70
        g3 = (at_sup & g2l & g3l) | (at_res & g2s & g3s)

        # ═══ G4: Volume spike > 2x average ═══
        g4 = vm.notna() & (vo > vm * 2.0)

        # ═══ G5: Trend weakening (ADX declining) ═══
        g5 = ax.notna() & (ax < ax.shift(10))

        # ═══ G6: Close beyond level ═══
        g6l = cl > sl20
        g6s = cl < sh20
        g6 = (at_sup & g6l) | (at_res & g6s)

        # Count gates
        c1 = g1.astype(float)
        c2 = pd.Series(0.0, index=df.index); c2[g2] = 1.0
        c3 = g3.astype(float)
        c4 = g4.astype(float)
        c5 = g5.astype(float)
        c6 = g6.astype(float)

        passed = c1 + c2 + c3 + c4 + c5 + c6
        conf = passed / 6.0

        df['signal'] = np.where(conf >= self.min_confidence, 1, 0)
        df['direction'] = None
        df.loc[(df['signal'] == 1) & at_sup, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & at_res, 'direction'] = 'SHORT'
        df['confidence'] = conf
        return df

    def calculate_sl(self, signal, df, signal_idx, atr):
        if signal_idx < 5: return None
        row = df.iloc[signal_idx]
        if signal.direction == 'LONG':
            return round(row['low'] - 1.0 * atr, 8)
        return round(row['high'] + 1.0 * atr, 8)

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
