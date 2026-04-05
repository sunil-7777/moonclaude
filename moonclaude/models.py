"""
Model catalog helpers.

OpenRouter free models are fetched from the public models API at runtime and
cached locally. If live fetch fails, MoonClaude falls back to cached models.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .branding import CONFIG_DIR, LEGACY_CONFIG_DIR


LEGACY_MODEL_MIGRATIONS = {
    "qwen/qwen3-235b-a22b:free": {
        "name": "Qwen 3.6 Plus (Free)",
        "model_id": "qwen/qwen3.6-plus:free",
        "litellm_model": "openrouter/qwen/qwen3.6-plus:free",
    },
    "qwen/qwen3-235b-a22b": {
        "name": "Qwen 3.6 Plus",
        "model_id": "qwen/qwen3.6-plus",
        "litellm_model": "openrouter/qwen/qwen3.6-plus",
    },
}

LEGACY_LITELLM_MODEL_MIGRATIONS = {
    "openrouter/qwen/qwen3-235b-a22b:free": "openrouter/qwen/qwen3.6-plus:free",
    "openrouter/qwen/qwen3-235b-a22b": "openrouter/qwen/qwen3.6-plus",
}

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_ZDR_URL = "https://openrouter.ai/api/v1/endpoints/zdr"
OPENROUTER_CACHE_PATH = CONFIG_DIR / "openrouter-models.json"
OPENROUTER_ZDR_CACHE_PATH = CONFIG_DIR / "openrouter-zdr.json"
LEGACY_OPENROUTER_CACHE_PATH = LEGACY_CONFIG_DIR / "openrouter-models.json"
OPENROUTER_FETCH_TIMEOUT = 10


class ModelCatalogError(RuntimeError):
    """Raised when a provider catalog cannot be loaded."""


STATIC_PROVIDERS = {
    "OpenRouter": {
        "key_env": "OPENROUTER_API_KEY",
        "key_label": "OpenRouter API Key",
        "key_url": "https://openrouter.ai/settings/keys",
        "models": [],
    },
    "Gemini (Direct)": {
        "key_env": "GEMINI_API_KEY",
        "key_label": "Gemini API Key",
        "key_url": "https://aistudio.google.com/app/apikey",
        "models": [
            {
                "name": "Gemini 2.0 Flash",
                "model_id": "gemini/gemini-2.0-flash",
                "litellm_model": "gemini/gemini-2.0-flash",
                "free": True,
            },
            {
                "name": "Gemini 1.5 Pro",
                "model_id": "gemini/gemini-1.5-pro",
                "litellm_model": "gemini/gemini-1.5-pro",
                "free": False,
            },
        ],
    },
    "Groq": {
        "key_env": "GROQ_API_KEY",
        "key_label": "Groq API Key",
        "key_url": "https://console.groq.com/keys",
        "models": [
            {
                "name": "Llama 3.3 70B (Fast)",
                "model_id": "groq/llama-3.3-70b-versatile",
                "litellm_model": "groq/llama-3.3-70b-versatile",
                "free": True,
            },
            {
                "name": "Mixtral 8x7B",
                "model_id": "groq/mixtral-8x7b-32768",
                "litellm_model": "groq/mixtral-8x7b-32768",
                "free": True,
            },
        ],
    },
}

# Backwards-compatible constant for callers that still import PROVIDERS.
PROVIDERS = STATIC_PROVIDERS


def get_provider_names() -> list[str]:
    return list(STATIC_PROVIDERS.keys())


def get_provider(provider_name: str) -> dict:
    if provider_name not in STATIC_PROVIDERS:
        raise KeyError(f"Unknown provider: {provider_name}")

    provider = copy.deepcopy(STATIC_PROVIDERS[provider_name])

    if provider_name == "OpenRouter":
        models, source = load_openrouter_free_models()
        # Fetch ZDR status for these models
        zdr_ids = set()
        try:
            zdr_data = _fetch_openrouter_zdr_list()
            zdr_ids = {m.get("model_id") for m in zdr_data}
        except Exception:
            pass # Fallback to no ZDR info
            
        for model in models:
            model["zdr"] = model["model_id"].replace("openrouter/", "") in zdr_ids or model["model_id"] in zdr_ids

        provider["models"] = models
        provider["catalog_source"] = source
    else:
        provider["catalog_source"] = "static"

    return provider


def get_providers() -> dict:
    return {name: get_provider(name) for name in get_provider_names()}


def load_openrouter_free_models() -> tuple[list[dict], str]:
    try:
        models = _fetch_openrouter_free_models()
    except ModelCatalogError:
        cached_models = _read_cached_openrouter_models()
        if cached_models:
            return cached_models, "cache"
        raise

    _write_cached_openrouter_models(models)
    return models, "live"


def _fetch_openrouter_free_models() -> list[dict]:
    request = Request(
        OPENROUTER_MODELS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "moonclaude/2.0",
        },
    )

    try:
        with urlopen(request, timeout=OPENROUTER_FETCH_TIMEOUT) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise ModelCatalogError(
            f"OpenRouter returned HTTP {exc.code} while fetching the free model catalog."
        ) from exc
    except URLError as exc:
        raise ModelCatalogError(
            f"Could not reach OpenRouter to load free models: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ModelCatalogError("OpenRouter returned invalid JSON for the model catalog.") from exc

    if not isinstance(payload, dict):
        raise ModelCatalogError("OpenRouter returned an unexpected model catalog payload.")

    raw_models = payload.get("data", [])
    models = []
    seen_model_ids = set()

    for raw_model in raw_models:
        model = _normalize_openrouter_model(raw_model)
        if model is None:
            continue
        if model["model_id"] in seen_model_ids:
            continue
        seen_model_ids.add(model["model_id"])
        models.append(model)

    models.sort(key=lambda item: (item["name"].casefold(), item["model_id"].casefold()))

    if not models:
        raise ModelCatalogError("OpenRouter did not return any free text models.")

    return models


def _fetch_openrouter_zdr_list() -> list[dict]:
    request = Request(
        OPENROUTER_ZDR_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "moonclaude/2.0",
        },
    )
    try:
        with urlopen(request, timeout=OPENROUTER_FETCH_TIMEOUT) as response:
            payload = json.load(response)
            return payload.get("data", [])
    except Exception:
        return []


def _normalize_openrouter_model(raw_model: dict) -> dict | None:
    model_id = str(raw_model.get("id") or "").strip()
    if not model_id or not model_id.endswith(":free"):
        return None
    if not _supports_text_io(raw_model):
        return None

    name = str(raw_model.get("name") or model_id).strip()
    if "free" not in name.lower():
        name = f"{name} (Free)"

    # Check if this model supports tool/function calling
    # Three-state: True (confirmed), False (explicitly unsupported), None (unknown/not reported)
    supported_params = raw_model.get("supported_parameters")
    if supported_params is not None and isinstance(supported_params, list) and len(supported_params) > 0:
        supports_tools = "tools" in supported_params
    else:
        supports_tools = None  # Unknown — API didn't report

    return {
        "name": name,
        "model_id": model_id,
        "litellm_model": f"openrouter/{model_id}",
        "free": True,
        "supports_tools": supports_tools,
    }


def _supports_text_io(raw_model: dict) -> bool:
    architecture = raw_model.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []

    if not input_modalities and not output_modalities:
        return True

    return "text" in input_modalities and "text" in output_modalities


def _read_cached_openrouter_models() -> list[dict]:
    for path in (OPENROUTER_CACHE_PATH, LEGACY_OPENROUTER_CACHE_PATH):
        models = _read_cached_models_file(path)
        if models:
            return models
    return []


def _read_cached_models_file(path: Path) -> list[dict]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        raw_models = payload.get("models", [])
    elif isinstance(payload, list):
        raw_models = payload
    else:
        raw_models = []

    models = []
    seen_model_ids = set()
    for raw_model in raw_models:
        model = _normalize_cached_model(raw_model)
        if model is None:
            continue
        if model["model_id"] in seen_model_ids:
            continue
        seen_model_ids.add(model["model_id"])
        models.append(model)

    models.sort(key=lambda item: (item["name"].casefold(), item["model_id"].casefold()))
    return models


def _normalize_cached_model(raw_model: dict) -> dict | None:
    if not isinstance(raw_model, dict):
        return None

    model_id = str(raw_model.get("model_id") or "").strip()
    if not model_id:
        return None

    name = str(raw_model.get("name") or model_id).strip()
    litellm_model = str(raw_model.get("litellm_model") or f"openrouter/{model_id}").strip()

    return {
        "name": name,
        "model_id": model_id,
        "litellm_model": litellm_model,
        "free": True,
        "supports_tools": bool(raw_model.get("supports_tools", False)),
    }


def _write_cached_openrouter_models(models: list[dict]) -> None:
    payload = {
        "source": OPENROUTER_MODELS_URL,
        "models": models,
    }

    try:
        OPENROUTER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENROUTER_CACHE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        # Live model fetching should still work even if the cache location is unavailable.
        return


CLAUDE_MODEL_ALIASES = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

