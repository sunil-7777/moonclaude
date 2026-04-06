# MoonClaude 🌙

**Moon for Claude**: Run [Claude Code](https://github.com/anthropics/claude-code) fully autonomously on external LLMs (e.g. Qwen, Gemini, MiniMax, OpenAI) through a LiteLLM proxy, while enjoying **zero-downtime hot reloading** and an **Antigravity-grade persistent AI memory** engine.

🌐 **[Visit the Official Landing Page](https://sunil-7777.github.io/moonclaude/)** for interactive setup guides and documentation.

---

## 🚀 Features

- **Free OpenRouter Models**: Interactively fetch and route your prompts through any of the 25+ completely free models on OpenRouter, or configure your own premium API keys (Gemini, Groq, OpenAI).
- **True Zero-Downtime Hot Reloading**: Press `Alt+M` directly in the proxy terminal to instantaneously swap the active model. MoonClaude dynamically intercepts the routing under the hood—no proxy restarts, no lost context in the CLI, no downtime.
- **Antigravity-Grade Project Memory**:
  - Auto-discovers and enforces `MOONCLAUDE.md` global project instructions into Claude Code's system prompts.
  - Generates cross-session, highly structured summarization context representing your recent AI coding sessions, intelligently managing your AI's working context without maxing out open files.
  - Easily browse transcripts natively with `moon history`.

---

## 📦 Installation & Setup

### 1. Prerequisites 
If you haven't already, you need `Node.js` installed to run Anthropic's official Claude Code CLI.
```bash
# Install Claude Code globally via npm
npm install -g @anthropic-ai/claude-code
```

### 2. Install MoonClaude
MoonClaude is available directly on PyPI!
```bash
pip install moonclaude
```

### 3. Initialize Settings
Run the interactive setup wizard to map your API keys (OpenRouter, Gemini, Groq) and select your preferred chat models.
```bash
moon setup
```

---

## 🏃 Quick Start

The easiest way to launch the proxy and jump straight into Claude Code is a single command. Open your project folder and run:
```bash
moon launch
```
*(If you haven't run setup yet, it will guide you through it first!)*

**Manual Control:**
If you prefer running the Proxy and Claude independently, open two terminals:
- **Terminal 1**: Run `moon start` (Starts the LiteLLM routing proxy)
- **Terminal 2**: Run `moon chat` (Launches Claude Code seamlessly attached to the proxy)

---

## 🎛️ Core Commands

```text
moon setup                  Interactive wizard for API keys and preferred models
moon launch                 Quick launch (starts proxy in background, then launches Claude)
moon chat                   Launch Claude connected to the proxy
moon start                  Start LiteLLM proxy in the foreground with live token monitoring
moon switch                 Fast CLI model switcher 
moon history                Interactive rich browser for your past conversation logs
moon memory                 Detailed control over the project memory context engine
moon status                 Display system health, active models, and paths
moon                        Show CLI help and commands
```

> **Compatibility**: MoonClaude preserves the old `claude-ext ...` legacy command aliases. Your legacy `~/.claude-ext` config will automatically migrate to `~/.moonclaude/` at launch!

---

## ♻️ Zero-Downtime Hot Reloading

When you are deep in a Claude Code debug session, discovering your chosen model is failing can be frustrating.

Instead of dropping context:
1. Keep the proxy running in the foreground (`moon start`).
2. Press `Alt+M`. 
3. Select a new LLM from your interactive UI overlay.
4. MoonClaude dynamically pre-warms its internal router injection without dropping the proxy connection. Your next prompt in the Claude Code terminal instantly bridges over to the new model!

---

## 🧠 Memory Engine

MoonClaude injects long-term memory into Claude Code.

1. **`MOONCLAUDE.md`**: Place this file in your project root. MoonClaude automatically reads it and appends it to your AI's persistent context across all sessions.
2. **Context Compression**: When you boot `moon chat`, MoonClaude evaluates your last 20 sessions and constructs an elegant, compressed timeline of files you've modified, goals you've accomplished, and context you shouldn't forget.
3. **Session Replay**: Type `moon history` to explore Rich-formatted logs of all of your previous AI code iterations.

---

## 🛡️ Bypassing Claude Restrictions

Claude Code by default only supports Anthropic models and requires an active initial authentication to their servers. **To use MoonClaude, you must authenticate once via the official CLI:**

```bash
claude login
```

Follow the browser prompt to log into your Anthropic Developer account. Don't worry—MoonClaude will route the actual requests away from Anthropic to your selected free providers instead.

### Routing Through MoonClaude

To ensure you don't hit Anthropic's paid API, never run `claude` directly. Always launch your environment with:

```bash
moon chat
# OR
moon launch
```

MoonClaude sets local HTTP proxy environmental variables (under the hood) to seamlessly override Anthropic's endpoints. Your prompts instantly hit Gemini, Llama, or Qwen instances safely and securely!

---

## License

MIT 
