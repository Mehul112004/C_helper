import os
import logging
from app.core.llm_providers.base import BaseLLMProvider
from app.core.llm_providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

def get_llm_provider() -> BaseLLMProvider:
    """
    Reads environment configuration to determine and instantiate the appropriate LLM provider.
    """
    provider_type = os.environ.get("LLM_PROVIDER", "lm_studio").lower()
    
    # Defaults depending on the provider type for easy swapping
    if provider_type == "groq":
        default_url = "https://api.groq.com/openai/v1/chat/completions"
        default_model = "llama3-70b-8192" 
    elif provider_type == "openrouter":
        default_url = "https://openrouter.ai/api/v1/chat/completions"
        default_model = "meta-llama/llama-3-70b-instruct"
    elif provider_type == "openai":
        default_url = "https://api.openai.com/v1/chat/completions"
        default_model = "gpt-4o"
    else: # lm_studio
        default_url = "http://localhost:1234/v1/chat/completions"
        default_model = "google/gemma-4-e4b"

    api_url = os.environ.get("LLM_API_URL", default_url)
    model = os.environ.get("LLM_MODEL", default_model)
    
    # Check general api key var first
    api_key = os.environ.get("LLM_API_KEY", "")

    # For groq specifically we have GROQ_API_KEY from previous config
    if provider_type == "groq" and not api_key:
        api_key = os.environ.get("GROQ_API_KEY", "")

    try:
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", 2500))
    except (ValueError, TypeError):
        max_tokens = 2500

    logger.info(f"[LLMFactory] Initializing LLM Provider: {provider_type} (Model: {model}) at {api_url}")

    # In the future, if you add Anthropic or Gemini, return their specific Provider instances here.
    if provider_type in ["lm_studio", "groq", "openrouter", "openai"]:
        return OpenAICompatibleProvider(
            api_url=api_url, 
            model=model, 
            api_key=api_key, 
            max_tokens=max_tokens
        )
    else:
        # Fallback to OpenAI compatible if unknown
        logger.warning(f"Unknown LLM_PROVIDER '{provider_type}', falling back to OpenAICompatibleProvider.")
        return OpenAICompatibleProvider(
            api_url=api_url, 
            model=model, 
            api_key=api_key, 
            max_tokens=max_tokens
        )
