import os
import sys
import logging

# Ensure the 'backend' directory is in the python path (this script is in backend/scripts)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environmental variables just like the main app would
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv not installed, assuming env is already loaded or defaults suffice")

from app.core.llm_providers.factory import get_llm_provider

# Basic logging config to see the output
logging.basicConfig(level=logging.INFO)

def test_manual():
    print(f"Current LLM_PROVIDER in env: {os.environ.get('LLM_PROVIDER', 'not set (defaults to lm_studio)')}")
    
    # 1. Initialize the provider via the factory
    provider = get_llm_provider()
    
    # 2. Check if it reports as online
    if not provider.ping_status():
        print(f"⚠️ Provider {provider.model} at {provider.api_url} is unreachable. If using lm_studio, check if it's running.")
        return
        
    print(f"✅ Provider {provider.model} is online. Sending a test prompt...")
    
    # 3. Send a test analysis
    system_prompt = "You are a quantitative trading risk manager. Respond with a simple JSON object containing status='ok'."
    user_prompt = "Hello, is the LLM inference working?"
    
    content, raw_response = provider.evaluate_prompt(system_prompt, user_prompt)
    
    print("\n--- LLM RESPONSE ---")
    print("Content String:", content)
    print("--------------------")

if __name__ == "__main__":
    test_manual()
