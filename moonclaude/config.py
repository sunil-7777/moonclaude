"""
MoonClaude config/state helpers and LiteLLM config generation.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from .branding import CONFIG_DIR, DEFAULT_PORT, LEGACY_CONFIG_DIR
from .models import LEGACY_LITELLM_MODEL_MIGRATIONS, LEGACY_MODEL_MIGRATIONS
from .shells import write_shell_helpers


CLAUDE_ALIASES = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

LITELLM_CONFIG_PATH = CONFIG_DIR / "litellm.yaml"
ENV_PATH = CONFIG_DIR / ".env"
STATE_PATH = CONFIG_DIR / "config.json"
DEFAULT_PROMPT_PATH = CONFIG_DIR / "default-prompt.txt"


def read_text_compat(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
    last_error = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text(encoding="utf-8")


def ensure_config_dir() -> Path:
    _migrate_legacy_config_dir()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def _migrate_legacy_config_dir() -> None:
    """
    One-way copy from legacy ~/.claude-ext into ~/.moonclaude.
    """
    if CONFIG_DIR.exists() or not LEGACY_CONFIG_DIR.exists():
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    filenames = [
        "litellm.yaml",
        ".env",
        "config.json",
        "openrouter-models.json",
        "project-memory.md",
        "load-env.sh",
        "load-env.ps1",
        "load-env.bat",
        "run-claude.sh",
        "run-claude.ps1",
        "run-claude.bat",
        "start-proxy.sh",
        "start-proxy.ps1",
        "start-proxy.bat",
    ]

    for filename in filenames:
        src = LEGACY_CONFIG_DIR / filename
        dst = CONFIG_DIR / filename
        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue

    src_projects = LEGACY_CONFIG_DIR / "projects"
    dst_projects = CONFIG_DIR / "projects"
    if src_projects.exists() and not dst_projects.exists():
        try:
            shutil.copytree(src_projects, dst_projects)
        except OSError:
            pass


def build_litellm_config(primary_model: dict, extra_models: list, api_keys: dict, port: int, full_catalog: list | None = None) -> dict:
    model_list = []

    params = {
        "model": primary_model["litellm_model"],
        "api_key": f"os.environ/{_key_env_for(primary_model, api_keys)}",
        "extra_body": {
            "provider": {
                "data_collection": "deny" if primary_model.get("zdr") else "allow"
            }
        },
        "extra_headers": {
            "HTTP-Referer": "https://github.com/sunil/moonclaude",
            "X-Title": "MoonClaude CLI",
        },
    }

    for alias in CLAUDE_ALIASES:
        model_list.append({"model_name": alias, "litellm_params": dict(params)})

    # Register all available models natively so the dynamic router can hit them without error
    # We include EVERY model from the catalog so seamless switching never hits "no healthy deployments"
    registry = [primary_model] + extra_models
    if full_catalog:
        registry += full_catalog
        
    seen_model_names = set()
    for m in registry:
        m_name = m["litellm_model"]
        if m_name in seen_model_names:
            continue
        seen_model_names.add(m_name)
        
        m_params = {
            "model": m_name,
            "api_key": f"os.environ/{_key_env_for(m, api_keys)}",
            "extra_body": {
                "provider": {
                    "data_collection": "deny" if m.get("zdr") else "allow"
                }
            },
            "extra_headers": {
                "HTTP-Referer": "https://github.com/sunil/moonclaude",
                "X-Title": "MoonClaude CLI",
            },
        }
        model_list.append({
            "model_name": m_name,
            "litellm_params": m_params
        })
        
        # Also register model_id as an alias if it differs
        m_id = m["model_id"]
        if m_id != m_name and m_id not in seen_model_names:
            model_list.append({
                "model_name": m_id,
                "litellm_params": m_params
            })
            seen_model_names.add(m_id)

    return {
        "model_list": model_list,
        "general_settings": {
            "completion_model": CLAUDE_ALIASES[0],
        },
        "litellm_settings": {
            "drop_params": True,
            "set_verbose": False,
            "watch_config": True,
            "callbacks": ["moonclaude.proxy_logging.moon_usage_logger"],
        },
        "router_settings": {
            "routing_strategy": "simple-shuffle",
            "disable_cooldowns": True,
        },
    }


def _key_env_for(model: dict, api_keys: dict) -> str:
    litellm_model = model["litellm_model"]
    if litellm_model.startswith("openrouter/"):
        return "OPENROUTER_API_KEY"
    if litellm_model.startswith("gemini/"):
        return "GEMINI_API_KEY"
    if litellm_model.startswith("groq/"):
        return "GROQ_API_KEY"
    return list(api_keys.keys())[0]


def write_litellm_config(config: dict) -> Path:
    ensure_config_dir()
    with open(LITELLM_CONFIG_PATH, "w", encoding="utf-8") as handle:
        yaml.dump(config, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)
    ensure_proxy_callback_module(LITELLM_CONFIG_PATH)
    return LITELLM_CONFIG_PATH


def switch_primary_model(new_model: dict, state: dict) -> dict:
    """
    Hot-swap the primary model: rewrites litellm.yaml so all Claude aliases
    point to the new model, and updates the persisted state.
    """
    config_path = Path(state.get("config_path", str(LITELLM_CONFIG_PATH)))
    api_keys = {}
    _, env = _load_env(state)
    litellm_model = new_model.get("litellm_model", "")

    # Determine the API key env var
    key_env = _key_env_for(new_model, {})
    api_key_ref = f"os.environ/{key_env}"

    # Read existing config
    if config_path.exists():
        config = yaml.safe_load(read_text_compat(config_path)) or {}
    else:
        config = {}

    # Rebuild model_list: all Claude aliases -> new model, keep extras
    new_model_list = []
    seen_aliases = set()

    for alias in CLAUDE_ALIASES:
        new_model_list.append({
            "model_name": alias,
            "litellm_params": {
                "model": litellm_model,
                "api_key": api_key_ref,
                "extra_body": {
                    "provider": {
                        "data_collection": "deny" if new_model.get("zdr") else "allow"
                    }
                },
                "extra_headers": {
                    "HTTP-Referer": "https://github.com/sunil/moonclaude",
                    "X-Title": "MoonClaude CLI",
                },
            },
        })
        seen_aliases.add(alias)

    # Add the model under its own name too
    new_model_list.append({
        "model_name": new_model["model_id"],
        "litellm_params": {
            "model": litellm_model,
            "api_key": api_key_ref,
            "extra_body": {
                "provider": {
                    "data_collection": "deny" if new_model.get("zdr") else "allow"
                }
            },
            "extra_headers": {
                "HTTP-Referer": "https://github.com/sunil/moonclaude",
                "X-Title": "MoonClaude CLI",
            },
        },
    })

    # Preserve any extra models that aren't Claude aliases or the old primary
    old_primary_id = state.get("primary_model_id", "")
    for entry in config.get("model_list", []):
        name = entry.get("model_name", "")
        if name in seen_aliases or name == old_primary_id or name == new_model["model_id"]:
            continue
        new_model_list.append(entry)
        
    # Inject all configured models into the background router so hot-reloads never fail
    existing_names = {x.get("model_name") for x in new_model_list}
    for m in state.get("configured_models", []):
        m_name = m["litellm_model"]
        if m_name not in existing_names and m_name != new_model["model_id"]:
            new_model_list.append({
                "model_name": m_name,
                "litellm_params": {
                    "model": m_name,
                    "api_key": f"os.environ/{_key_env_for(m, api_keys)}",
                    "extra_body": {
                        "provider": {"data_collection": "deny" if m.get("zdr") else "allow"}
                    },
                    "extra_headers": {
                        "HTTP-Referer": "https://github.com/sunil/moonclaude",
                        "X-Title": "MoonClaude CLI",
                    },
                }
            })
            existing_names.add(m_name)

    config["model_list"] = new_model_list
    config.setdefault("general_settings", {})["completion_model"] = CLAUDE_ALIASES[0]
    config.setdefault("litellm_settings", {})["drop_params"] = True
    config.setdefault("litellm_settings", {})["set_verbose"] = False
    config.setdefault("litellm_settings", {})["watch_config"] = True
    config.setdefault("litellm_settings", {}).setdefault("callbacks", [])
    if "moonclaude.proxy_logging.moon_usage_logger" not in config["litellm_settings"]["callbacks"]:
        config["litellm_settings"]["callbacks"].append("moonclaude.proxy_logging.moon_usage_logger")

    config.setdefault("router_settings", {})["routing_strategy"] = "simple-shuffle"
    config.setdefault("router_settings", {})["disable_cooldowns"] = True

    # Write config
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.dump(config, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)
    ensure_proxy_callback_module(config_path)

    # Update state
    state["primary_model_id"] = new_model["model_id"]
    state["primary_model_name"] = new_model["name"]

    # Update configured_models list
    configured = state.get("configured_models", [])
    # Ensure new model is in the list
    if not any(m.get("model_id") == new_model["model_id"] for m in configured):
        configured.append(new_model)
        state["configured_models"] = configured

    write_state(state)
    return state


def _load_env(state: dict) -> tuple[Path, dict]:
    """Load env for key resolution."""
    import os
    env_path = Path(state.get("env_path", str(ENV_PATH)))
    env = os.environ.copy()
    if env_path.exists():
        for line in read_text_compat(env_path).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env_path, env


def write_env_file(api_keys: dict, port: int) -> Path:
    ensure_config_dir()
    lines = [
        "# moonclaude environment",
        "# Use generated helper scripts in this folder to load these values.",
        f"LITELLM_PORT={port}",
        "",
        "# API Keys",
    ]
    for key, value in api_keys.items():
        lines.append(f"{key}={value}")

    lines += [
        "",
        "# Claude Code routing",
        f"ANTHROPIC_BASE_URL=http://localhost:{port}",
        "ANTHROPIC_API_KEY=moonclaude-local",
    ]

    with open(ENV_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    os.chmod(ENV_PATH, 0o600)
    return ENV_PATH


def write_helper_scripts(port: int, config_path: Path | None = None, env_path: Path | None = None) -> dict:
    config_path = Path(config_path or LITELLM_CONFIG_PATH)
    env_path = Path(env_path or ENV_PATH)
    ensure_config_dir()
    return write_shell_helpers(CONFIG_DIR, env_path, config_path, port)


def ensure_proxy_callback_module(config_path: Path | str | None = None) -> None:
    """
    LiteLLM resolves custom callback imports relative to config file directory.
    Mirror moonclaude.proxy_logging into that directory so callbacks load reliably.
    """
    config_path = Path(config_path or LITELLM_CONFIG_PATH)
    callback_pkg_dir = config_path.parent / "moonclaude"
    callback_pkg_dir.mkdir(parents=True, exist_ok=True)

    init_path = callback_pkg_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("", encoding="utf-8")

    source_proxy_logging = Path(__file__).resolve().parent / "proxy_logging.py"
    target_proxy_logging = callback_pkg_dir / "proxy_logging.py"
    content = source_proxy_logging.read_text(encoding="utf-8")
    if target_proxy_logging.exists():
        try:
            existing = target_proxy_logging.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return
    target_proxy_logging.write_text(content, encoding="utf-8")


def migrate_state_models(state: dict) -> tuple[dict, bool]:
    model_id = state.get("primary_model_id")
    migration = LEGACY_MODEL_MIGRATIONS.get(model_id)
    if migration is None:
        return state, False

    state["primary_model_id"] = migration["model_id"]
    state["primary_model_name"] = migration["name"]

    configured = []
    for model in state.get("configured_models", []):
        if model.get("model_id") == model_id:
            configured.append(
                {
                    "name": migration["name"],
                    "model_id": migration["model_id"],
                    "litellm_model": migration["litellm_model"],
                    "free": model.get("free", True),
                }
            )
        else:
            configured.append(model)
    if configured:
        state["configured_models"] = configured

    return state, True


def migrate_litellm_config(path: Path | str) -> bool:
    config_path = Path(path)
    if not config_path.exists():
        return False

    config = yaml.safe_load(read_text_compat(config_path)) or {}
    changed = False

    for entry in config.get("model_list", []):
        model_name = entry.get("model_name")
        if model_name in LEGACY_MODEL_MIGRATIONS:
            entry["model_name"] = LEGACY_MODEL_MIGRATIONS[model_name]["model_id"]
            changed = True

        litellm_params = entry.get("litellm_params", {})
        litellm_model = litellm_params.get("model")
        if litellm_model in LEGACY_LITELLM_MODEL_MIGRATIONS:
            litellm_params["model"] = LEGACY_LITELLM_MODEL_MIGRATIONS[litellm_model]
            changed = True

    litellm_settings = config.setdefault("litellm_settings", {})
    callbacks = litellm_settings.get("callbacks", [])
    if isinstance(callbacks, str):
        callbacks = [callbacks]
    if "moonclaude.proxy_logging.moon_usage_logger" not in callbacks:
        callbacks.append("moonclaude.proxy_logging.moon_usage_logger")
        litellm_settings["callbacks"] = callbacks
        changed = True

    if changed:
        with open(config_path, "w", encoding="utf-8") as handle:
            yaml.dump(config, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)

    ensure_proxy_callback_module(config_path)
    return changed


def sync_all_configured_models_to_yaml(state: dict, full_catalog: list | None = None) -> None:
    """Inject all known models into litellm.yaml so the dynamic router finds them."""
    config_path = Path(state.get("config_path", str(LITELLM_CONFIG_PATH)))
    if not config_path.exists():
        return
    config = yaml.safe_load(read_text_compat(config_path)) or {}
    models_dict = {m.get("model_name"): m for m in config.get("model_list", [])}
    
    api_keys = {}
    _, env = _load_env(state)
    changed = False
    
    registry = list(state.get("configured_models", []))
    if full_catalog:
        registry += full_catalog
        
    for model in registry:
        model_name = model["litellm_model"]
        if model_name not in models_dict:
            m_params = {
                "model": model_name,
                "api_key": f"os.environ/{_key_env_for(model, api_keys)}",
                "extra_body": {
                    "provider": {
                        "data_collection": "deny" if model.get("zdr") else "allow"
                    }
                },
                "extra_headers": {
                    "HTTP-Referer": "https://github.com/sunil/moonclaude",
                    "X-Title": "MoonClaude CLI",
                },
            }
            config.setdefault("model_list", []).append({
                "model_name": model_name,
                "litellm_params": m_params
            })
            models_dict[model_name] = True
            changed = True
            
    # Ensure hot-reload settings are preserved
    litellm_settings = config.setdefault("litellm_settings", {})
    if litellm_settings.get("watch_config") is not True:
        litellm_settings["watch_config"] = True
        changed = True

    router_settings = config.setdefault("router_settings", {})
    if router_settings.get("disable_cooldowns") is not True:
        router_settings["disable_cooldowns"] = True
        router_settings["routing_strategy"] = "simple-shuffle"
        changed = True

    if changed:
        with open(config_path, "w", encoding="utf-8") as handle:
            yaml.dump(config, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)


def write_default_prompt(text: str) -> Path:
    ensure_config_dir()
    DEFAULT_PROMPT_PATH.write_text(text.strip() + "\n", encoding="utf-8")
    return DEFAULT_PROMPT_PATH


def read_default_prompt() -> str:
    ensure_config_dir()
    if not DEFAULT_PROMPT_PATH.exists():
        return ""
    return read_text_compat(DEFAULT_PROMPT_PATH).strip()


def write_state(state: dict) -> None:
    ensure_config_dir()
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
    os.chmod(STATE_PATH, 0o600)


def read_state() -> dict:
    ensure_config_dir()
    legacy_state_path = LEGACY_CONFIG_DIR / "config.json"
    source_path = STATE_PATH if STATE_PATH.exists() else legacy_state_path

    if not source_path.exists():
        return {}

    state = json.loads(read_text_compat(source_path))
    changed = source_path != STATE_PATH

    state, migrated = migrate_state_models(state)
    changed = changed or migrated

    if "configured_models" not in state:
        primary_model_id = state.get("primary_model_id")
        primary_model_name = state.get("primary_model_name")
        if primary_model_id and primary_model_name:
            state["configured_models"] = [
                {
                    "name": primary_model_name,
                    "model_id": primary_model_id,
                    "litellm_model": f"openrouter/{primary_model_id}",
                    "free": primary_model_id.endswith(":free"),
                }
            ]
            changed = True

    if "default_prompt_enabled" not in state:
        state["default_prompt_enabled"] = False
        changed = True

    if "default_prompt_text" not in state:
        state["default_prompt_text"] = read_default_prompt()
        changed = changed or bool(state["default_prompt_text"])

    if "port" not in state:
        state["port"] = DEFAULT_PORT
        changed = True

    if "config_path" not in state:
        state["config_path"] = str(LITELLM_CONFIG_PATH)
        changed = True

    if "env_path" not in state:
        state["env_path"] = str(ENV_PATH)
        changed = True

    if changed:
        write_state(state)

    return state
