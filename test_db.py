from app.models.db import db, Candle
from run import app

with app.app_context():
    c = Candle.query.filter_by(timeframe='5m').order_by(Candle.open_time.desc()).first()
    if c:
        print(c.symbol, c.timeframe, c.open_time, c.open, c.high, c.low, c.close)
    else:
        print("No 5m candles")
