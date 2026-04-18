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
    timeframes = ["15m", "1h", "4h", "1D"]
    version = "1.1"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
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

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the recent 3-candle pivot preceding the crossover."""
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-3:])
            return round(recent_low - (0.2 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-3:])
            return round(recent_high + (0.2 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 1.5R and 3.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))
