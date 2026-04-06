"""
Directly invoke run_launch logic step by step to debug what happens.
"""
import sys
sys.path.insert(0, r"c:\Users\sunil\ai-projects\claude-ext")

from moonclaude.commands import _proxy_is_up, _load_saved_env, _prepare_proxy_env
from moonclaude.config import read_state 
from moonclaude.branding import DEFAULT_PORT

state = read_state()
if not state:
    print("ERROR: No state found. run moon setup first.")
    sys.exit(1)

port = int(state.get("port", DEFAULT_PORT))
print(f"Port: {port}")
print(f"Proxy is up: {_proxy_is_up(port)}")
print(f"Primary model: {state.get('primary_model_name')}")

_, env = _load_saved_env(state)
env = _prepare_proxy_env(env)

import os
print(f"\nos.name: {os.name}")
print(f"Will spawn new CMD window with: 'moon chat'")
print("Will call run_start() in this terminal")
print("\nIf proxy is already up:", _proxy_is_up(port))
print("-> If True, run_start() will EXIT EARLY since proxy is already running!")
print("   This means the current terminal gets NO proxy logs and just returns.")
print("   The new CMD window gets 'moon chat' which connects and runs claude.")
print("   This would mean claude appears in the new window, not the current one.")
print("\nIs the problem that the proxy is ALREADY running from a previous session?")
