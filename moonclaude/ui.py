"""
Terminal UI helpers: colors, prompts, and compact menus. Ultra-premium aesthetics inspired by Gemini CLI.
"""
from __future__ import annotations

import getpass
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box

# Enable rich console with truecolor
console = Console(highlight=False)

# Export legacy codes to prevent import breaks
RESET = ""
BOLD = "bold"
DIM = "dim"
ITALIC = "italic"
UNDERLINE = "underline"
RED = "red"
GREEN = "green"
YELLOW = "yellow"
BLUE = "blue"
MAGENTA = "magenta"
CYAN = "cyan"
WHITE = "white"
BRIGHT = "bright_black"

# Theme colors
T_INFO = "#a855f7" # bright purple
T_SUCCESS = "#22c55e" # green
T_DIM = "#52525b" # zinc-600
T_PROMPT = "#a1a1aa" # zinc-400
T_WARN = "#f59e0b" # amber
T_ERR = "#ef4444" # red

def c(text: str, *codes: str) -> str:
    valid_codes = [code for code in codes if code]
    if not valid_codes:
        return str(text)
    tags, escaped = " ".join(valid_codes), str(text).replace("[", "\\[")
    return f"[{tags}]{escaped}[/]"

def banner() -> None:
    try:
        from importlib.metadata import version
        v = version("moonclaude")
    except:
        v = "3.0.0"

    art = [
        "███╗   ███╗ ██████╗  ██████╗ ███╗   ██╗ ██████╗ ██╗       █████╗ ██╗   ██╗██████╗ ███████╗",
        "████╗ ████║██╔═══██╗██╔═══██╗████╗  ██║██╔════╝ ██║      ██╔══██╗██║   ██║██╔══██╗██╔════╝",
        "██╔████╔██║██║   ██║██║   ██║██╔██╗ ██║██║      ██║      ███████║██║   ██║██║  ██║█████╗  ",
        "██║╚██╔╝██║██║   ██║██║   ██║██║╚██╗██║██║      ██║      ██╔══██║██║   ██║██║  ██║██╔══╝  ",
        "██║ ╚═╝ ██║╚██████╔╝╚██████╔╝██║ ╚████║╚██████╗ ███████╗ ██║  ██║╚██████╔╝██████╔╝███████╗",
        f"╚═╝     ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ v{v}",
    ]
    colors = ["#3b82f6", "#6366f1", "#8b5cf6", "#a855f7", "#d946ef", "#ec4899"]
    
    console.print()
    for line, color in zip(art, colors):
        console.print(f"[{color}]{line}[/]")
    console.print()

    # Check for updates in the background (throttled to 24h)
    try:
        from .updates import check_for_updates
        check_for_updates()
    except Exception:
        pass

def info(msg: str) -> None:
    console.print(f" [{T_INFO}]✦[/] {msg}")

def ok(msg: str) -> None:
    console.print(f" [{T_SUCCESS}]✦[/] {msg}")

def success(msg: str) -> None:
    ok(msg)

def warn(msg: str) -> None:
    console.print(f" [{T_WARN}]✦[/] {msg}")

def fail(msg: str) -> None:
    console.print(f" [{T_ERR}]✖[/] {msg}")

def error(msg: str) -> None:
    fail(msg)

def hint(msg: str) -> None:
    console.print(f"   [dim]{msg}[/]")

def spin_line(msg: str) -> str:
    return f" [{T_INFO}]⠇[/] [dim]{msg}[/]"

def prompt(question: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [dim]({default})[/]" if default else ""
    console.print(f"[{T_DIM}]>[/] [{T_PROMPT}]{question}{suffix} [/]", end="")
    value = getpass.getpass("") if secret else input()
    return default if not value and default else value.strip()

def confirm(question: str, default: bool = True) -> bool:
    hint_str = "[dim]Y/n[/]" if default else "[dim]y/N[/]"
    console.print(f"[{T_DIM}]>[/] [{T_PROMPT}]{question} {hint_str} [/]", end="")
    answer = input().strip().lower()
    return default if not answer else answer in ("y", "yes")

def select(question: str, options: list[str], descriptions: list[str] | None = None, multi: bool = False):
    console.print(f"[{T_DIM}]>[/] [{T_PROMPT}]{question}[/]")
    for i, opt in enumerate(options, 1):
        desc = descriptions[i-1] if descriptions and i-1 < len(descriptions) else ""
        console.print(f"   [{T_INFO}]{i}.[/] {opt} [dim]{desc}[/]")
    while True:
        console.print(f"[{T_DIM}]>[/] ", end="")
        raw = input()
        if multi:
            try:
                selected = [int(t.strip())-1 for t in raw.split(",") if t.strip()]
                if all(0 <= idx < len(options) for idx in selected): return selected
            except ValueError: pass
        else:
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(options): return idx
            except ValueError: pass
        error("Invalid selection. Try again.")

def card(title: str, rows: list[tuple[str, str]], footer: str | None = None) -> None:
    txt = Text()
    for i, (lbl, val) in enumerate(rows):
        txt.append(f"{lbl}: ", style=T_DIM)
        if isinstance(val, str) and "[" in val and "]" in val:
            txt.append(Text.from_markup(val))
        else:
            txt.append(str(val))
            
        if i < len(rows) - 1:
            txt.append("\n")
    if footer:
        txt.append("\n\n")
        txt.append(Text.from_markup(footer))
    
    panel = Panel(
        txt,
        title=f" [{T_INFO}]✦[/] {title} ",
        title_align="left",
        border_style=T_DIM,
        box=box.ROUNDED,
        padding=(0, 2)
    )
    console.print()
    console.print(panel)
    console.print()

def section(title: str) -> None:
    console.print(f"\n[bold white]{title}[/]")

def step(current: int, total: int, title: str) -> None:
    console.print(f"\n[{T_DIM}]({current}/{total})[/] [bold white]{title}[/]")
