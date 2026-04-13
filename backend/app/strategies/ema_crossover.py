"""
EMA Crossover Strategy
Reactive strategy on 15m, 1h, 4h.

LONG: EMA 9 crosses above EMA 21 with close > EMA 50 (trend filter)
SHORT: EMA 9 crosses below EMA 21 with close < EMA 50 (trend filter)
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class EMACrossoverStrategy(BaseStrategy):
    name = "EMA Crossover"
    description = "EMA 9 crosses EMA 21 with EMA 50 trend filter"
    timeframes = ["15m", "1h", "4h"]
    version = "1.0"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # Guard: need previous bar EMA values for crossover detection
        if indicators.prev_ema_9 is None or indicators.prev_ema_21 is None:
            return None
        if indicators.ema_9 is None or indicators.ema_21 is None:
            return None

        # Detect crossover
        prev_above = indicators.prev_ema_9 > indicators.prev_ema_21
        curr_above = indicators.ema_9 > indicators.ema_21
        prev_below = indicators.prev_ema_9 < indicators.prev_ema_21
        curr_below = indicators.ema_9 < indicators.ema_21

        bullish_cross = (not prev_above) and curr_above
        bearish_cross = (not prev_below) and curr_below

        if not bullish_cross and not bearish_cross:
            return None

        close = candles[-1].close

        # Trend filter: EMA 50
        if indicators.ema_50 is not None:
            if bullish_cross and close < indicators.ema_50:
                return None  # Counter-trend long, skip
            if bearish_cross and close > indicators.ema_50:
                return None  # Counter-trend short, skip

        direction = "LONG" if bullish_cross else "SHORT"

        # Confidence scoring
        confidence = 0.60

        # +0.10 if volume confirms
        if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
            confidence += 0.10

        # +0.10 if aligned with EMA 200 trend
        if indicators.ema_200 is not None:
            if direction == "LONG" and close > indicators.ema_200:
                confidence += 0.10
            elif direction == "SHORT" and close < indicators.ema_200:
                confidence += 0.10

        # +0.05 if RSI is in mid-range (not overbought/oversold)
        if indicators.rsi_14 is not None and 35 <= indicators.rsi_14 <= 65:
            confidence += 0.05

        cross_type = "bullish" if bullish_cross else "bearish"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"EMA 9/21 {cross_type} crossover on {timeframe}",
        )

    def calculate_sl(self, signal, candles, atr):
        """Tighter SL for reactive EMA crosses: 1.2 × ATR."""
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (1.2 * atr), 8)
        else:
            return round(entry + (1.2 * atr), 8)
