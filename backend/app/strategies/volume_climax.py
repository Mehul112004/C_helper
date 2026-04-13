"""
Volume Climax / Absorption Reversal Strategy
Detects institutional absorption via volume anomalies.

Logic:
Looks for an ultra-high volume candle (Volume > 3x MA20) with a relatively small body indicating absorption of limit orders.
Occurring after a directional trend, this often spots local bottoms or tops before a reversal.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class VolumeClimaxStrategy(BaseStrategy):
    name = "Volume Climax"
    description = "Detects institutional stopping volume or climax buying for trend reversals."
    timeframes = ["5m", "15m", "1h"]
    version = "1.0"
    min_confidence = 0.65

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 10 or not indicators.volume_ma_20:
            return None

        current_candle = candles[-1]
        
        # We need an ultra-high volume anomaly
        if current_candle.volume > indicators.volume_ma_20 * 3:
            
            # Check for Capitulation / Stopping Volume (Bullish Reversal)
            # Must occur after a downtrend (last 3 of 4 candles bearish)
            recent_bearish = sum(1 for c in candles[-5:-1] if c.is_bearish)
            if recent_bearish >= 3:
                # The climax candle should have a long lower wick or be a small-bodied reversal candle
                if current_candle.lower_wick > current_candle.body_size * 2 or current_candle.body_size < current_candle.range_size * 0.3:
                    # Confluence: RSI oversold
                    if indicators.rsi_14 and indicators.rsi_14 < 35:
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=0.80,
                            entry=current_candle.close,
                            notes=f"Volume Climax Detected: Volume is {current_candle.volume:.2f} (MA: {indicators.volume_ma_20:.2f}) after a downtrend. High probability of institutional absorption.",
                        )

            # Check for Climax Buying (Bearish Reversal)
            # Must occur after an uptrend (last 3 of 4 candles bullish)
            recent_bullish = sum(1 for c in candles[-5:-1] if c.is_bullish)
            if recent_bullish >= 3:
                # The climax candle should have a long upper wick or be a small-bodied exhaustive candle
                if current_candle.upper_wick > current_candle.body_size * 2 or current_candle.body_size < current_candle.range_size * 0.3:
                    # Confluence: RSI overbought
                    if indicators.rsi_14 and indicators.rsi_14 > 65:
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=0.80,
                            entry=current_candle.close,
                            notes=f"Climax Buying Detected: Volume is {current_candle.volume:.2f} (MA: {indicators.volume_ma_20:.2f}) after an uptrend. High probability of distribution.",
                        )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Volatility-based ATR SL."""
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (2.0 * atr), 8) # Slightly wider SL to weather the climax volatility
        else:
            return round(entry + (2.0 * atr), 8)

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True
