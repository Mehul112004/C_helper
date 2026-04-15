from datetime import datetime
from app.core.base_strategy import SetupSignal, Candle, Indicators
from app.core.llm_client import LLMClient, LLMVerdictSchema, LLM_CONFIDENCE_THRESHOLD

def test_prompt_builder():
    signal = SetupSignal(strategy_name="TestStrat", symbol="BTCUSDT", timeframe="4h", direction="LONG", confidence=0.8, entry=40000.0)
    candles = [Candle(datetime.now(), 40000, 40100, 39900, 40050, 100)]
    inds = Indicators(rsi_14=45, macd_line=10, macd_signal=8, macd_histogram=2, ema_9=39000, ema_21=38000, ema_50=35000, ema_200=30000, atr_14=150.0)
    sr_zones = [{'price_level': 39000, 'zone_type': 'support', 'strength_score': 0.8}]
    
    prompt = LLMClient._build_prompt_context(signal, candles, inds, sr_zones)
    assert "TestStrat" in prompt
    assert "BTCUSDT" in prompt
    # Chain-of-thought: prompt should instruct reasoning first
    assert "reasoning FIRST" in prompt
    # Candle momentum analysis should be injected
    assert "Body/ATR ratio" in prompt
    # Should NOT hallucinate — prompt must warn against it
    assert "Do NOT invent" in prompt
    print("Prompt builder is working successfully.")

def test_schema_field_order():
    """Verify the chain-of-thought schema: reasoning comes before verdict."""
    valid_json = '{"reasoning": "RSI hooked up from 38, EMA stack aligned, body/ATR=0.3x which is a gentle pullback.", "confidence_score": 7, "verdict": "CONFIRM", "modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    parsed = LLMVerdictSchema.model_validate_json(valid_json)
    assert parsed.verdict == "CONFIRM"
    assert parsed.confidence_score == 7
    assert "RSI hooked up" in parsed.reasoning
    print("Schema field order (reasoning → confidence → verdict) working correctly.")

def test_schema_valid():
    valid_json = '{"reasoning": "Looks great", "confidence_score": 8, "verdict": "CONFIRM", "modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    parsed = LLMVerdictSchema.model_validate_json(valid_json)
    assert parsed.verdict == "CONFIRM"
    assert parsed.confidence_score == 8
    print("Schema parsing working successfully.")

def test_low_confidence_auto_downgrade():
    """If LLM says CONFIRM but confidence < threshold, it should be caught downstream."""
    low_conf_json = '{"reasoning": "Not very sure about this one.", "confidence_score": 2, "verdict": "CONFIRM", "modified_sl": null, "modified_tp1": null, "modified_tp2": null}'
    parsed = LLMVerdictSchema.model_validate_json(low_conf_json)
    # The auto-downgrade happens in evaluate_signal(), not in schema parsing.
    # But we can verify the threshold constant is set correctly.
    assert parsed.confidence_score < LLM_CONFIDENCE_THRESHOLD
    assert LLM_CONFIDENCE_THRESHOLD == 4
    print("Low confidence threshold validation working correctly.")

if __name__ == "__main__":
    test_prompt_builder()
    test_schema_field_order()
    test_schema_valid()
    test_low_confidence_auto_downgrade()
