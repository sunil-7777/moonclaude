import re
import json

def _obj_or_dict(value, key: str):
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)

def _extract_model(kwargs, response_obj) -> str:
    # Prefer the strictly returned model from the provider response (e.g., 'openrouter/qwen')
    model = _obj_or_dict(response_obj, "model")
    
    # Fallback to the provider-specific target embedded deep in Litellm kwarg routings
    # This is usually where the hook-modified model ends up
    if not model and isinstance(kwargs, dict):
        params = kwargs.get("litellm_params", {})
        if isinstance(params, dict) and params.get("model"):
            model = params.get("model")
            
    # Also check the direct 'model' in kwargs - LiteLLM might have updated it from our hook
    if not model and isinstance(kwargs, dict):
        model = kwargs.get("model")
        
    # If the model is still a Claude alias, it means it failed BEFORE the hook or the hook didn't run.
    if model and isinstance(model, str) and model.startswith("openrouter/"):
        model = model.replace("openrouter/", "")
        
    return str(model or "unknown")

def _extract_error_message(exc_obj) -> str:
    if not exc_obj:
        return "failed"
    msg = str(exc_obj)
    
    # Extract nested JSON error if present from OpenRouter/Anthropic
    match = re.search(r'(\{.*"error".*"message".*\})', msg)
    if match:
        try:
            data = json.loads(match.group(1))
            return str(data["error"]["message"])
        except Exception:
            pass
            
    # Clean up the generic LiteLLM exception prefix noise
    msg = re.sub(r'^litellm\.[a-zA-Z]+Error:\s*', '', msg)
    msg = re.sub(r'^[a-zA-Z]+Exception -\s*', '', msg)
    
    # Remove proxy trailing status info
    msg = re.sub(r'Passed model=.*$', '', msg, flags=re.IGNORECASE)
    msg = re.sub(r'You passed in model=.*$', '', msg, flags=re.IGNORECASE)
    
    return msg.strip(". ")

# Test Cases
print("--- Test Model Extraction ---")
# Case 1: Success with provider model
print(f"Success: {_extract_model({'model': 'claude-opus-4-6'}, {'model': 'openrouter/qwen/qwen3.6-plus:free'})}")

# Case 2: Failure with hook-modified model in params
print(f"Failure (params): {_extract_model({'model': 'claude-opus-4-6', 'litellm_params': {'model': 'openrouter/nvidia/nemotron-nano-9b-v2:free'}}, None)}")

# Case 3: Failure with hook-modified model in root
print(f"Failure (root): {_extract_model({'model': 'openrouter/openai/gpt-oss-120b:free'}, None)}")

print("\n--- Test Error Extraction ---")
# Case 1: OpenRouter "no healthy deployments" error
err1 = 'litellm.InternalServerError: LiteLLM Error - You passed in model=openrouter/nvidia/nemotron-nano-9b-v2:free. There are no healthy deployments for this model'
print(f"Error 1 cleanup: {_extract_error_message(err1)}")

# Case 2: JSON error
err2 = '{"error": {"message": "Invalid API Key"}}'
print(f"Error 2 cleanup: {_extract_error_message(err2)}")

# Case 3: Random exception
err3 = 'Exception - Connection Timed Out'
print(f"Error 3 cleanup: {_extract_error_message(err3)}")
