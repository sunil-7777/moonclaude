"""
MoonClaude CLI entry point.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from .branding import CLI_ALIAS, CLI_NAME, LEGACY_CLI_NAME
from .commands import (
    run_chat,
    run_env,
    run_history,
    run_launch,
    run_models,
    run_prompt,
    run_rebuild_config,
    run_setup_then_status,
    run_start,
    run_status,
    run_switch,
)
from .config import CONFIG_DIR
from .shells import get_shell_commands
from .ui import banner



def render_help() -> str:
    shell_commands = get_shell_commands(Path(CONFIG_DIR))
    return f"""
moonclaude - Moon for Claude with LiteLLM proxy

Short alias:
  moon

Commands:
  setup                  Interactive setup wizard
  start                  Start LiteLLM proxy in foreground
  chat [args...]         Launch Claude (auto-start proxy by default)
  launch [args...]       Quick path: setup if missing, then chat
  status                 Show active config and proxy status
  models                 List available models by provider
  switch [model_id]      Switch active model among configured models
  history                Browse past session history for this project
  prompt ...             Manage persistent default prompt
  env [--shell X]        Print shell-specific helper commands
  rebuild                Rebuild litellm config from state
  help                   Show this help

Memory:
  MoonClaude uses an Antigravity-style persistent memory system.
  - Global rules:    ~/.moonclaude/MOONCLAUDE.md
  - Workspace rules: <project>/MOONCLAUDE.md
  - Knowledge Items: <project>/.moonclaude/brain/knowledge/

Examples:
  moon
  moon setup
  moon chat
  moon switch
  moon history
  moon history --resume <session-id>
  moon prompt set "Prefer concise answers with code blocks"
  moon env --shell powershell
  {shell_commands['run_moon']}

Compatibility:
  `{LEGACY_CLI_NAME}` still works and maps to MoonClaude.
"""


def main() -> None:
    args = sys.argv[1:]
    help_text = render_help()

    if not args:
        banner()
        print(help_text)
        return

    cmd = args[0].strip().lower()

    if cmd in ("--help", "-h", "help"):
        print(help_text)
        return

    banner()

    if cmd == "setup":
        run_setup_then_status()
        return

    if cmd == "start":
        run_start()
        return

    if cmd == "chat":
        run_chat(args[1:])
        return

    if cmd in ("launch", "up", "moon"):
        run_launch(args[1:])
        return

    if cmd == "status":
        run_status()
        return

    if cmd == "models":
        run_models()
        return

    if cmd == "switch":
        run_switch(args[1:])
        return

    if cmd == "history":
        run_history(args[1:])
        return

    if cmd == "prompt":
        run_prompt(args[1:])
        return

    if cmd == "env":
        run_env(args[1:])
        return

    if cmd == "rebuild":
        run_rebuild_config()
        return

    print(f"Unknown command: {cmd}\n")
    print(help_text)
    sys.exit(1)


if __name__ == "__main__":
    main()
