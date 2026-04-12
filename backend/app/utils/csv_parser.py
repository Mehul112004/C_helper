import pandas as pd
from datetime import datetime

def parse_binance_csv(file_stream, symbol: str, timeframe: str):
    """
    Parses a CSV uploaded directly matching Binance export format.
    Expects columns like open_time, open, high, low, close, volume...
    """
    try:
        df = pd.read_csv(file_stream)
    except Exception as e:
        raise ValueError(f"Could not read CSV file: {e}")

    required_cols = {'open_time', 'open', 'high', 'low', 'close', 'volume'}
    # Ensure they exist (case-insensitive mapping to be nice)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    # Drop potential nans
    df = df.dropna(subset=list(required_cols))

    all_candles = []
    for _, row in df.iterrows():
        try:
            # open_time in binance exports is typically unix ms
            # Sometimes it might be an actual string date, try/except handle this
            val = row['open_time']
            if isinstance(val, (int, float)):
                # If timestamp in ms
                open_time = datetime.fromtimestamp(val / 1000.0)
            else:
                # String parse (e.g., '2023-01-01 00:00:00')
                open_time = pd.to_datetime(val).to_pydatetime()
                
            all_candles.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "open_time": open_time,
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": float(row['volume'])
            })
        except Exception as e:
            raise ValueError(f"Error parsing row: {row}. Details: {e}")

    return all_candles
