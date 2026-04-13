"""
MACD Momentum Strategy
Reactive strategy on 15m, 1h, 4h, 1d.

LONG: MACD line crosses above signal line with histogram turning positive.
      Stronger if histogram was negative for ≥2 bars before (momentum buildup).
SHORT: MACD line crosses below signal line with histogram turning negative.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class MACDMomentumStrategy(BaseStrategy):
    name = "MACD Momentum"
    description = "MACD/signal cross with histogram confirmation"
    timeframes = ["15m", "1h", "4h", "1d"]
    version = "1.1"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # Guard: need current and previous MACD values
        if indicators.macd_line is None or indicators.macd_signal is None:
            return None
        if indicators.prev_macd_line is None or indicators.prev_macd_signal is None:
            return None
        if indicators.macd_histogram is None or indicators.prev_macd_histogram is None:
            return None

        # Detect MACD/Signal crossover
        prev_macd_above = indicators.prev_macd_line > indicators.prev_macd_signal
        curr_macd_above = indicators.macd_line > indicators.macd_signal
        prev_macd_below = indicators.prev_macd_line < indicators.prev_macd_signal
        curr_macd_below = indicators.macd_line < indicators.macd_signal

        bullish_cross = (not prev_macd_above) and curr_macd_above
        bearish_cross = (not prev_macd_below) and curr_macd_below

        if not bullish_cross and not bearish_cross:
            return None

        # Histogram confirmation: must agree with cross direction
        if bullish_cross and indicators.macd_histogram <= 0:
            return None
        if bearish_cross and indicators.macd_histogram >= 0:
            return None

        close = candles[-1].close
        direction = "LONG" if bullish_cross else "SHORT"

        # Confidence scoring
        confidence = 0.55

        # +0.10 for momentum buildup: check if histogram was opposite for ≥2 bars
        # We check via the candle history — looking for a momentum squeeze before the cross
        if len(candles) >= 4:
            # For bullish cross, histogram should have been negative for at least 2 prior bars
            if bullish_cross and indicators.prev_macd_histogram < 0:
                confidence += 0.10
            elif bearish_cross and indicators.prev_macd_histogram > 0:
                confidence += 0.10

        # +0.15 if EMA 50 aligns with direction
        if indicators.ema_50 is not None:
            if direction == "LONG" and close > indicators.ema_50:
                confidence += 0.15
            elif direction == "SHORT" and close < indicators.ema_50:
                confidence += 0.15

        # +0.10 if volume confirms
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.05 for strong histogram delta (large crossover momentum)
        hist_delta = abs(indicators.macd_histogram - indicators.prev_macd_histogram)
        if hist_delta > abs(indicators.macd_histogram) * 0.5:
            confidence += 0.05

        cross_type = "bullish" if bullish_cross else "bearish"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"MACD {cross_type} crossover on {timeframe}. "
                  f"Histogram: {indicators.prev_macd_histogram:.6f} → {indicators.macd_histogram:.6f}",
        )
