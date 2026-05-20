"""
EMA Cross Alert Strategy
Monitors EMA 9 and EMA 20 for imminent crossovers on 30m and 1h timeframes.
Sends direct Telegram alerts with RSI divergence, FVG/OB, and S/R zone context.
Bypasses the Watching/Confirmed pipeline — sends a simple direct message.
"""

import logging
import re
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

from app.core.base_strategy import BaseStrategy
from app.core.indicators import compute_ema, compute_rsi, compute_atr

logger = logging.getLogger(__name__)

_MD_SPECIAL = re.compile(r'([_*\[\]()~>#+\-=|{}.!])')


def _escape_md(text: str) -> str:
    return _MD_SPECIAL.sub(r'\\\1', str(text))


class EMACrossAlert(BaseStrategy):
    name = "EMA Cross Alert"
    description = (
        "Monitors EMA 9/20 for imminent crossovers on 30m/1h. "
        "Sends direct Telegram alerts with RSI divergence, FVG/OB, S/R context."
    )
    version = "1.0"
    timeframes = ["30m", "1h"]
    min_confidence = 0.0
    require_htf_alignment = False
    allowed_regimes = []
    required_features = ['rsi', 'fvg', 'ob', 'sr']
    run_on_live_candle = True

    _last_alert = {}
    _alert_cooldown_hours = 4

    def generate_signals(self, df):
        df = df.copy()
        df['signal'] = 0
        df['direction'] = None
        df['confidence'] = 0.0

        if len(df) < 50:
            return df

        symbol = df['symbol'].iloc[0] if 'symbol' in df.columns else 'UNKNOWN'
        timeframe = df['timeframe'].iloc[0] if 'timeframe' in df.columns else 'UNKNOWN'

        if 'ema_9' not in df.columns:
            df['ema_9'] = compute_ema(df['close'], 9)
        if 'ema_20' not in df.columns:
            df['ema_20'] = compute_ema(df['close'], 20)

        ema9 = df['ema_9']
        ema20 = df['ema_20']
        close = df['close']
        atr = df['atr'].fillna(df['close'] * 0.005)

        ema9_last = ema9.iloc[-1]
        ema20_last = ema20.iloc[-1]
        ema9_prev = ema9.iloc[-2]
        ema20_prev = ema20.iloc[-2]
        ema9_prev2 = ema9.iloc[-3]
        ema20_prev2 = ema20.iloc[-3]

        if pd.isna(ema9_last) or pd.isna(ema20_last):
            return df
        if pd.isna(ema9_prev) or pd.isna(ema20_prev):
            return df

        last_close = close.iloc[-1]
        last_atr = atr.iloc[-1]
        if pd.isna(last_atr) or last_atr <= 0:
            last_atr = last_close * 0.005

        dist = abs(ema9_last - ema20_last)
        dist_prev = abs(ema9_prev - ema20_prev)
        converging = dist < dist_prev
        near_threshold = max(0.08 * last_atr, last_close * 0.0003)
        near = dist < near_threshold

        if not (near and converging):
            return df

        dist_prev2 = abs(ema9_prev2 - ema20_prev2) if pd.notna(ema9_prev2) and pd.notna(ema20_prev2) else None
        if dist_prev2 is not None and not (dist < dist_prev <= dist_prev2):
            return df

        if ema9_last < ema20_last:
            direction = 'bullish'
        else:
            direction = 'bearish'

        now = datetime.now(timezone.utc)
        alert_key = (symbol, timeframe, direction)
        last_time = self._last_alert.get(alert_key)
        if last_time and (now - last_time).total_seconds() < self._alert_cooldown_hours * 3600:
            print(f"[EMA Cross Alert] Cooldown active for {symbol}/{timeframe} {direction} "
                  f"(last: {last_time.isoformat()})")
            return df

        print(f"[EMA Cross Alert] DETECTED {symbol}/{timeframe} {direction} "
              f"price={last_close:.4f} ema9={ema9_last:.4f} ema20={ema20_last:.4f} "
              f"dist={dist:.4f} threshold={near_threshold:.4f}")
        msg = self._build_message(df, symbol, timeframe, direction, last_close, last_atr,
                                  ema9_last, ema20_last, dist)
        sent = self._send_telegram(msg)
        if sent:
            self._last_alert[alert_key] = now

        return df

    def _build_message(self, df, symbol, timeframe, direction, price, atr_val,
                       ema9=None, ema20=None, ema_dist=None):
        direction_label = "Bullish" if direction == 'bullish' else "Bearish"
        emoji = "📈" if direction == 'bullish' else "📉"

        rsi_div = self._check_rsi_divergence(df, timeframe, direction)
        fvg_ob = self._check_fvg_ob_near(df, price, atr_val)
        sr_info = self._check_sr_near(df, price, atr_val)

        lines = [
            f"{emoji} *EMA Cross Alert*",
            "",
            f"*Pair*: {_escape_md(symbol)}",
            f"*Timeframe*: {_escape_md(timeframe)}",
            f"*Crossover*: {_escape_md(direction_label)} \\(EMA 9 {'↑' if direction == 'bullish' else '↓'} EMA 20\\)",
            f"*Price*: ${_escape_md(f'{price:,.4f}')}",
        ]
        if ema9 is not None and ema20 is not None:
            lines.append(
                f"*EMA 9*: ${_escape_md(f'{ema9:,.4f}')}  \\|  "
                f"*EMA 20*: ${_escape_md(f'{ema20:,.4f}')}  \\|  "
                f"*Diff*: ${_escape_md(f'{ema_dist:,.4f}')}"
            )
        lines += [
            "",
            f"*RSI Divergence \\(2d\\)*: {_escape_md(rsi_div)}",
            f"*FVG/OB near price*: {_escape_md(fvg_ob)}",
            f"*S/R zone near price*: {_escape_md(sr_info)}",
        ]
        return "\n".join(lines)

    def _check_rsi_divergence(self, df, timeframe, direction):
        if 'rsi' not in df.columns:
            return "RSI data unavailable"
        if 'low' not in df.columns or 'high' not in df.columns:
            return "Insufficient data"

        rsi = df['rsi']
        lookback = 96 if timeframe == '30m' else 48
        if len(df) < lookback + 30:
            return "Insufficient data"

        window = df.iloc[-lookback:]

        pl10 = window['low'].rolling(10).min()
        pl30 = window['low'].rolling(30).min()
        ph10 = window['high'].rolling(10).max()
        ph30 = window['high'].rolling(30).max()
        rl10 = window['rsi'].rolling(10).min()
        rl30 = window['rsi'].rolling(30).min()
        rh10 = window['rsi'].rolling(10).max()
        rh30 = window['rsi'].rolling(30).max()

        hd_bull = (pl10 > pl30.shift(10)) & (rl10 < rl30.shift(10))
        hd_bear = (ph10 < ph30.shift(10)) & (rh10 > rh30.shift(10))

        recent_bullish = hd_bull.tail(24).any()
        recent_bearish = hd_bear.tail(24).any()

        if recent_bullish:
            return "Bullish divergence detected"
        elif recent_bearish:
            return "Bearish divergence detected"
        return "None"

    def _check_fvg_ob_near(self, df, price, atr_val):
        near_range = 3.0 * atr_val
        findings = []

        last = df.iloc[-1]
        if last.get('fvg_active') and 'fvg_upper' in df.columns and 'fvg_lower' in df.columns:
            fvg_upper = last.get('fvg_upper')
            fvg_lower = last.get('fvg_lower')
            if pd.notna(fvg_upper) and pd.notna(fvg_lower):
                fvg_mid = (fvg_upper + fvg_lower) / 2
                dist = abs(price - fvg_mid)
                if dist < near_range:
                    side = "above" if price > fvg_upper else ("below" if price < fvg_lower else "inside")
                    findings.append(f"FVG ({side})")

        if last.get('ob_active') and 'ob_upper' in df.columns and 'ob_lower' in df.columns:
            ob_upper = last.get('ob_upper')
            ob_lower = last.get('ob_lower')
            if pd.notna(ob_upper) and pd.notna(ob_lower):
                ob_mid = (ob_upper + ob_lower) / 2
                dist = abs(price - ob_mid)
                if dist < near_range:
                    ob_dir = last.get('ob_direction', '')
                    side = "above" if price > ob_upper else ("below" if price < ob_lower else "inside")
                    findings.append(f"OB ({ob_dir})")

        return ", ".join(findings) if findings else "None"

    def _check_sr_near(self, df, price, atr_val):
        near_range = 3.0 * atr_val
        findings = []
        last = df.iloc[-1]

        has_sr = (
            'sr_active' in df.columns
            and 'sr_support_upper' in df.columns
            and 'sr_support_lower' in df.columns
            and 'sr_resistance_upper' in df.columns
            and 'sr_resistance_lower' in df.columns
        )
        if not has_sr:
            return "SR data unavailable"

        if last.get('sr_active') and pd.notna(last.get('sr_active')) and last['sr_active']:
            sup_upper = last.get('sr_support_upper')
            sup_lower = last.get('sr_support_lower')
            if pd.notna(sup_upper) and pd.notna(sup_lower):
                sup_mid = (sup_upper + sup_lower) / 2
                if abs(price - sup_mid) < near_range:
                    dist_pct = abs(price - sup_mid) / price * 100
                    direction_label = "above" if price > sup_upper else ("below" if price < sup_lower else "in")
                    findings.append(f"Support {direction_label} ({dist_pct:.1f}%)")

            res_upper = last.get('sr_resistance_upper')
            res_lower = last.get('sr_resistance_lower')
            if pd.notna(res_upper) and pd.notna(res_lower):
                res_mid = (res_upper + res_lower) / 2
                if abs(price - res_mid) < near_range:
                    dist_pct = abs(price - res_mid) / price * 100
                    direction_label = "above" if price > res_upper else ("below" if price < res_lower else "in")
                    findings.append(f"Resistance {direction_label} ({dist_pct:.1f}%)")

        return ", ".join(findings) if findings else "None"

    def _send_telegram(self, message):
        try:
            from app.core.telegram_client import telegram_client
            if telegram_client.is_configured():
                telegram_client.send_message(message)
                print(f"[EMA Cross Alert] Telegram sent successfully")
                return True
            else:
                print("[EMA Cross Alert] Telegram not configured, skipping alert")
                return False
        except Exception as e:
            print(f"[EMA Cross Alert] Failed to send Telegram: {e}")
            return False
