import time
import requests
from datetime import datetime

def fetch_klines(symbol: str, interval: str, start_time: int, end_time: int):
    """
    Fetch OHLCV data from Binance REST API and paginate automatically.
    start_time and end_time should be provided in milliseconds.
    """
    base_url = "https://api.binance.com/api/v3/klines"
    limit = 1000
    all_candles = []
    
    current_start = start_time

    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_time,
            "limit": limit
        }
        
        response = requests.get(base_url, params=params)
        
        if response.status_code != 200:
            raise Exception(f"Binance API Error: {response.text}")
            
        data = response.json()
        
        if not data:
            break
            
        for row in data:
            # row[0] is open_time in ms
            # The format is described in Binance docs
            all_candles.append({
                "symbol": symbol,
                "timeframe": interval,
                "open_time": datetime.fromtimestamp(row[0] / 1000.0),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            })
            
        # Update current_start to be right after the last returned candle
        last_time = data[-1][0]
        if current_start == last_time + 1:
            # We are not progressing, exit to prevent infinite loop
            break
        current_start = last_time + 1
        
        # Avoid hitting rate limits too hard
        time.sleep(0.1)

    return all_candles
