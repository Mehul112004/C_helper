"""
SMC Structure Shift Strategy (HTF — 1H / 4H)

Detects Change of Character (ChoCh) and Break of Structure (BOS) using
dynamically mapped swing highs and lows.

Key distinction:
  - BOS (trend continuation): Price breaks the most recent swing point
    in the direction of the existing trend with a body close.
  - ChoCh (trend reversal): Price breaks the most recent swing point
    *against* the prevailing trend direction with a body close.

Safeguards:
  - Only body closes count — wick-only piercings are treated as
    liquidity sweeps and are explicitly rejected.
  - Requires at least 2 prior swing points to establish a trend context
    before any signal can fire.
"""

from app.core.fractals import build_swing_map
from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class SMCStructureShiftStrategy(BaseStrategy):
    name = "SMC Structure Shift"
    description = (
        "Detects Change of Character (ChoCh) or Break of Structure (BOS) "
        "using dynamically mapped swing highs/lows. Only body closes count — "
        "wick sweeps are rejected."
    )
    timeframes = ["1h", "4h"]
    version = "1.0"
    min_confidence = 0.60

    LOOKBACK = 40
    PIVOT_BARS = 3    # Bars on each side for swing detection

    def _determine_trend(self, swings: list[dict]) -> str:
        """
        Determine prevailing trend from the last few swing points.
        Returns 'bullish', 'bearish', or 'neutral'.
        """
        if len(swings) < 4:
            return 'neutral'

        # Look at the last 4 swing points
        recent = swings[-4:]
        highs = [s for s in recent if s['type'] == 'high']
        lows = [s for s in recent if s['type'] == 'low']

        # Accelerating trends might only have one valid lower opposite swing point in the window
        # We ensure there are at least 2 highs + lows in total and the direction aligns
        if len(highs) + len(lows) >= 3:
            higher_highs = highs[-1]['price'] > highs[-2]['price'] if len(highs) >= 2 else True
            higher_lows = lows[-1]['price'] > lows[-2]['price'] if len(lows) >= 2 else True
            lower_highs = highs[-1]['price'] < highs[-2]['price'] if len(highs) >= 2 else True
            lower_lows = lows[-1]['price'] < lows[-2]['price'] if len(lows) >= 2 else True
            
            # Avoid cases where we assume True because len() < 2 but the existing ones contradict
            has_hh = len(highs) >= 2 and higher_highs
            has_hl = len(lows) >= 2 and higher_lows
            has_lh = len(highs) >= 2 and lower_highs
            has_ll = len(lows) >= 2 and lower_lows

            if (has_hh and higher_lows) or (higher_highs and has_hl):
                return 'bullish'
            elif (has_lh and lower_lows) or (lower_highs and has_ll):
                return 'bearish'

        return 'neutral'

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < self.LOOKBACK + self.PIVOT_BARS:
            return None

        window = candles[-(self.LOOKBACK + self.PIVOT_BARS):]
        current = candles[-1]
        swings = build_swing_map(window, self.PIVOT_BARS)

        if len(swings) < 4:
            return None

        trend = self._determine_trend(swings)
        if trend == 'neutral':
            return None

        # Find the most recent swing high and swing low
        last_swing_high = None
        last_swing_low = None
        for s in reversed(swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        if not last_swing_high or not last_swing_low:
            return None

        # --- Bullish BOS: Price body closes above the last swing high in a bullish trend ---
        if trend == 'bullish' and last_swing_high:
            level = last_swing_high['price']
            # Body close must be above (not just wick)
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998

            # Reject if only wick touched (body stayed below or equal)
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.65
                signal_type = "BOS"

                # +0.10 for volume confirmation
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2:
                    confidence += 0.10

                # +0.08 for strong body (low wick ratio)
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                # +0.07 for RSI momentum (not yet overbought)
                if indicators.rsi_14 and 50 < indicators.rsi_14 < 75:
                    confidence += 0.07

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    notes=(
                        f"Bullish {signal_type}: body closed above swing high at {level:.2f}. "
                        f"Trend: {trend}. Close: {current.close:.2f}."
                    ),
                )

        # --- Bearish BOS: Price body closes below the last swing low in a bearish trend ---
        if trend == 'bearish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002

            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.65
                signal_type = "BOS"

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2:
                    confidence += 0.10

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and 25 < indicators.rsi_14 < 50:
                    confidence += 0.07

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    notes=(
                        f"Bearish {signal_type}: body closed below swing low at {level:.2f}. "
                        f"Trend: {trend}. Close: {current.close:.2f}."
                    ),
                )

        # --- ChoCh: Reversal against prevailing trend ---
        # Bullish ChoCh: bearish trend, but price breaks last swing high
        if trend == 'bearish' and last_swing_high:
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.60  # Slightly lower — reversal is riskier

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                    confidence += 0.12

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and indicators.rsi_14 > 50:
                    confidence += 0.05

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    notes=(
                        f"Bullish ChoCh: body broke above swing high at {level:.2f} "
                        f"against prevailing bearish trend. Potential reversal."
                    ),
                )

        # Bearish ChoCh: bullish trend, but price breaks last swing low
        if trend == 'bullish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.60

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                    confidence += 0.12

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and indicators.rsi_14 < 50:
                    confidence += 0.05

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    notes=(
                        f"Bearish ChoCh: body broke below swing low at {level:.2f} "
                        f"against prevailing bullish trend. Potential reversal."
                    ),
                )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the recent swing point that caused the shift."""
        # Look back 20 candles to find the origin of the breakout impulse
        recent_history = candles[-20:]

        if signal.direction == "LONG":
            # SL goes below the lowest low of the structure forming the breakout
            structural_low = min(c.low for c in recent_history)
            return round(structural_low - (0.5 * atr), 8)
        else:
            # SL goes above the highest high of the structure forming the breakdown
            structural_high = max(c.high for c in recent_history)
            return round(structural_high + (0.5 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
        """Risk-based TP: 2.0R and 4.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.1)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (4.0 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (4.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
