# MoonClaude

MoonClaude is "Moon for Claude": use Claude Code with external LLMs through a LiteLLM proxy while keeping project-local memory and simple CLI ergonomics.

Backward compatibility is preserved:
- `claude-ext` command still works.
- Legacy `~/.claude-ext` config is migrated into `~/.moonclaude` when needed.

## Install

```bash
pip install moonclaude
```

From source:

```bash
git clone https://github.com/yourname/moonclaude
cd moonclaude
pip install -e .
```

## Quick Start

1. Run setup:

```bash
moon setup
```

2. Launch with one command (auto-start proxy + Claude):

```bash
moon
```

That is the easiest path. You can still run manual steps if you want explicit control:

```bash
moon start
moon chat
```

If MoonClaude is not configured yet, `moon` will run setup first and then continue into chat.

## Core Commands

```text
moon setup                  Interactive setup
moon                        Quick launch (setup if missing, then chat)
moon chat                   Launch Claude (auto-proxy on by default)
moon start                  Start LiteLLM proxy in foreground
moon status                 Show current model, proxy state, memory paths
moon models                 List provider models
moon switch [model_id]      Switch active model among configured models
moon prompt ...             Manage persistent default prompt
moon env --shell powershell Print helper commands for a shell
```

You can also use:
- `moonclaude ...` (full command name)
- `claude-ext ...` (legacy command alias)

## Model Catalog

OpenRouter free text models are fetched live from:

`https://openrouter.ai/api/v1/models`

MoonClaude caches this catalog in:

`~/.moonclaude/openrouter-models.json`

If live fetch is unavailable, setup and model listing fall back to cached data.

## Model Switching

Setup can store multiple models in `configured_models`. Switch active model instantly:

```bash
moon switch
moon switch qwen/qwen3.6-plus:free
```

After switching, restart proxy if it is already running so aliases update immediately:

```bash
moon start
```

## Persistent Default Prompt

You can keep a default instruction that is appended to every launched Claude session:

```bash
moon prompt show
moon prompt set "Always prefer concise answers with actionable steps."
moon prompt enable
moon prompt disable
moon prompt clear
```

This instruction is merged with project memory context at launch time.

## Token Visibility in Proxy Logs

MoonClaude registers a LiteLLM callback (`moonclaude.proxy_logging.moon_usage_logger`) that prints:
- per-request short request/response labels
- prompt tokens and completion tokens
- running summary totals

These lines appear in proxy output while LiteLLM is running.

## Startup Performance Notes

MoonClaude reduces startup friction by:
- auto-starting proxy when you run `moon` or `moon chat` (unless disabled)
- caching generated memory summary when local transcript set has not changed
- avoiding rewriting helper scripts unless content changed

## Generated Files

Primary config folder:

`~/.moonclaude/`

Key files:
- `litellm.yaml`
- `.env`
- `config.json`
- `default-prompt.txt`
- `proxy.log`
- `run-moon.*`, `load-env.*`, `start-proxy.*`

Legacy compatibility helper names (`run-claude.*`) are still generated.

## Migration from claude-ext

MoonClaude migrates from `~/.claude-ext` when `~/.moonclaude` does not exist yet:
- `litellm.yaml`
- `.env`
- `config.json`
- model cache
- helper scripts
- project memory folder

You can continue using the old command:

```bash
claude-ext status
```

It now routes to MoonClaude.

## License

MIT
