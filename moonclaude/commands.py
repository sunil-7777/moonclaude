"""
MoonClaude commands.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from .branding import CLI_ALIAS, CLI_NAME, DEFAULT_PORT
from .config import (
    CLAUDE_ALIASES,
    CONFIG_DIR,
    ENV_PATH,
    LITELLM_CONFIG_PATH,
    build_litellm_config,
    ensure_proxy_callback_module,
    migrate_litellm_config,
    read_state,
    read_text_compat,
    switch_primary_model,
    sync_all_configured_models_to_yaml,
    write_default_prompt,
    write_helper_scripts,
    write_litellm_config,
    write_state,
)
from .memory import (
    build_memory_prompt,
    build_project_memory,
    claude_project_dir,
    detect_project_root,
    ensure_project_settings,
    get_session_summaries,
    latest_project_session_id,
    moon_project_dir,
    should_auto_resume,
)
from .models import ModelCatalogError, get_provider, get_provider_names
from .shells import get_shell_commands
from .ui import (
    console,
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    BRIGHT,
    c,
    card,
    error,
    T_ERR,
    T_INFO,
    T_SUCCESS,
    T_WARN,
    T_DIM,
    hint,
    info,
    ok,
    section,
    select,
    spin_line,
    success,
    warn,
)


def _prepare_proxy_env(env: dict) -> dict:
    proxy_env = env.copy()
    proxy_env.setdefault("PYTHONIOENCODING", "utf-8")
    proxy_env.setdefault("PYTHONUTF8", "1")
    proxy_env.setdefault("PYTHONUNBUFFERED", "1")
    return proxy_env


class _MoonEventRenderer:
    EVENT_PREFIX = "[moon:event] "

    def __init__(self):
        self.footer_visible = False
        self.events_total = 0
        self.success_total = 0
        self.failure_total = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0

    def handle_line(self, raw_line: str) -> bool:
        payload = self._parse_event(raw_line)
        if payload is None:
            return False
        self._render_event(payload)
        return True

    def emit_passthrough(self, raw_line: str, markup: bool = False) -> None:
        if self.footer_visible:
            sys.stdout.write("\r\033[2K")
        console.print(raw_line, markup=markup, highlight=False)
        if self.footer_visible:
            self._draw_footer()

    def finish(self) -> None:
        if self.footer_visible:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.footer_visible = False

    def _parse_event(self, raw_line: str) -> dict | None:
        if not raw_line.startswith(self.EVENT_PREFIX):
            return None
        payload_text = raw_line[len(self.EVENT_PREFIX) :].strip()
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _render_event(self, payload: dict) -> None:
        status = str(payload.get("status") or "failure")
        event_id = int(payload.get("id") or 0)
        req_name = str(payload.get("req_name") or "request")
        res_name = str(payload.get("res_name") or "response")

        def _shorten(text: str, max_words: int = 6) -> str:
            import re
            # Completely strip <system-reminder> blocks and their content (Claude Code injects this constantly)
            cleaned = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL | re.IGNORECASE)
            # Strip bare tags
            cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
            words = cleaned.split()
            if not words: return "..."
            return " ".join(words[:max_words]) + ("..." if len(words) > max_words else "")

        req_snippet = _shorten(req_name, max_words=6)
        res_snippet = _shorten(res_name, max_words=12 if status != "success" else 6)

        prompt_tokens = int(payload.get("prompt_tokens") or 0)
        completion_tokens = int(payload.get("completion_tokens") or 0)
        model_name = str(payload.get("actual_model") or payload.get("requested_model") or "unknown")

        self.events_total += 1
        if status == "success":
            self.success_total += 1
            self.prompt_tokens_total += prompt_tokens
            self.completion_tokens_total += completion_tokens
        else:
            self.failure_total += 1

        if self.footer_visible:
            sys.stdout.write("\r\033[2K")

        if status == "success":
            line = (
                f" [#a855f7]✦[/] [#52525b]Req {event_id:04d}[/] "
                f"[#3b82f6]User:[/] [#e4e4e7]{req_snippet}[/] "
                f"[#52525b]›[/] "
                f"[#ec4899]AI:[/] [#e4e4e7]{res_snippet}[/] "
                f"[#52525b]│[/] [#06b6d4]{model_name}[/] "
                f"[#52525b]│[/] [#a855f7]{prompt_tokens}↑ {completion_tokens}↓[/]"
            )
        else:
            line = (
                f" [#ef4444]✖[/] [#52525b]Req {event_id:04d}[/] "
                f"[#3b82f6]User:[/] [#e4e4e7]{req_snippet}[/] "
                f"[#52525b]›[/] [#ef4444]failed:[/] [#f87171]{res_snippet}[/] "
                f"[#52525b]│[/] [#06b6d4]{model_name}[/]"
            )

        console.print(line)
        self._draw_footer()
        self.footer_visible = True

    def _draw_footer(self) -> None:
        total_tokens = self.prompt_tokens_total + self.completion_tokens_total
        from .ui import console
        footer = (
            f"[#3b82f6]proxy ✦ {self.events_total} reqs[/]          "
            f"[#ec4899]{self.success_total} ok / {self.failure_total} fail[/]          "
            f"[#8b5cf6]{total_tokens} tokens[/]"
        )
        # We manually issue carriage return and line clear \r\033[2K
        console.print(f"\r\033[2K{footer}", end="", markup=True)


def _model_display_pairs(config_path: str | Path) -> list[tuple[str, str]]:
    path = Path(config_path)
    if not path.exists():
        return []
    try:
        config = yaml.safe_load(read_text_compat(path)) or {}
    except Exception:
        return []

    from .config import CLAUDE_ALIASES
    
    pairs: list[tuple[str, str]] = []
    
    primary_actual = None
    for entry in config.get("model_list", []):
        model_name = str(entry.get("model_name") or "").strip()
        actual = str((entry.get("litellm_params") or {}).get("model") or "").strip()
        if model_name in CLAUDE_ALIASES:
            primary_actual = actual
            break

    for entry in config.get("model_list", []):
        model_name = str(entry.get("model_name") or "").strip()
        actual = str((entry.get("litellm_params") or {}).get("model") or "").strip()
        
        if model_name and actual:
            if model_name in CLAUDE_ALIASES or (primary_actual and actual == primary_actual and model_name == primary_actual.replace("openrouter/", "")):
                pairs.append((model_name, actual))
                
    return pairs


def _model_display_map(config_path: str | Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for model_name, actual in _model_display_pairs(config_path):
        mapping[model_name] = actual
    return mapping


def _check_alt_m() -> bool:
    """Non-blocking check for Alt+M keypress. Cross-platform.
    Windows: msvcrt returns \x00 followed by scancode 0x32 for Alt+M.
    Unix: Alt+M sends ESC (0x1b) followed by 'm'.
    Falls back to plain 'm' on Windows since Alt+M may not work in all terminals.
    """
    if os.name == "nt":
        import msvcrt
        if not msvcrt.kbhit():
            return False
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):
            # Extended key — read the scancode
            if msvcrt.kbhit():
                scancode = msvcrt.getch()
                return scancode == b'\x32'  # Alt+M scancode
            return False
        # Accept plain 'm' on Windows (Alt+M may not produce extended codes in all terminals)
        return ch.lower() == b'm'
    else:
        import select as _select
        rlist, _, _ = _select.select([sys.stdin], [], [], 0)
        if not rlist:
            return False
        ch = sys.stdin.read(1)
        if ch == '\x1b':  # ESC — could be Alt+M sequence
            rlist2, _, _ = _select.select([sys.stdin], [], [], 0.05)
            if rlist2:
                ch2 = sys.stdin.read(1)
                return ch2.lower() == 'm'
            return False
        return False


def _hot_reload_models(port: int, new_model: dict, state: dict) -> bool:
    """Update config files for the new model."""
    switch_primary_model(new_model, state)
    return True


def _pick_model_interactive(state: dict) -> dict | None:
    """Show a model picker overlay and return the selected model dict, or None if cancelled."""
    from .ui import console, T_INFO, T_DIM

    # Gather models from configured_models + fresh OpenRouter catalog
    configured = list(state.get("configured_models", []))
    current_id = state.get("primary_model_id", "")

    # Try to load fresh models from OpenRouter
    try:
        from .models import load_openrouter_free_models
        openrouter_models, _ = load_openrouter_free_models()
        # Merge: add any OpenRouter model not already in configured
        configured_ids = {m.get("model_id") for m in configured}
        for m in openrouter_models:
            if m["model_id"] not in configured_ids:
                configured.append(m)
    except Exception:
        pass  # Use only configured models if catalog fetch fails

    if not configured:
        console.print(f" [{T_INFO}]⚠[/] No models available to switch to.")
        return None

    # Sort: tool-supporting models first, then alphabetical
    configured.sort(key=lambda m: (not m.get("supports_tools", False), m.get("name", "").casefold()))

    console.print()
    console.print(f" [bold #a78bfa]Model Switcher[/]  [dim]Press number to select, [bold]q[/bold] to cancel[/]")
    console.print(f" [dim]{'─' * 60}[/]")

    for i, m in enumerate(configured, 1):
        name = m.get("name", m.get("model_id", "?"))
        mid = m.get("model_id", "")
        is_current = mid == current_id

        # Tools tag
        supports_tools = m.get("supports_tools")
        if supports_tools is True:
            tool_tag = f" [#22c55e]⚡tools[/]"
        elif supports_tools is False:
            tool_tag = f" [{T_WARN}]⚠ no-tools[/]"
        else:
            tool_tag = f" [dim]◌ unknown[/]"

        # ZDR tag (Zero Data Retention)
        is_zdr = m.get("zdr", False)
        if is_zdr:
            zdr_tag = f" [#a855f7]🛡️ZDR[/]"
        else:
            zdr_tag = f" [dim]◌ no-zdr[/]"

        current_badge = " [bold #f59e0b]← active[/]" if is_current else ""
        num_color = "#3b82f6" if supports_tools is not False else "#52525b"

        console.print(
            f"  [{num_color}]{i:>2}[/] [bold white]{name}[/] {tool_tag}{zdr_tag}{current_badge}",
            markup=True,
        )

    console.print(f" [dim]{'─' * 60}[/]")
    console.print(f" [dim]Select [bold]1-{len(configured)}[/dim]: ", end="")

    # Read input
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if raw.lower() == "q" or not raw:
        console.print(f" [{T_DIM}]Cancelled.[/]")
        return None

    try:
        idx = int(raw) - 1
    except ValueError:
        console.print(f" [#ef4444]Invalid selection.[/]")
        return None

    if idx < 0 or idx >= len(configured):
        console.print(f" [#ef4444]Out of range.[/]")
        return None

    selected = configured[idx]
    if selected.get("model_id") == current_id:
        console.print(f" [{T_DIM}]Rebuilding config for currently active model...[/]")
        return selected

    return selected


def _stream_litellm_logs(command: list[str], env: dict, config_path: str | Path | None = None, state: dict | None = None) -> int:
    import queue
    import threading
    import time

    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    renderer = _MoonEventRenderer()
    in_model_list_block = False

    from .ui import console, T_INFO, T_DIM
    status = console.status(" [dim]Starting MoonClaude Engine...[/]", spinner="dots")
    status.start()
    is_ready = False

    # Threaded reader to prevent blocking the keyboard check
    log_queue = queue.Queue()

    def reader_thread(pipe, q):
        try:
            for line in pipe:
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)  # Sentinel for EOF

    if process.stdout is None:
        return process.wait()

    t = threading.Thread(target=reader_thread, args=(process.stdout, log_queue), daemon=True)
    t.start()

    try:
        while True:
            # 1. Check for keyboard input (Alt+M)
            if is_ready and state is not None:
                try:
                    if _check_alt_m():
                        renderer.finish()
                        selected = _pick_model_interactive(state)
                        if selected is not None:
                            port = int(state.get("port", DEFAULT_PORT))
                            _hot_reload_models(port, selected, state)
                            state = read_state() or state
                            console.print(f" [{T_INFO}]✦[/] [bold white]Model switched to {selected.get('name', '?')}[/] [{T_DIM}](applied seamlessly)[/]")
                            # The proxy stays running! `proxy_logging.py` dynamically routes based on state.json!
                except Exception:
                    pass

            # 2. Check for new log lines
            try:
                line = log_queue.get_nowait()
                if line is None:  # EOF
                    break
                
                stripped = line.rstrip("\r\n")

                if not is_ready and "Uvicorn running on http" in stripped:
                    status.stop()
                    is_ready = True
                    console.print(f" [{T_INFO}]✦[/] [bold white]MoonClaude Engine[/] [{T_DIM}]is online and routing requests.[/]")
                    console.print(f" [{T_DIM}]   Press [bold]Alt+M[/bold] to switch models[/]")
                    continue

                if renderer.handle_line(stripped):
                    continue

                if _should_suppress_litellm_line(stripped):
                    continue

                # Once an unsuppressed line appears (e.g. an error traceback or server warning), halt the spinner
                if not is_ready:
                    status.stop()
                    is_ready = True

                renderer.emit_passthrough(stripped, markup=False)

            except queue.Empty:
                # No new logs, sleep briefly to avoid high CPU
                time.sleep(0.05)

            # Check if process died
            if process.poll() is not None and log_queue.empty():
                break

    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    finally:
        renderer.finish()
        if process.stdout is not None:
            process.stdout.close()
    return process.wait()


def _should_suppress_litellm_line(line: str) -> bool:
    """Aggressively suppress LiteLLM noise for a premium brand feel."""
    import re
    # LiteLLM formats with ANSI colors which dodge starts/endswith checks
    clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)
    stripped = clean_line.strip()

    if not stripped:
        return True

    # Suppress raw python stacktraces and LiteLLM trace cascades
    traceback_noise = (
        "Traceback (most recent call last):",
        "During handling of the above exception, another exception occurred:",
        "httpx.HTTPStatusError:",
        "litellm.exceptions.",
        "litellm.types.router.",
        "litellm.llms.openrouter.",
        "LiteLLM Proxy:ERROR:",
        "Available Model Group Fallbacks=",
        "Received Model Group=",
        "For more information check:",
    )
    if any(token in stripped for token in traceback_noise):
        return True
        
    if stripped.startswith('File "') and '", line ' in stripped:
        return True

    # Check for empty boxes OR strings enclosed in boxes (since LiteLLM often markets in boxes)
    if stripped.startswith("#") and stripped.endswith("#"):
        return True

    if stripped.startswith("██") or stripped.startswith("╚") or stripped.startswith("╔"):
        return True

    if "LiteLLM: Proxy initialized" in stripped:
        return True

    noise = (
        "Thank you for using LiteLLM",
        "Give Feedback / Get Help",
        "https://github.com/BerriAI/litellm",
        "LITELLM_MASTER_KEY is not set",
        "Started server process",
        "Waiting for application startup",
        "Application startup complete",
        "treated as INTERNAL_USER",
        "Set LITELLM_MASTER_KEY for production use",
    )
    if any(token in line for token in noise):
        return True

    # Suppress bare model aliases (indentation with no colon/info)
    if clean_line.startswith("    ") and "->" not in clean_line and "File" not in clean_line:
        return True

    # Suppress Uvicorn ready message (handled explicitly in the stream loop for the spinner stop)
    if "Uvicorn running on http" in line:
        return True

    # Only show actual errors or true application traces
    if "ERROR" in line or "CRITICAL" in line or "Traceback" in line or "Exception" in line:
        return False

    # Hide all other INFO/DEBUG logs to maintain a clean UI
    if "INFO:" in line or "DEBUG:" in line:
        return True

    return False


def _load_saved_env(state: dict) -> tuple[Path, dict]:
    env_path = Path(state.get("env_path", str(ENV_PATH)))
    env = os.environ.copy()

    if env_path.exists():
        for line in read_text_compat(env_path).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

    return env_path, env


def _ensure_shell_helpers(state: dict) -> dict:
    port = state.get("port", DEFAULT_PORT)
    config_path = Path(state.get("config_path", str(LITELLM_CONFIG_PATH)))
    env_path = Path(state.get("env_path", str(ENV_PATH)))
    return write_helper_scripts(port, config_path=config_path, env_path=env_path)


def _proxy_is_up(port: int, timeout: float = 0.35) -> bool:
    urls = (
        f"http://127.0.0.1:{port}/health",
        f"http://127.0.0.1:{port}/health/readiness",
    )
    for url in urls:
        try:
            with urlopen(url, timeout=timeout) as response:
                if response.status < 500:
                    return True
        except (URLError, TimeoutError, OSError):
            continue
    return False


def _key_env_from_litellm_model(litellm_model: str) -> str:
    if litellm_model.startswith("openrouter/"):
        return "OPENROUTER_API_KEY"
    if litellm_model.startswith("gemini/"):
        return "GEMINI_API_KEY"
    if litellm_model.startswith("groq/"):
        return "GROQ_API_KEY"
    return "OPENROUTER_API_KEY"


def _configured_models(state: dict) -> list[dict]:
    models = state.get("configured_models", [])
    if models:
        return models

    model_id = state.get("primary_model_id")
    model_name = state.get("primary_model_name")
    if not model_id:
        return []
    return [
        {
            "name": model_name or model_id,
            "model_id": model_id,
            "litellm_model": f"openrouter/{model_id}",
            "free": str(model_id).endswith(":free"),
        }
    ]


def _start_proxy_background(state: dict, env: dict) -> bool:
    port = int(state.get("port", DEFAULT_PORT))
    config_path = state.get("config_path", str(LITELLM_CONFIG_PATH))
    ensure_proxy_callback_module(config_path)
    command = ["litellm", "--config", str(config_path), "--port", str(port)]

    log_path = CONFIG_DIR / "proxy.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        handle = open(log_path, "a", encoding="utf-8")
    except OSError:
        handle = open(os.devnull, "w", encoding="utf-8")

    try:
        kwargs = {
            "env": env,
            "stdout": handle,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            process = subprocess.Popen(command, creationflags=creationflags, **kwargs)
        else:
            process = subprocess.Popen(command, start_new_session=True, **kwargs)
    except FileNotFoundError:
        error("litellm not found. Install it with: pip install 'litellm[proxy]'")
        return False
    finally:
        handle.close()

    for _ in range(40):
        if _proxy_is_up(port):
            state["proxy_pid"] = process.pid
            write_state(state)
            return True
        if process.poll() is not None:
            break
        time.sleep(0.25)

    return _proxy_is_up(port)


def _ensure_proxy_running(state: dict, env: dict) -> bool:
    port = int(state.get("port", DEFAULT_PORT))
    if _proxy_is_up(port):
        return True

    info(f"Proxy is not running on port {port}. Starting LiteLLM in background...")
    started = _start_proxy_background(state, env)
    if started:
        success("Proxy is up.")
    else:
        error("Failed to start proxy in background. Try: moon start")
    return started


def _compose_appended_prompt(state: dict, memory_prompt: str) -> str:
    prompt_enabled = bool(state.get("default_prompt_enabled"))
    prompt_text = str(state.get("default_prompt_text", "")).strip()

    if prompt_enabled and prompt_text:
        return (
            "Persistent Moon instruction (always apply):\n"
            f"{prompt_text}\n\n"
            "Project memory context:\n"
            f"{memory_prompt}"
        )
    return memory_prompt


def run_start() -> None:
    state = read_state()
    if not state:
        error("No configuration found. Run: moon setup")
        sys.exit(1)

    _ensure_shell_helpers(state)
    shell_commands = get_shell_commands(CONFIG_DIR)

    config_path = state.get("config_path", str(LITELLM_CONFIG_PATH))
    port = int(state.get("port", DEFAULT_PORT))
    active_model = None
    for model in _configured_models(state):
        if model.get("model_id") == state.get("primary_model_id"):
            active_model = model
            break
    if active_model is None:
        key_env = state.get("key_env", "OPENROUTER_API_KEY")
    else:
        key_env = _key_env_from_litellm_model(active_model.get("litellm_model", "openrouter/unknown"))
    migrate_litellm_config(config_path)
    sync_all_configured_models_to_yaml(state)
    ensure_proxy_callback_module(config_path)

    _, env = _load_saved_env(state)
    env = _prepare_proxy_env(env)

    if not env.get(key_env):
        error(f"{key_env} not set. Run: moon setup")
        sys.exit(1)

    if _proxy_is_up(port):
        warn(f"Proxy is already running on port {port}.")
        hint(f"Launch Claude with:  {c(shell_commands['run_moon'], CYAN, BOLD)}")
        return

    try:
        while True:
            state = read_state()  # Re-read state on each loop
            if not state:
                break
                
            active_model = None
            configured = state.get("configured_models", [])
            for model in configured:
                if model.get("model_id") == state.get("primary_model_id"):
                    active_model = model
                    break
            
            rows = [
                ("Status", c(f"Active on http://127.0.0.1:{port}", GREEN, BOLD)),
                ("Model", c(state.get("primary_model_name", "?"), BOLD)),
                ("Provider", c(state.get("provider", "?"), BOLD)),
                ("Config", c(str(config_path), BRIGHT)),
            ]
            model_pairs = _model_display_pairs(config_path)
            if model_pairs:
                aliases_str = "\n".join(
                    f"  {c(m, BOLD, CYAN)} {c('->', BRIGHT)} {c(a, BOLD, YELLOW)}"
                    for m, a in model_pairs
                )
                rows.append(("Aliases", f"\n{aliases_str}"))

            footer = f"Open a second terminal and run:\n  {c(shell_commands['run_moon'], CYAN, BOLD)}"

            from .ui import card
            card("Proxy Server", rows, footer=footer)

            returncode = _stream_litellm_logs(
                ["litellm", "--config", str(config_path), "--port", str(port)],
                env=env,
                config_path=str(config_path),
                state=state,
            )
            if returncode != 88:  # 88 = RESTART_REQUIRED
                break
            
            # Show a warning if the selected model is not ZDR
            state = read_state() or state
            active_id = state.get("primary_model_id")
            configured = state.get("configured_models", [])
            for m in configured:
                if m.get("model_id") == active_id:
                    if not m.get("zdr", False):
                        console.print(f" [{T_WARN}]⚠ Warning:[/] This model requires [bold]Data Collection[/].")
                        console.print(f"   If it fails, disable '[italic]Exclude from training[/]' in your OpenRouter Privacy Settings.")
                    break
    except KeyboardInterrupt:
        console.print()
        console.print(f" [{T_DIM}]Proxy stopped.[/]")


def run_chat(args: list[str] | None = None) -> None:
    state = read_state()
    if not state:
        error("No configuration found. Run: moon setup")
        sys.exit(1)

    _ensure_shell_helpers(state)

    key_env = state.get("key_env", "OPENROUTER_API_KEY")
    _, env = _load_saved_env(state)
    env = _prepare_proxy_env(env)
    if not env.get(key_env):
        error(f"{key_env} not set. Run: moon setup")
        sys.exit(1)

    auto_proxy = True
    claude_args = []
    for arg in list(args or []):
        if arg == "--no-auto-proxy":
            auto_proxy = False
            continue
        if arg == "--auto-proxy":
            auto_proxy = True
            continue
        claude_args.append(arg)

    port = int(state.get("port", DEFAULT_PORT))
    if auto_proxy:
        if not _ensure_proxy_running(state, env):
            sys.exit(1)
    elif not _proxy_is_up(port):
        warn("Proxy does not appear to be running. Start it manually with: moon start")

    project_root = detect_project_root()
    settings_path, memory_dir = ensure_project_settings(project_root)
    memory_path, memory_text = build_project_memory(project_root)
    memory_prompt = build_memory_prompt(project_root, memory_path, memory_text)
    combined_prompt = _compose_appended_prompt(state, memory_prompt)

    command = ["claude", "--dangerously-skip-permissions", "--settings", str(settings_path)]

    transcript_dir = claude_project_dir(project_root)
    if transcript_dir.exists():
        command += ["--add-dir", str(transcript_dir)]

    command += ["--add-dir", str(moon_project_dir(project_root)), "--append-system-prompt", combined_prompt]

    session_id = None
    if should_auto_resume(claude_args):
        session_id = latest_project_session_id(project_root, Path.cwd())
        if session_id:
            command += ["--resume", session_id]

    command += claude_args

    rows = [
        ("Proxy", c(f"http://127.0.0.1:{port}", CYAN)),
        ("Project", c(str(project_root), BOLD)),
    ]
    if session_id:
        rows.append(("Session", c(f"resuming {session_id}", GREEN)))
    else:
        rows.append(("Session", c("starting fresh", BRIGHT)))

    from .ui import card
    card(f"Claude Code ({c(state.get('primary_model_name', '?'), BOLD)})", rows)

    try:
        returncode = subprocess.call(command, env=env)
        if returncode != 0:
            sys.exit(returncode)
    except FileNotFoundError:
        error("claude not found. Install it with: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print()


def run_launch(args: list[str] | None = None) -> None:
    state = read_state()
    if not state:
        from .wizard import run_setup

        run_setup()
        state = read_state()
        if not state:
            error("Setup did not produce a valid configuration.")
            sys.exit(1)

    run_chat(["--auto-proxy", *(args or [])])


def run_history(args: list[str] | None = None) -> None:
    """Browse past conversation sessions for this project."""
    project_root = detect_project_root()
    summaries = get_session_summaries(project_root)

    if not summaries:
        warn(f"No session history found for: {project_root}")
        hint("Run 'moon chat' to start a session first.")
        return

    from .ui import card

    info(f"Project: {c(str(project_root), BOLD)}")
    info(f"Sessions: {c(str(len(summaries)), BOLD)}")
    console.print()

    from rich.table import Table

    table = Table(title="Session History", show_lines=False, border_style="dim")
    table.add_column("#", style="dim", width=3)
    table.add_column("Session ID", style="cyan", width=14)
    table.add_column("Date", style="green", width=18)
    table.add_column("Objective", style="white", max_width=50)
    table.add_column("Msgs", style="yellow", justify="right", width=5)
    table.add_column("Files", style="magenta", justify="right", width=5)

    for i, s in enumerate(summaries, 1):
        sid = s["session_id"][:12] + "..."
        from .memory import _format_timestamp
        started = _format_timestamp(s["first_timestamp"])
        objective = s["first_user_msg"][:50] or "—"
        msgs = str(s["exchange_count"])
        files = str(len(s["files_touched"]))
        table.add_row(str(i), sid, started, objective, msgs, files)

    console.print(table)
    console.print()

    # Check for --resume flag
    if args and len(args) >= 2 and args[0] == "--resume":
        target = args[1]
        # Find matching session
        for s in summaries:
            if s["session_id"].startswith(target):
                info(f"Resuming session: {c(s['session_id'], CYAN)}")
                run_chat(["--resume", s["session_id"]])
                return
        error(f"No session found matching: {target}")


def run_status() -> None:
    state = read_state()
    if not state:
        warn("Not configured yet. Run: moon setup")
        return

    port = int(state.get("port", DEFAULT_PORT))
    project_root = detect_project_root()
    _, memory_dir = ensure_project_settings(project_root)
    memory_path, _ = build_project_memory(project_root)
    models = _configured_models(state)
    proxy_up = _proxy_is_up(port)

    from .ui import card

    rows = [
        ("Proxy", c(f"live on port {port}", GREEN, BOLD) if proxy_up else c(f"stopped on port {port}", RED)),
        ("Provider", c(state.get("provider", "?"), BOLD)),
        ("Model", c(state.get("primary_model_name", "?"), BOLD)),
        ("Model ID", c(state.get("primary_model_id", "?"), BRIGHT)),
        ("Models", f"{c(str(len(models)), BOLD)} configured"),
        ("Project", c(str(project_root), BOLD)),
        ("Memory", c(str(memory_dir), BRIGHT)),
        ("Config", c(str(state.get("config_path", "?")), BRIGHT)),
    ]
    card("System Status", rows)


def run_models() -> None:
    state = read_state()
    active_model_id = state.get("primary_model_id")
    configured_ids = {item.get("model_id") for item in _configured_models(state)}

    from .ui import card
    
    for provider_name in get_provider_names():
        try:
            provider = get_provider(provider_name)
        except ModelCatalogError as exc:
            warn(str(exc))
            continue

        footer = None
        if provider_name == "OpenRouter" and provider.get("catalog_source") == "cache":
            footer = c("[cached catalog]", YELLOW, DIM)

        rows = []
        for model in provider["models"]:
            paid_tag = c(" [FREE]", GREEN, BOLD) if model["free"] else c(" [PAID]", YELLOW, BOLD)
            selected = " " + c("[ACTIVE]", GREEN, BOLD) if model["model_id"] == active_model_id else ""
            configured = " " + c("[CONFIGURED]", CYAN, BOLD) if model["model_id"] in configured_ids else ""
            
            rows.append((f"{model['name']}{paid_tag}", f"{c(model['model_id'], DIM)}{selected}{configured}"))

        card(provider_name, rows, footer=footer)
    info("Use `moon switch` to pick a configured model as active.")


def _switch_primary_model(state: dict, selected_model: dict) -> None:
    config_path = Path(state.get("config_path", str(LITELLM_CONFIG_PATH)))
    if not config_path.exists():
        raise RuntimeError("LiteLLM config file is missing. Run: moon setup")

    config = yaml.safe_load(read_text_compat(config_path)) or {}
    model_list = config.setdefault("model_list", [])

    key_env = _key_env_from_litellm_model(selected_model["litellm_model"])

    seen_aliases = set()
    for entry in model_list:
        model_name = entry.get("model_name")
        if model_name in CLAUDE_ALIASES:
            seen_aliases.add(model_name)
            entry["litellm_params"] = {
                "model": selected_model["litellm_model"],
                "api_key": f"os.environ/{key_env}",
            }

    missing_aliases = [alias for alias in CLAUDE_ALIASES if alias not in seen_aliases]
    for alias in missing_aliases:
        model_list.append(
            {
                "model_name": alias,
                "litellm_params": {
                    "model": selected_model["litellm_model"],
                    "api_key": f"os.environ/{key_env}",
                },
            }
        )

    if not any(item.get("model_name") == selected_model["model_id"] for item in model_list):
        model_list.append(
            {
                "model_name": selected_model["model_id"],
                "litellm_params": {
                    "model": selected_model["litellm_model"],
                    "api_key": f"os.environ/{key_env}",
                },
            }
        )

    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.dump(config, handle, default_flow_style=False, sort_keys=False, allow_unicode=True)

    state["primary_model_name"] = selected_model["name"]
    state["primary_model_id"] = selected_model["model_id"]
    state["key_env"] = key_env
    write_state(state)


def run_switch(args: list[str] | None = None) -> None:
    state = read_state()
    if not state:
        error("No configuration found. Run: moon setup")
        sys.exit(1)

    models = _configured_models(state)
    if not models:
        error("No configured models found. Re-run setup and include extra models.")
        sys.exit(1)

    selected = None
    args = args or []
    if args:
        model_id = args[0].strip()
        for model in models:
            if model.get("model_id") == model_id:
                selected = model
                break
        if selected is None:
            error(f"Configured model not found: {model_id}")
            info("Run `moon switch` without arguments for interactive selection.")
            sys.exit(1)
    else:
        options = []
        descriptions = []
        active_id = state.get("primary_model_id")
        for model in models:
            marker = " [ACTIVE]" if model.get("model_id") == active_id else ""
            options.append(f"{model.get('name', model.get('model_id'))}{marker}")
            descriptions.append(model.get("model_id", ""))
        index = select("Select active model", options, descriptions)
        selected = models[index]

    _switch_primary_model(state, selected)
    success(f"Active model is now: {selected['name']} ({selected['model_id']})")

    port = int(state.get("port", DEFAULT_PORT))
    if _proxy_is_up(port):
        warn("Proxy appears to be running in another terminal.")
        info("Press Alt+M in your Proxy terminal to apply this change seamlessly.")


def run_prompt(args: list[str] | None = None) -> None:
    state = read_state()
    if not state:
        state = {}

    args = args or []
    command = args[0] if args else "show"
    current_text = str(state.get("default_prompt_text", "")).strip()
    current_enabled = bool(state.get("default_prompt_enabled"))

    if command in ("show", "status"):
        section("Persistent Default Prompt")
        info(f"Enabled : {c('yes', GREEN) if current_enabled and current_text else c('no', DIM)}")
        if current_text:
            info(f"Text    : {c(current_text, CYAN)}")
        else:
            info(c("Text    : <empty>", DIM))
        console.print()
        info("Set with: moon prompt set \"Always do X\"")
        info("Toggle  : moon prompt enable | moon prompt disable")
        info("Clear   : moon prompt clear")
        return

    if command == "set":
        text = " ".join(args[1:]).strip()
        if not text:
            error("Usage: moon prompt set \"your instruction\"")
            sys.exit(1)
        state["default_prompt_text"] = text
        state["default_prompt_enabled"] = True
        write_default_prompt(text)
        write_state(state)
        success("Persistent default prompt saved and enabled.")
        return

    if command in ("enable", "on"):
        if not current_text:
            error("Default prompt text is empty. Set it first with: moon prompt set \"...\"")
            sys.exit(1)
        state["default_prompt_enabled"] = True
        write_state(state)
        success("Persistent default prompt enabled.")
        return

    if command in ("disable", "off"):
        state["default_prompt_enabled"] = False
        write_state(state)
        success("Persistent default prompt disabled.")
        return

    if command in ("clear", "reset"):
        state["default_prompt_text"] = ""
        state["default_prompt_enabled"] = False
        write_default_prompt("")
        write_state(state)
        success("Persistent default prompt cleared.")
        return

    error("Usage: moon prompt [show|set|enable|disable|clear]")
    sys.exit(1)


def run_env(args: list[str] | None = None) -> None:
    state = read_state()
    if not state:
        error("Not configured. Run: moon setup")
        sys.exit(1)

    _ensure_shell_helpers(state)

    shell_name = None
    args = args or []
    if args:
        if len(args) == 2 and args[0] == "--shell":
            shell_name = args[1]
        else:
            error("Usage: moon env [--shell sh|powershell|cmd]")
            sys.exit(1)

    try:
        shell_commands = get_shell_commands(CONFIG_DIR, shell_name=shell_name)
    except ValueError as exc:
        error(str(exc))
        sys.exit(1)

    console.print(f"# {shell_commands['label']}")
    console.print(shell_commands["load_env"])
    console.print()
    console.print("# Launch Claude with local memory + auto proxy")
    console.print(shell_commands["run_moon"])
    console.print()
    console.print("# Start proxy")
    console.print(shell_commands["start_proxy"])
    console.print()
    console.print("# Backward-compatible launcher")
    console.print(shell_commands["run_legacy"])


def run_setup_then_status() -> None:
    from .wizard import run_setup

    run_setup()
    run_status()


def run_rebuild_config() -> None:
    """
    Regenerate LiteLLM config from current state while preserving active model.
    """
    state = read_state()
    if not state:
        error("No configuration found. Run: moon setup")
        sys.exit(1)

    models = _configured_models(state)
    selected = None
    for model in models:
        if model.get("model_id") == state.get("primary_model_id"):
            selected = model
            break
    if selected is None and models:
        selected = models[0]

    if selected is None:
        error("No configured models available to rebuild config.")
        sys.exit(1)

    extra_models = [m for m in models if m.get("model_id") != selected.get("model_id")]
    _, env = _load_saved_env(state)
    key_env = _key_env_from_litellm_model(selected.get("litellm_model", "openrouter/unknown"))
    api_keys = {key_env: env.get(key_env, "")}

    config = build_litellm_config(selected, extra_models, api_keys, int(state.get("port", DEFAULT_PORT)))
    write_litellm_config(config)
    write_helper_scripts(
        state.get("port", DEFAULT_PORT),
        config_path=Path(state.get("config_path", str(LITELLM_CONFIG_PATH))),
        env_path=Path(state.get("env_path", str(ENV_PATH))),
    )
    success("LiteLLM config rebuilt from current MoonClaude state.")
