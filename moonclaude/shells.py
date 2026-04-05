"""
Shell-aware helper scripts and command rendering for MoonClaude.
"""

from __future__ import annotations

import os
from pathlib import Path

from .branding import CLI_ALIAS, CLI_NAME


LOAD_ENV_SH = "load-env.sh"
RUN_MOON_SH = "run-moon.sh"
START_PROXY_SH = "start-proxy.sh"
RUN_CLAUDE_SH = "run-claude.sh"  # legacy helper name

LOAD_ENV_PS1 = "load-env.ps1"
RUN_MOON_PS1 = "run-moon.ps1"
START_PROXY_PS1 = "start-proxy.ps1"
RUN_CLAUDE_PS1 = "run-claude.ps1"  # legacy helper name

LOAD_ENV_BAT = "load-env.bat"
RUN_MOON_BAT = "run-moon.bat"
START_PROXY_BAT = "start-proxy.bat"
RUN_CLAUDE_BAT = "run-claude.bat"  # legacy helper name


def normalize_shell(shell_name: str | None = None) -> str:
    if shell_name:
        value = shell_name.strip().lower()
        aliases = {
            "bash": "sh",
            "zsh": "sh",
            "posix": "sh",
            "sh": "sh",
            "pwsh": "powershell",
            "ps": "powershell",
            "powershell": "powershell",
            "cmd": "cmd",
            "cmd.exe": "cmd",
        }
        if value not in aliases:
            raise ValueError(f"Unsupported shell: {shell_name}")
        return aliases[value]

    if os.name == "nt":
        if os.environ.get("PSModulePath"):
            return "powershell"
        return "cmd"

    return "sh"


def get_shell_commands(config_dir: Path, shell_name: str | None = None) -> dict:
    shell = normalize_shell(shell_name)
    config_dir = Path(config_dir)
    config_dir_posix = config_dir.as_posix()

    if shell == "powershell":
        return {
            "shell": shell,
            "label": "PowerShell",
            "load_env": f'. "{config_dir / LOAD_ENV_PS1}"',
            "run_moon": f'& "{config_dir / RUN_MOON_PS1}"',
            "run_legacy": f'& "{config_dir / RUN_CLAUDE_PS1}"',
            "start_proxy": f"{CLI_ALIAS} start",
            "start_proxy_helper": f'& "{config_dir / START_PROXY_PS1}"',
        }

    if shell == "cmd":
        return {
            "shell": shell,
            "label": "Command Prompt",
            "load_env": f'call "{config_dir / LOAD_ENV_BAT}"',
            "run_moon": f'call "{config_dir / RUN_MOON_BAT}"',
            "run_legacy": f'call "{config_dir / RUN_CLAUDE_BAT}"',
            "start_proxy": f"{CLI_ALIAS} start",
            "start_proxy_helper": f'call "{config_dir / START_PROXY_BAT}"',
        }

    return {
        "shell": shell,
        "label": "POSIX shell",
        "load_env": f'. "{config_dir_posix}/{LOAD_ENV_SH}"',
        "run_moon": f'"{config_dir_posix}/{RUN_MOON_SH}"',
        "run_legacy": f'"{config_dir_posix}/{RUN_CLAUDE_SH}"',
        "start_proxy": f"{CLI_ALIAS} start",
        "start_proxy_helper": f'"{config_dir_posix}/{START_PROXY_SH}"',
    }


def write_shell_helpers(config_dir: Path, env_path: Path, config_path: Path, port: int) -> dict:
    config_dir = Path(config_dir)
    env_path = Path(env_path)
    config_path = Path(config_path)
    env_path_posix = env_path.as_posix()
    config_path_posix = config_path.as_posix()
    config_dir.mkdir(parents=True, exist_ok=True)

    scripts = {
        LOAD_ENV_SH: f"""#!/usr/bin/env sh
set -a
. "{env_path_posix}"
set +a
""",
        RUN_MOON_SH: f"""#!/usr/bin/env sh
set -e
set -a
. "{env_path_posix}"
set +a
exec {CLI_NAME} chat --auto-proxy "$@"
""",
        RUN_CLAUDE_SH: f"""#!/usr/bin/env sh
set -e
set -a
. "{env_path_posix}"
set +a
exec {CLI_NAME} chat --auto-proxy "$@"
""",
        START_PROXY_SH: f"""#!/usr/bin/env sh
set -e
set -a
. "{env_path_posix}"
set +a
exec litellm --config "{config_path_posix}" --port "{port}"
""",
        LOAD_ENV_PS1: f"""$EnvFile = "{env_path}"
Get-Content $EnvFile | ForEach-Object {{
    if (-not [string]::IsNullOrWhiteSpace($_) -and -not $_.TrimStart().StartsWith('#')) {{
        $name, $value = $_ -split '=', 2
        Set-Item -Path ("Env:{{0}}" -f $name.Trim()) -Value $value
    }}
}}
""",
        RUN_MOON_PS1: f"""& "{config_dir / LOAD_ENV_PS1}"
& {CLI_NAME} chat --auto-proxy @args
""",
        RUN_CLAUDE_PS1: f"""& "{config_dir / LOAD_ENV_PS1}"
& {CLI_NAME} chat --auto-proxy @args
""",
        START_PROXY_PS1: f"""& "{config_dir / LOAD_ENV_PS1}"
& litellm --config "{config_path}" --port "{port}"
""",
        LOAD_ENV_BAT: f"""@echo off
for /f "usebackq eol=# tokens=1,* delims==" %%i in ("{env_path}") do (
    if not "%%i"=="" set "%%i=%%j"
)
""",
        RUN_MOON_BAT: f"""@echo off
call "{config_dir / LOAD_ENV_BAT}"
{CLI_NAME} chat --auto-proxy %*
""",
        RUN_CLAUDE_BAT: f"""@echo off
call "{config_dir / LOAD_ENV_BAT}"
{CLI_NAME} chat --auto-proxy %*
""",
        START_PROXY_BAT: f"""@echo off
call "{config_dir / LOAD_ENV_BAT}"
litellm --config "{config_path}" --port {port}
""",
    }

    written = {}
    for name, content in scripts.items():
        path = config_dir / name
        _write_if_changed(path, content)
        if path.suffix in (".sh", ".ps1"):
            os.chmod(path, 0o700)
        written[name] = path

    return written


def _write_if_changed(path: Path, content: str) -> None:
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = None
        if existing == content:
            return
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)

