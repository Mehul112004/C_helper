# Modular LLM Provider System

## Overview

The backend uses a modular approach for interacting with Large Language Models (LLMs). This flexible architecture removes hardcoded dependencies on specific local or cloud inference setups (like LM Studio). Instead, it relies on an abstract Factory pattern, allowing you to seamlessly swap between various providers (e.g., LM Studio, Groq, OpenRouter) simply by modifying your environment file.

## Architecture

The system resides in `backend/app/core/llm_providers/` and relies on three main components:

1. **`BaseLLMProvider` (`base.py`)**: 
   An abstract base class that enforces the interface structure for all inference methods, primarily requiring an `evaluate_prompt` implementation and a `ping_status` functionality lock-in.

2. **`OpenAICompatibleProvider` (`openai_compatible.py`)**: 
   Since many local orchestrations (like LM Studio) and cloud inferences (like Groq, OpenRouter, and OpenAI) adopt the OpenAI JSON format (`/v1/chat/completions`), this class universally proxies traffic without needing custom, model-specific code variants. It leverages the standard payload layout consisting of an array of role-specified messages (`[{"role": "system", ...}, {"role": "user", ...}]`).

3. **`Factory` (`factory.py`)**: 
   The entry point for initialization. It intercepts requests for `get_llm_provider()` within the `LLMClient` and dynamically instances the chosen provider strategy dictation fetched from the `.env` settings.

## Configuration Guide (`.env`)

To switch providers, update the LLM configuration variables within the `backend/.env` file. The factory falls back to local `lm_studio` defaults if variables are omitted.

```bash
# LLM Provider Configuration
LLM_PROVIDER=groq
LLM_MAX_TOKENS=500

# Overrides (If you need to define explicit credentials when the default provider isn't detected)
# LLM_API_KEY=your_key_here
# LLM_API_URL=https://api.groq.com/openai/v1/chat/completions
# LLM_MODEL=llama3-70b-8192
```

### Supported `LLM_PROVIDER` Key Defaults
- `lm_studio` (Uses `http://localhost:1234/v1/chat/completions` and `google/gemma-4-e4b`)
- `groq` (Uses `https://api.groq.com/openai/v1/chat/completions`, grabs `GROQ_API_KEY` locally, and selects `llama3-70b-8192`)
- `openrouter` (Uses `https://openrouter.ai/api/v1/chat/completions` and `meta-llama/llama-3-70b-instruct`)
- `openai` (Uses `https://api.openai.com/v1/chat/completions` and `gpt-4o`)

## Scaling Integration (Adding Non-OpenAI APIs)

If you ever wish to add an integration with a service that has a dramatically different payload schema (e.g., Anthropic's Claude API, Gemini Native API):

1. **Create the Concrete Implementation**: Add a new file matching the format name (e.g., `app/core/llm_providers/anthropic_native.py`).
2. **Inherit `BaseLLMProvider`**: Create a class `AnthropicProvider(BaseLLMProvider)` ensuring `evaluate_prompt(system_prompt, user_prompt)` compiles to logic suited for that specific library/SDK. Let it return `(text_content, raw_response)`.
3. **Register in Factory**: Import your new module inside `factory.py`'s `get_llm_provider()` switch-case.

```python
# Inside factory.py
if provider_type == "anthropic":
    return AnthropicProvider(api_key=api_key, model=model, max_tokens=max_tokens)
```
