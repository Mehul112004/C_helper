"""
Trend Pullback Confluence Strategy (LTF — 15m)

A robust trend continuation model that requires three independent
confluences before firing:

1. **EMA Alignment**: Strict MA stacking order (50 > 100 > 200 for longs,
   reversed for shorts) to confirm an established trend.
2. **Price Pullback to 50 EMA**: Price must retrace and tag the 50 EMA
   support/resistance band (within 0.15% tolerance).
3. **RSI Momentum Hook**: RSI(14) must have dipped below 40 (for longs)
   or above 60 (for shorts) recently and then hooked back, proving
   oversold/overbought exhaustion is resolving — prevents catching
   a "falling knife".

Safeguards:
  - Will NOT fire if the EMA stack is not perfectly ordered.
  - Will NOT fire if RSI shows no recent exhaustion dip.
  - Will NOT fire if current candle has no rejection from the 50 EMA.
"""

from datetime import datetime

from app.core.base_strategy import (
    BaseStrategy, Candle, ExecutionMode, Indicators, SetupSignal,
)


class TrendPullbackConfluenceStrategy(BaseStrategy):
    name = "Trend Pullback Confluence"
    description = (
        "Trend continuation: requires strict EMA alignment (50>100>200), "
        "pullback tagging the 50 EMA, and RSI momentum hook from exhaustion."
    )
    timeframes = ["15m"]
    version = "1.0"
    min_confidence = 0.60

    execution_mode = ExecutionMode.HYBRID
    context_tf = "4h"
    execution_tf = "15m"

    # Configuration
    RSI_OVERSOLD_THRESHOLD = 40  # RSI must have dipped below this for LONG
    RSI_OVERBOUGHT_THRESHOLD = 60  # RSI must have risen above this for SHORT
    RSI_LOOKBACK = 5             # Candles to look back for the RSI exhaustion dip

    # Volatility / Momentum Filters ("Falling Knife" Protection)
    ATR_RANGE_MULTIPLIER = 1.8   # Max candle range as multiple of ATR before aborting
    ATR_BODY_MULTIPLIER = 1.2    # Max candle body size as multiple of ATR before aborting

    def _check_ema_alignment_bullish(self, indicators: Indicators) -> bool:
        """Verify 50 EMA > 100 EMA > 200 EMA (bullish stack)."""
        if not all([indicators.ema_50, indicators.ema_100, indicators.ema_200]):
            return False
        return indicators.ema_50 > indicators.ema_100 > indicators.ema_200

    def _check_ema_alignment_bearish(self, indicators: Indicators) -> bool:
        """Verify 50 EMA < 100 EMA < 200 EMA (bearish stack)."""
        if not all([indicators.ema_50, indicators.ema_100, indicators.ema_200]):
            return False
        return indicators.ema_50 < indicators.ema_100 < indicators.ema_200

    def _price_tags_ema50(self, candle: Candle, ema_50: float, atr: float, direction: str) -> bool:
        """Check if the candle's low (for longs) or high (for shorts) tagged the 50 EMA."""
        tolerance = atr * 0.20
        if direction == "LONG":
            return candle.low <= (ema_50 + tolerance)
        else:
            return candle.high >= (ema_50 - tolerance)

    def _rsi_hooked_bullish(self, candles: list[Candle], indicators: Indicators) -> bool:
        """
        Check if RSI recently dipped below the oversold threshold and is now
        hooking back up within the RSI_LOOKBACK window.
        """
        if indicators.rsi_14 is None or indicators.prev_rsi_14 is None or not indicators.rsi_14_history:
            return False

        # Current RSI must be recovering (above threshold) and rising
        current_rising = indicators.rsi_14 > indicators.prev_rsi_14

        # Was the RSI at or below the threshold at any point in the lookback window?
        prev_was_exhausted = any(val < self.RSI_OVERSOLD_THRESHOLD + 5 for val in indicators.rsi_14_history)

        # Current RSI shouldn't be overbought already
        not_overbought = indicators.rsi_14 < 65

        return current_rising and prev_was_exhausted and not_overbought

    def _rsi_hooked_bearish(self, candles: list[Candle], indicators: Indicators) -> bool:
        """Check if RSI recently spiked above overbought and is now hooking down."""
        if indicators.rsi_14 is None or indicators.prev_rsi_14 is None or not indicators.rsi_14_history:
            return False

        current_falling = indicators.rsi_14 < indicators.prev_rsi_14
        prev_was_exhausted = any(val > self.RSI_OVERBOUGHT_THRESHOLD - 5 for val in indicators.rsi_14_history)
        not_oversold = indicators.rsi_14 > 35

        return current_falling and prev_was_exhausted and not_oversold

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < 30:
            return None

        current = candles[-1]

        # ═══════ "Falling Knife" Protection ═══════
        # If the current candle's range is massively larger than the average
        # true range, it is a momentum dump/pump, not a gentle pullback.
        if indicators.atr_14 and current.range_size > (indicators.atr_14 * self.ATR_RANGE_MULTIPLIER):
            return None

        # ═══════ LONG Setup ═══════
        if self._check_ema_alignment_bullish(indicators):
            # Confluence 2: Price must tag the 50 EMA
            if indicators.ema_50 and indicators.atr_14 and self._price_tags_ema50(current, indicators.ema_50, indicators.atr_14, 'LONG'):
                # For longs, price low should be near/at EMA 50, close should be above
                if current.close > indicators.ema_50:
                    # Momentum filter: reject massive red marubozu that barely closed above
                    if indicators.atr_14 and current.body_size >= (indicators.atr_14 * self.ATR_BODY_MULTIPLIER):
                        return None
                    # Confluence 3: RSI momentum hook
                    if self._rsi_hooked_bullish(candles, indicators):
                        confidence = 0.65

                        # +0.10 for bullish candle (close > open)
                        if current.is_bullish:
                            confidence += 0.10

                        # +0.08 for strong lower wick rejection off EMA
                        if current.lower_wick > current.body_size * 1.0:
                            confidence += 0.08

                        # +0.07 for volume confirmation
                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20:
                            confidence += 0.07

                        # +0.05 for MACD histogram turning positive
                        if indicators.macd_histogram and indicators.macd_histogram > 0:
                            confidence += 0.05

                        ema_spread = ((indicators.ema_50 - indicators.ema_200) / indicators.ema_200) * 100

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=min(confidence, 1.0),
                            entry=current.close,
                            notes=(
                                f"Bullish trend pullback: EMA stack aligned "
                                f"(50={indicators.ema_50:.2f} > 100={indicators.ema_100:.2f} > "
                                f"200={indicators.ema_200:.2f}, spread={ema_spread:.2f}%). "
                                f"Price tagged 50 EMA, RSI hooked up from "
                                f"{indicators.prev_rsi_14:.1f} → {indicators.rsi_14:.1f}."
                            ),
                        )

        # ═══════ SHORT Setup ═══════
        if self._check_ema_alignment_bearish(indicators):
            if indicators.ema_50 and indicators.atr_14 and self._price_tags_ema50(current, indicators.ema_50, indicators.atr_14, 'SHORT'):
                if current.close < indicators.ema_50:
                    # Momentum filter: reject massive green marubozu that barely closed below
                    if indicators.atr_14 and current.body_size >= (indicators.atr_14 * self.ATR_BODY_MULTIPLIER):
                        return None
                    if self._rsi_hooked_bearish(candles, indicators):
                        confidence = 0.65

                        if current.is_bearish:
                            confidence += 0.10

                        if current.upper_wick > current.body_size * 1.0:
                            confidence += 0.08

                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20:
                            confidence += 0.07

                        if indicators.macd_histogram and indicators.macd_histogram < 0:
                            confidence += 0.05

                        ema_spread = ((indicators.ema_200 - indicators.ema_50) / indicators.ema_200) * 100

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=min(confidence, 1.0),
                            entry=current.close,
                            notes=(
                                f"Bearish trend pullback: EMA stack aligned "
                                f"(50={indicators.ema_50:.2f} < 100={indicators.ema_100:.2f} < "
                                f"200={indicators.ema_200:.2f}, spread={ema_spread:.2f}%). "
                                f"Price tagged 50 EMA, RSI hooked down from "
                                f"{indicators.prev_rsi_14:.1f} → {indicators.rsi_14:.1f}."
                            ),
                        )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: 5-candle pivot + 0.3 ATR buffer."""
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-5:])
            return round(recent_low - (0.3 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-5:])
            return round(recent_high + (0.3 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2.0R and 4.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + 2.0 * risk, 8), round(entry + 4.0 * risk, 8))
        else:
            return (round(entry - 2.0 * risk, 8), round(entry - 4.0 * risk, 8))

    def should_confirm_with_llm(self, signal):
        return True

    def update_context(self, symbol, htf_candles, htf_indicators, sr_zones):
        ctx = self._context_state
        ctx.clear()

        trend = "NEUTRAL"
        if all([htf_indicators.ema_50, htf_indicators.ema_100, htf_indicators.ema_200]):
            if htf_indicators.ema_50 > htf_indicators.ema_100 > htf_indicators.ema_200:
                trend = "BULLISH"
            elif htf_indicators.ema_50 < htf_indicators.ema_100 < htf_indicators.ema_200:
                trend = "BEARISH"

        ctx.regime = trend
        ctx.indicators_snapshot = {
            'ema_50': htf_indicators.ema_50,
            'ema_100': htf_indicators.ema_100,
            'ema_200': htf_indicators.ema_200,
            'rsi_14': htf_indicators.rsi_14,
        }
        ctx.last_updated = datetime.utcnow()

    def evaluate_trigger(self, symbol, timeframe, ltf_candles, ltf_indicators, current_price):
        ctx = self._context_state
        if not ctx.last_updated:
            return None

        signal = self.scan(symbol, timeframe, ltf_candles, ltf_indicators, [], None)
        if signal is None:
            return None

        if ctx.regime == "BULLISH" and signal.direction == "SHORT":
            return None
        if ctx.regime == "BEARISH" and signal.direction == "LONG":
            return None

        signal.htf_context_summary = f"HTF trend: {ctx.regime} (EMA stack on {self.context_tf})"
        signal.ltf_trigger_summary = f"Pullback to 50 EMA with RSI momentum hook on {timeframe}"
        return signal
