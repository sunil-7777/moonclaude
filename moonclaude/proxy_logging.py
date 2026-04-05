"""
LiteLLM callback that emits structured Moon events.

Formatting and live summary rendering are handled by MoonClaude parent process.
"""

from __future__ import annotations

import itertools
import json
import threading

try:
    from litellm.integrations.custom_logger import CustomLogger
except Exception:  # pragma: no cover - import-safe fallback
    CustomLogger = object  # type: ignore[misc,assignment]


_counter = itertools.count(1)
_lock = threading.Lock()


class MoonUsageLogger(CustomLogger):  # type: ignore[misc]
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """Intercept proxy calls inside LiteLLM to inject live model routing without restarts."""
        import os
        import json
        from pathlib import Path
        
        try:
            # We don't want to import full moonclaude config here to keep startup fast, so hardcode the path
            config_dir = Path(os.environ.get("MOONCLAUDE_CONFIG_DIR", Path.home() / ".moonclaude"))
            state_file = config_dir / "config.json"
            
            with open(state_file, "r") as f:
                state = json.load(f)
                
            model_id = state.get("primary_model_id")
            if not model_id:
                return data

            active = next((m for m in state.get("configured_models", []) if m["model_id"] == model_id), None)
            if not active:
                return data

            litellm_model = active.get("litellm_model", f"openrouter/{model_id}")
            data["model"] = litellm_model
            
            # Map API key directly into kwargs, bypassing the stale litellm.yaml definitions
            if litellm_model.startswith("openrouter/"):
                data["api_key"] = os.environ.get("OPENROUTER_API_KEY")
            elif litellm_model.startswith("gemini/"):
                data["api_key"] = os.environ.get("GEMINI_API_KEY")
            elif litellm_model.startswith("groq/"):
                data["api_key"] = os.environ.get("GROQ_API_KEY")
            elif litellm_model.startswith("openai/"):
                data["api_key"] = os.environ.get("OPENAI_API_KEY")
                
            # Apply ZDR privacy flags if supported
            if active.get("zdr"):
                data.setdefault("extra_body", {}).setdefault("provider", {})["data_collection"] = "deny"
            else:
                try:
                    # Clear it natively
                    data.get("extra_body", {}).get("provider", {}).pop("data_collection", None)
                except Exception:
                    pass

        except Exception:
            pass  # Fail gracefully to existing litellm configuration
            
        return data

    def log_success_event(self, kwargs, response_obj, start_time, end_time):  # pragma: no cover - runtime callback
        self._record_success(kwargs, response_obj)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):  # pragma: no cover
        self._record_success(kwargs, response_obj)

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):  # pragma: no cover
        self._record_failure(kwargs, response_obj)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):  # pragma: no cover
        self._record_failure(kwargs, response_obj)

    def _record_success(self, kwargs, response_obj):
        with _lock:
            index = next(_counter)

        payload = {
            "id": index,
            "status": "success",
            "requested_model": _requested_model(kwargs),
            "actual_model": _extract_model(kwargs, response_obj),
            "req_name": _request_name(kwargs),
            "res_name": _response_name(response_obj),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated": True,
        }

        prompt_tokens, completion_tokens, estimated = _token_usage(response_obj)
        payload["prompt_tokens"] = prompt_tokens
        payload["completion_tokens"] = completion_tokens
        payload["estimated"] = estimated

        with _lock:
            print(f"[moon:event] {json.dumps(payload, ensure_ascii=False)}", flush=True)

    def _record_failure(self, kwargs, response_obj):
        with _lock:
            index = next(_counter)

        exc = kwargs.get("exception")
        
        def _extract_error_message(exc_obj) -> str:
            if not exc_obj:
                return "failed"
            import re
            import json
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
            msg = re.sub(r'\s*Passed model=.*$', '', msg)
            
            return msg.strip()

        error_msg = _extract_error_message(exc)

        payload = {
            "id": index,
            "status": "failure",
            "requested_model": _requested_model(kwargs),
            "actual_model": _extract_model(kwargs, response_obj),
            "req_name": _request_name(kwargs),
            "res_name": error_msg,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated": True,
        }
        with _lock:
            print(f"[moon:event] {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _extract_model(kwargs, response_obj) -> str:
    # Prefer the strictly returned model from the provider response (e.g., 'openrouter/qwen')
    model = _obj_or_dict(response_obj, "model")
    
    # Fallback to the provider-specific target embedded deep in Litellm kwarg routings
    if not model and isinstance(kwargs, dict):
        params = kwargs.get("litellm_params", {})
        if isinstance(params, dict) and params.get("model"):
            model = params.get("model")
            
    # Absolute final fallback to the top-level alias (e.g., 'claude-opus-4-6')
    if not model and isinstance(kwargs, dict):
        model = kwargs.get("model")
        
    return str(model or "unknown")


def _requested_model(kwargs) -> str:
    if isinstance(kwargs, dict):
        proxy_request = kwargs.get("proxy_server_request")
        if isinstance(proxy_request, dict):
            body = proxy_request.get("body", {})
            model = body.get("model")
            if model:
                return str(model)
        model = kwargs.get("model")
        if model:
            return str(model)
    return "unknown"


def _request_name(kwargs) -> str:
    if isinstance(kwargs, dict):
        proxy_request = kwargs.get("proxy_server_request")
        if isinstance(proxy_request, dict):
            body = proxy_request.get("body", {})
            text = _first_user_message(body.get("messages", []))
            if text:
                return _short_label(text)
        text = _first_user_message(kwargs.get("messages", []))
        if text:
            return _short_label(text)
    return "request"


def _response_name(response_obj) -> str:
    choices = _obj_or_dict(response_obj, "choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            content = message.get("content")
            text = _extract_text(content)
            if text:
                return _short_label(text)
        else:
            message = _obj_or_dict(first, "message")
            content = _obj_or_dict(message, "content")
            text = _extract_text(content)
            if text:
                return _short_label(text)
    return "response"


def _token_usage(response_obj) -> tuple[int, int, bool]:
    usage = _obj_or_dict(response_obj, "usage")
    if not usage:
        return 0, 0, True

    prompt_tokens = _int_value(usage, "prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = _int_value(usage, "input_tokens")

    completion_tokens = _int_value(usage, "completion_tokens")
    if completion_tokens is None:
        completion_tokens = _int_value(usage, "output_tokens")

    if prompt_tokens is None:
        prompt_tokens = 0
    if completion_tokens is None:
        completion_tokens = 0

    estimated = prompt_tokens == 0 and completion_tokens == 0
    return prompt_tokens, completion_tokens, estimated


def _int_value(value, key: str) -> int | None:
    if isinstance(value, dict):
        raw = value.get(key)
    else:
        raw = getattr(value, key, None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _obj_or_dict(value, key: str):
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _first_user_message(messages) -> str:
    if not isinstance(messages, list):
        return ""
    # Claude passes full history; we want the LAST user message logically
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        text = _extract_text(message.get("content"))
        if text:
            return text
    return ""


def _extract_text(content) -> str:
    import re
    def _strip_reminders(t: str) -> str:
        return re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.DOTALL | re.IGNORECASE)

    if isinstance(content, str):
        return " ".join(_strip_reminders(content).split())
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = str(item.get("text", "")).strip()
            text = _strip_reminders(text)
            if text:
                parts.append(" ".join(text.split()))
    return " ".join(parts).strip()


def _short_label(text: str, max_words: int = 7, max_chars: int = 54) -> str:
    words = text.split()
    trimmed = " ".join(words[:max_words])
    if len(trimmed) > max_chars:
        trimmed = trimmed[: max_chars - 3].rstrip() + "..."
    return trimmed or "n/a"


moon_usage_logger = MoonUsageLogger()

