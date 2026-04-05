"""
Branding constants shared across MoonClaude modules.
"""

import os
from pathlib import Path


APP_NAME = "moonclaude"
APP_TITLE = "MoonClaude"
CLI_NAME = "moonclaude"
CLI_ALIAS = "moon"
LEGACY_CLI_NAME = "claude-ext"

CONFIG_DIR = Path(os.environ.get("MOONCLAUDE_HOME", Path.home() / ".moonclaude")).expanduser()
LEGACY_CONFIG_DIR = Path(os.environ.get("MOONCLAUDE_LEGACY_HOME", Path.home() / ".claude-ext")).expanduser()

DEFAULT_PORT = 4000
