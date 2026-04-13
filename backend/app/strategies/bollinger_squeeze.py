"""
Bollinger Band Squeeze Strategy
Reactive strategy on 15m, 1h, 4h.

Detects periods of low volatility (squeeze) followed by a directional breakout.
LONG: After squeeze, close breaks at or above upper band with volume confirmation
SHORT: After squeeze, close breaks at or below lower band with volume confirmation
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class BollingerSqueezeStrategy(BaseStrategy):
    name = "Bollinger Band Squeeze"
    description = "Price breaks out of bands after low-volatility squeeze"
    timeframes = ["15m", "1h", "4h"]
    version = "1.1"

    # Minimum number of bb_width history values needed to detect a squeeze
    MIN_BB_HISTORY = 10

    def _is_squeeze(self, indicators: Indicators) -> bool:
        """
        Detect if a Bollinger Band squeeze was active on the previous bar.
        Squeeze = bb_width below the mean of the last 20 bb_width values.
        """
        history = indicators.bb_width_history
        if len(history) < self.MIN_BB_HISTORY:
            return False

        # Average bb_width over the available history
        avg_width = sum(history) / len(history)

        # Previous bar's width must be below average (squeeze was active)
        if indicators.prev_bb_width is None:
            return False

        return indicators.prev_bb_width < avg_width

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # Guard: need Bollinger Band values
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return None
        if indicators.bb_width is None or indicators.prev_bb_width is None:
            return None

        close = candles[-1].close

        # Step 1: Was there a squeeze on the previous bar?
        if not self._is_squeeze(indicators):
            return None

        # Step 2: Detect breakout direction
        # Allow near-band touches (within 0.1% of band) as well as strict breakouts
        band_tolerance = indicators.bb_upper * 0.001  # 0.1% tolerance
        breakout_up = close >= (indicators.bb_upper - band_tolerance)
        breakout_down = close <= (indicators.bb_lower + band_tolerance)

        if not breakout_up and not breakout_down:
            return None

        direction = "LONG" if breakout_up else "SHORT"

        # Confidence scoring
        confidence = 0.55

        # +0.10 if volume confirms (above average)
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.10 if extreme volume (>1.5× vol_ma)
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20 * 1.5:
            confidence += 0.10

        # +0.10 if EMA alignment
        if indicators.ema_50 is not None:
            if direction == "LONG" and close > indicators.ema_50:
                confidence += 0.10
            elif direction == "SHORT" and close < indicators.ema_50:
                confidence += 0.10

        # +0.10 if bb_width is now expanding (current > previous = breakout started)
        if indicators.bb_width > indicators.prev_bb_width:
            confidence += 0.10

        bb_direction = "above upper band" if breakout_up else "below lower band"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"Bollinger squeeze breakout {bb_direction} on {timeframe}. "
                  f"BB width: {indicators.prev_bb_width:.6f} → {indicators.bb_width:.6f}",
        )
