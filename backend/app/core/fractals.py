"""
Fractal and swing detection utilities.
Shared across multiple strategy modules (SMC, Fibonacci, etc.).
"""
from app.core.base_strategy import Candle
def find_fractal_points(candles: list[Candle], pivot_n: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Find fractal highs and lows in a list of candles.
    
    A fractal high exists at index `i` if `candle[i].high` is strictly greater
    than the highs of all candles within `±pivot_n` bars.
    
    A fractal low exists at index `i` if `candle[i].low` is strictly less
    than the lows of all candles within `±pivot_n` bars.
    
    Returns:
        (fractal_highs, fractal_lows): Two lists of (index, price) tuples.
    """
    fractal_highs = []
    fractal_lows = []
    
    for i in range(pivot_n, len(candles) - pivot_n):
        # Check Fractal High
        is_high = True
        for j in range(1, pivot_n + 1):
            if candles[i].high <= candles[i - j].high or candles[i].high <= candles[i + j].high:
                is_high = False
                break
        if is_high:
            fractal_highs.append((i, candles[i].high))
            
        # Check Fractal Low
        is_low = True
        for j in range(1, pivot_n + 1):
            if candles[i].low >= candles[i - j].low or candles[i].low >= candles[i + j].low:
                is_low = False
                break
        if is_low:
            fractal_lows.append((i, candles[i].low))
            
    return fractal_highs, fractal_lows
def build_swing_map(candles: list[Candle], pivot_n: int) -> list[dict]:
    """
    Build an ordered list of swing points using fractal pivot detection.
    
    Returns a unified list sorted chronologically by index:
    [{'type': 'high'|'low', 'price': float, 'index': int}, ...]
    """
    highs, lows = find_fractal_points(candles, pivot_n)
    
    swings = []
    for idx, price in highs:
        swings.append({'type': 'high', 'price': price, 'index': idx})
    for idx, price in lows:
        swings.append({'type': 'low', 'price': price, 'index': idx})
        
    swings.sort(key=lambda s: s['index'])
    return swings