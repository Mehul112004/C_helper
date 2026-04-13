from datetime import datetime
from app.core.base_strategy import SetupSignal, Candle, Indicators
from app.core.llm_client import LLMClient, LLMVerdictSchema

def test_prompt_builder():
    signal = SetupSignal(strategy_name="TestStrat", symbol="BTCUSDT", timeframe="4h", direction="LONG", confidence=0.8, entry=40000.0)
    candles = [Candle(datetime.now(), 40000, 40100, 39900, 40050, 100)]
    inds = Indicators(rsi_14=45, macd_line=10, macd_signal=8, macd_histogram=2, ema_9=39000, ema_21=38000, ema_50=35000, ema_200=30000)
    sr_zones = [{'price_level': 39000, 'zone_type': 'support', 'strength_score': 0.8}]
    
    prompt = LLMClient._build_prompt_context(signal, candles, inds, sr_zones)
    assert "TestStrat" in prompt
    assert "BTCUSDT" in prompt
    print("Prompt builder is working successfully.")

def test_schema_valid():
    valid_json = '{"verdict": "CONFIRM", "reasoning": "Looks great", "modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    parsed = LLMVerdictSchema.model_validate_json(valid_json)
    assert parsed.verdict == "CONFIRM"
    print("Schema parsing working successfully.")

if __name__ == "__main__":
    test_prompt_builder()
    test_schema_valid()
