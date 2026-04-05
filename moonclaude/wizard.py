"""
MoonClaude setup wizard.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .branding import CLI_ALIAS, CLI_NAME, DEFAULT_PORT
from .config import (
    CONFIG_DIR,
    ENV_PATH,
    LITELLM_CONFIG_PATH,
    build_litellm_config,
    write_default_prompt,
    write_env_file,
    write_helper_scripts,
    write_litellm_config,
    write_state,
    read_state,
)
from .models import ModelCatalogError, get_provider, get_provider_names
from .shells import get_shell_commands
from .ui import console, BOLD, CYAN, DIM, GREEN, RED, YELLOW, c, confirm, error, info, prompt, section, select, step, success, warn


TOTAL_STEPS = 6


def check_dependencies():
    missing = []
    if shutil.which("litellm") is None:
        missing.append(("litellm", "pip install 'litellm[proxy]'"))
    if shutil.which("claude") is None:
        missing.append(("claude", "npm install -g @anthropic-ai/claude-code"))
    return missing


def run_setup():
    section("Dependency Check")
    missing = check_dependencies()
    if missing:
        warn("Some required tools are not installed:\n")
        for tool, install_cmd in missing:
            console.print(f"    {c('[x]', RED, BOLD)} {c(tool, BOLD)} - install with: {c(install_cmd, CYAN)}")
        console.print()
        if not confirm("Continue anyway?", default=False):
            info(f"Run installs above, then re-run: {CLI_ALIAS} setup")
            sys.exit(0)
    else:
        success("litellm found")
        success("claude found")

    state = read_state()
    if state:
        section("Existing Configuration Found")
        info(f"Provider : {state.get('provider', 'unknown')}")
        info(f"Model    : {state.get('primary_model_name', 'unknown')}")
        info(f"Port     : {state.get('port', DEFAULT_PORT)}")
        console.print()
        if not confirm("Reconfigure?", default=False):
            write_helper_scripts(
                state.get("port", DEFAULT_PORT),
                config_path=Path(state.get("config_path", str(LITELLM_CONFIG_PATH))),
                env_path=Path(state.get("env_path", str(ENV_PATH))),
            )
            _show_start_instructions(state)
            return

    step(1, TOTAL_STEPS, "Choose provider")
    provider_names = get_provider_names()
    provider_descs = [
        "Route any model via OpenRouter (recommended)",
        "Google Gemini directly",
        "Groq low-latency inference",
    ]
    provider_index = select("Select provider", provider_names, provider_descs)
    provider_name = provider_names[provider_index]
    try:
        provider = get_provider(provider_name)
    except ModelCatalogError as exc:
        error(str(exc))
        sys.exit(1)

    success(f"Provider: {provider_name}")
    if provider_name == "OpenRouter" and provider.get("catalog_source") == "cache":
        warn("Using cached OpenRouter model catalog because live fetch was unavailable.")

    step(2, TOTAL_STEPS, "Choose active model")
    models = provider["models"]
    if not models:
        error(f"No models available for {provider_name}.")
        sys.exit(1)

    labels = []
    descs = []
    for model in models:
        tag = c(" FREE", GREEN, BOLD) if model["free"] else c(" PAID", YELLOW, BOLD)
        labels.append(model["name"] + tag)
        descs.append(model["model_id"])
    primary_index = select("Active model", labels, descs)
    primary_model = models[primary_index]
    success(f"Active model: {primary_model['name']}")

    step(3, TOTAL_STEPS, "Add switchable models (optional)")
    configured_models = [primary_model]
    if confirm("Add more models so you can switch later?", default=True):
        remaining = [m for idx, m in enumerate(models) if idx != primary_index]
        if remaining:
            rlabels = []
            rdescs = []
            for model in remaining:
                tag = c(" FREE", GREEN, BOLD) if model["free"] else c(" PAID", YELLOW, BOLD)
                rlabels.append(model["name"] + tag)
                rdescs.append(model["model_id"])
            selected = select("Select additional models", rlabels, rdescs, multi=True)
            for idx in selected:
                configured_models.append(remaining[idx])
            success(f"Added {len(configured_models) - 1} additional model(s)")

    step(4, TOTAL_STEPS, "API key")
    api_keys = {}
    key_env = provider["key_env"]
    key_label = provider["key_label"]
    key_url = provider["key_url"]
    existing_key = os.environ.get(key_env, "")

    info(f"Get key: {c(key_url, CYAN)}")
    if existing_key:
        masked = existing_key[:6] + "..." + existing_key[-4:]
        info(f"Found existing {key_env}: {c(masked, DIM)}")
        if confirm("Use this key?", default=True):
            api_keys[key_env] = existing_key
        else:
            api_keys[key_env] = prompt(key_label, secret=True)
    else:
        value = prompt(key_label, secret=True)
        if not value:
            error("API key cannot be empty.")
            sys.exit(1)
        api_keys[key_env] = value
    success(f"{key_env} saved")

    step(5, TOTAL_STEPS, "Persistent default prompt (optional)")
    default_prompt_enabled = confirm(
        "Always prepend your custom instruction to every Claude session?",
        default=False,
    )
    default_prompt_text = ""
    if default_prompt_enabled:
        default_prompt_text = prompt("Enter default instruction")
        if not default_prompt_text:
            default_prompt_enabled = False
            warn("No instruction entered. Persistent prompt disabled.")
        else:
            success("Persistent instruction enabled.")

    step(6, TOTAL_STEPS, "Write config")
    port_raw = prompt("LiteLLM proxy port", default=str(DEFAULT_PORT))
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_PORT
        warn(f"Invalid port. Using default {DEFAULT_PORT}.")

    extra_models = [m for m in configured_models if m["model_id"] != primary_model["model_id"]]
    litellm_config = build_litellm_config(primary_model, extra_models, api_keys, port)
    config_path = write_litellm_config(litellm_config)
    env_path = write_env_file(api_keys, port)
    write_helper_scripts(port, config_path=config_path, env_path=env_path)

    state = {
        "provider": provider_name,
        "primary_model_name": primary_model["name"],
        "primary_model_id": primary_model["model_id"],
        "configured_models": configured_models,
        "port": port,
        "key_env": key_env,
        "config_path": str(config_path),
        "env_path": str(env_path),
        "default_prompt_enabled": default_prompt_enabled,
        "default_prompt_text": default_prompt_text.strip(),
    }
    write_default_prompt(default_prompt_text.strip())
    write_state(state)

    console.print()
    success(f"litellm.yaml -> {c(str(config_path), CYAN)}")
    success(f".env        -> {c(str(env_path), CYAN)}")
    _show_start_instructions(state)


def _show_start_instructions(state: dict):
    shell_commands = get_shell_commands(CONFIG_DIR)
    port = state.get("port", DEFAULT_PORT)

    section("MoonClaude Ready")
    console.print(f"  {c('Fast path', BOLD)} - run everything with one command:\n")
    console.print(f"    {c(CLI_ALIAS, CYAN, BOLD)}\n")

    console.print(f"  {c('Manual path', BOLD)} - if you want explicit control:\n")
    console.print(f"    {c(shell_commands['start_proxy'], CYAN)}")
    console.print(f"    {c(shell_commands['run_moon'], CYAN)}\n")

    console.print(f"  {c('Other helpful commands', DIM)}\n")
    console.print(f"    {c(f'{CLI_ALIAS} switch', CYAN)}")
    console.print(f"    {c(f'{CLI_ALIAS} prompt', CYAN)}")
    console.print(f"    {c(f'{CLI_ALIAS} env --shell powershell', CYAN)}")
    console.print()

    info(f"Primary model : {c(state.get('primary_model_name', '?'), BOLD)}")
    info(f"Proxy URL     : {c(f'http://localhost:{port}', BOLD)}")
