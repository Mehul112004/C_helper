"""
Institutional Order Block (OB) Retest Strategy
Smart Money Concept focusing on institutional accumulation/distribution zones.

Bullish OB: The last down candle before a significant bullish impulse. When price returns to this block's range, we look for a rejection to go LONG.
Bearish OB: The last up candle before a significant bearish impulse. When price returns to this block's range, we look for a rejection to go SHORT.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class OrderBlockRetestStrategy(BaseStrategy):
    name = "Order Block Retest"
    description = "Detects retracements into historical institutional Order Blocks with rejection."
    timeframes = ["1h", "4h", "1d"]
    version = "1.1"
    min_confidence = 0.60

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 20:
            return None

        current_candle = candles[-1]
        
        # Look back to find a valid order block (OB) created in the past 15 candles
        # An OB is followed by a strong impulse (e.g., 2+ candles heavily moving in one direction)
        for i in range(len(candles) - 15, len(candles) - 3):
            if i < 0:
                continue
                
            # Check for Bullish OB: A bearish candle followed by a strong bullish impulse
            if candles[i].is_bearish:
                # Check next 2 candles for strong bullish impulse (relaxed from 3)
                impulse_candles = candles[i+1:i+3]
                if len(impulse_candles) >= 2 and all(c.is_bullish for c in impulse_candles):
                    impulse_size = impulse_candles[-1].close - impulse_candles[0].open
                    avg_body = sum(c.body_size for c in impulse_candles) / len(impulse_candles)
                    
                    if impulse_size > avg_body * 1.5:  # Relaxed from 2x
                        ob_high = candles[i].high
                        ob_low = candles[i].low
                        
                        # Verify price has retraced to the OB
                        if ob_low <= current_candle.low <= ob_high or ob_low <= current_candle.close <= ob_high:
                            # Rejection condition: lower wick shows buying pressure
                            if current_candle.lower_wick > current_candle.body_size * 0.8:
                                confidence = 0.65
                                
                                # +0.10 if RSI supports (not overbought)
                                if indicators.rsi_14 and indicators.rsi_14 < 55:
                                    confidence += 0.10
                                
                                # +0.10 if volume confirms
                                if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                                    confidence += 0.10
                                
                                return SetupSignal(
                                    strategy_name=self.name,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    direction="LONG",
                                    confidence=min(confidence, 1.0),
                                    entry=current_candle.close,
                                    notes=f"Bullish Order Block retest at zone {ob_low:.2f}-{ob_high:.2f}. Originated at {candles[i].open_time.strftime('%Y-%m-%d %H:%M')}.",
                                )

            # Check for Bearish OB: A bullish candle followed by a strong bearish impulse
            if candles[i].is_bullish:
                impulse_candles = candles[i+1:i+3]
                if len(impulse_candles) >= 2 and all(c.is_bearish for c in impulse_candles):
                    impulse_size = impulse_candles[0].open - impulse_candles[-1].close
                    avg_body = sum(c.body_size for c in impulse_candles) / len(impulse_candles)
                    
                    if impulse_size > avg_body * 1.5:  # Relaxed from 2x
                        ob_high = candles[i].high
                        ob_low = candles[i].low
                        
                        # Verify price has retraced to the OB
                        if ob_low <= current_candle.high <= ob_high or ob_low <= current_candle.close <= ob_high:
                            # Rejection condition: upper wick shows selling pressure
                            if current_candle.upper_wick > current_candle.body_size * 0.8:
                                confidence = 0.65
                                
                                # +0.10 if RSI supports (not oversold)
                                if indicators.rsi_14 and indicators.rsi_14 > 45:
                                    confidence += 0.10
                                
                                # +0.10 if volume confirms
                                if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                                    confidence += 0.10
                                
                                return SetupSignal(
                                    strategy_name=self.name,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    direction="SHORT",
                                    confidence=min(confidence, 1.0),
                                    entry=current_candle.close,
                                    notes=f"Bearish Order Block retest at zone {ob_low:.2f}-{ob_high:.2f}. Originated at {candles[i].open_time.strftime('%Y-%m-%d %H:%M')}.",
                                )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Volatility-based ATR SL."""
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (1.5 * atr), 8)
        else:
            return round(entry + (1.5 * atr), 8)

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True
