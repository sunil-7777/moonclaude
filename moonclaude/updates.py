"""
PyPI update checker for MoonClaude.
"""

import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .branding import CONFIG_DIR
from .__init__ import __version__

LAST_CHECK_FILE = CONFIG_DIR / "last_update_check"
CHECK_INTERVAL_SECONDS = 86400  # 24 hours


def get_latest_version() -> str | None:
    """Fetch the latest version of moonclaude from PyPI."""
    url = "https://pypi.org/pypi/moonclaude/json"
    req = Request(url, headers={"User-Agent": "moonclaude-cli"})
    try:
        with urlopen(req, timeout=3) as response:
            data = json.load(response)
            return data.get("info", {}).get("version")
    except Exception:
        return None


def show_update_message(latest_version: str) -> None:
    """Display a rich panel with the update message."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    msg = Text.assemble(
        ("A new version of ", "yellow"),
        ("MoonClaude", "bold cyan"),
        (" is available: ", "yellow"),
        (f"v{latest_version}", "bold green"),
        ("\nTo upgrade, run: ", "yellow"),
        (f"pip install --upgrade moonclaude", "bold white"),
    )
    
    panel = Panel(
        msg,
        title="[bold green]Update Available[/bold green]",
        border_style="green",
        expand=False,
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print("\n")


def check_for_updates(force: bool = False) -> None:
    """Check for updates if the interval has passed."""
    if not force:
        try:
            if LAST_CHECK_FILE.exists():
                last_check = float(LAST_CHECK_FILE.read_text().strip())
                if time.time() - last_check < CHECK_INTERVAL_SECONDS:
                    return
        except Exception:
            pass

    latest = get_latest_version()
    if not latest:
        return

    # Persist the check time even if no update found to respect interval
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LAST_CHECK_FILE.write_text(str(time.time()))
    except Exception:
        pass

    if latest != __version__:
        # Simple version comparison (works for standard SEMVER)
        # For more complex stuff we'd use packaging.version, but we keep deps low.
        show_update_message(latest)
