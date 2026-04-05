"""
Antigravity-grade persistent memory engine for MoonClaude.

Features:
  - MOONCLAUDE.md global & workspace rules (like GEMINI.md)
  - 20-session automatic conversation summarization
  - Structured Knowledge Item extraction templates
  - File artifact tracking from JSONL tool-use entries
  - Session metadata for conversation browser
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .config import ensure_config_dir
from .branding import CONFIG_DIR


CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_PROJECTS_DIR = CLAUDE_DIR / "projects"
PROJECT_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "requirements.txt",
)

# Session summarization limits
MAX_SUMMARY_SESSIONS = 20       # Compact summaries for last N sessions
MAX_DETAILED_SESSIONS = 3       # Full transcript excerpts for last N
MAX_DETAIL_EXCHANGES = 5        # Max exchanges per detailed session
MAX_DETAIL_CHARS = 3000         # Max chars per detailed session transcript
MAX_SUMMARY_TITLE_LEN = 80     # Truncate session titles to this length

# KI categories for structured extraction
KI_CATEGORIES = [
    ("01_architecture", "Project architecture, folder structure, key components"),
    ("02_preferences", "User preferences, coding style, favorite tools"),
    ("03_decisions", "Design decisions, trade-offs, why X was chosen over Y"),
    ("04_bugs", "Known bugs, gotchas, workarounds, things that break"),
    ("05_dependencies", "Key dependencies, versions, integration notes"),
    ("06_context", "General project context, business logic, domain knowledge"),
]


def _has_project_markers(path: Path) -> bool:
    return any((path / marker).exists() for marker in PROJECT_MARKERS)


def detect_project_root(start_path: Path | None = None) -> Path:
    current = Path(start_path or Path.cwd()).resolve()
    home = Path.home().resolve()

    for candidate in (current, *current.parents):
        if candidate == home or len(candidate.parts) < len(home.parts):
            break
        if _has_project_markers(candidate):
            return candidate

    try:
        result = subprocess.run(
            ["git", "-C", str(current), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_root = Path(result.stdout.strip()).resolve()
        if git_root != home and str(git_root).startswith(str(home)):
            return git_root
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return current


def project_slug(project_root: Path) -> str:
    value = str(project_root.resolve())
    value = value.replace(":", "-").replace("\\", "-").replace("/", "-").replace(" ", "-")
    return value.strip("-")


def claude_project_dir(project_root: Path) -> Path:
    return CLAUDE_PROJECTS_DIR / project_slug(project_root)


def moon_project_dir(project_root: Path) -> Path:
    ensure_config_dir()
    return CONFIG_DIR / "projects" / project_slug(project_root)


def project_memory_file(project_root: Path) -> Path:
    return moon_project_dir(project_root) / "project-memory.md"


def _memory_meta_file(project_root: Path) -> Path:
    return moon_project_dir(project_root) / "project-memory.meta.json"


def _iter_project_session_files(project_root: Path) -> list[Path]:
    project_dir = claude_project_dir(project_root)
    if not project_dir.exists():
        return []
    return sorted(project_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)


def latest_project_session_id(project_root: Path, start_path: Path | None = None) -> str | None:
    current = Path(start_path or Path.cwd()).resolve()
    project_candidates = [project_root.resolve()]
    if current != project_root.resolve():
        project_candidates.append(current)

    session_files = []
    for candidate in project_candidates:
        project_dir = claude_project_dir(candidate)
        if project_dir.exists():
            session_files.extend(project_dir.glob("*.jsonl"))

    if not session_files:
        return None

    newest = max(session_files, key=lambda path: path.stat().st_mtime)
    return newest.stem


# ── MOONCLAUDE.md Workspace Rules ──────────────────────────────────────


def load_workspace_rules(project_root: Path) -> str:
    """Load global + workspace MOONCLAUDE.md rules (like GEMINI.md)."""
    sections = []

    # Global rules: ~/.moonclaude/MOONCLAUDE.md
    global_rules_path = CONFIG_DIR / "MOONCLAUDE.md"
    if global_rules_path.exists():
        try:
            content = global_rules_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"### Global Rules ({global_rules_path})\n{content}")
        except OSError:
            pass

    # Workspace rules: <project_root>/MOONCLAUDE.md
    workspace_rules_path = project_root / "MOONCLAUDE.md"
    if workspace_rules_path.exists():
        try:
            content = workspace_rules_path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"### Workspace Rules ({workspace_rules_path})\n{content}")
        except OSError:
            pass

    if not sections:
        return ""

    rules_text = "\n\n".join(sections)
    return f"\n<workspace_rules>\n{rules_text}\n</workspace_rules>\n"


# ── Message Extraction ─────────────────────────────────────────────────


def _extract_message_text(content) -> str:
    if isinstance(content, str):
        return " ".join(content.split())
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = item.get("text", "")
        if text:
            parts.append(" ".join(str(text).split()))
    return " ".join(parts).strip()


# ── Session Metadata Extraction ────────────────────────────────────────


def _extract_session_metadata(session_file: Path) -> dict:
    """Extract compact metadata from a session JSONL file."""
    meta = {
        "session_id": session_file.stem,
        "first_user_msg": "",
        "first_timestamp": "",
        "last_timestamp": "",
        "exchange_count": 0,
        "files_touched": set(),
    }

    try:
        lines = session_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return meta

    user_count = 0
    for raw_line in lines:
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        entry_type = entry.get("type")
        timestamp = entry.get("timestamp", "")

        if not meta["first_timestamp"] and timestamp:
            meta["first_timestamp"] = timestamp
        if timestamp:
            meta["last_timestamp"] = timestamp

        if entry_type == "user":
            user_count += 1
            message = entry.get("message", {})
            text = _extract_message_text(message.get("content"))
            if text and not meta["first_user_msg"]:
                meta["first_user_msg"] = text[:MAX_SUMMARY_TITLE_LEN]

        elif entry_type == "assistant":
            if user_count > 0:
                meta["exchange_count"] += 1

            # Track files touched via tool use
            message = entry.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        tool_input = block.get("input", {})
                        if isinstance(tool_input, dict):
                            for key in ("file_path", "path", "command"):
                                val = tool_input.get(key, "")
                                if isinstance(val, str) and val:
                                    meta["files_touched"].add(val)

    meta["files_touched"] = sorted(meta["files_touched"])
    return meta


def _extract_detailed_exchanges(session_file: Path) -> list[dict]:
    """Extract full exchange pairs from a single session file."""
    exchanges = []
    pending_user = None

    try:
        lines = session_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return exchanges

    for raw_line in lines:
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        entry_type = entry.get("type")
        if entry_type == "user":
            message = entry.get("message", {})
            text = _extract_message_text(message.get("content"))
            if text:
                pending_user = {
                    "timestamp": entry.get("timestamp", ""),
                    "user": text,
                    "session_id": entry.get("sessionId", session_file.stem),
                }
        elif entry_type == "assistant" and pending_user:
            message = entry.get("message", {})
            text = _extract_message_text(message.get("content"))
            if text:
                exchanges.append({
                    "timestamp": entry.get("timestamp", pending_user["timestamp"]),
                    "user": pending_user["user"],
                    "assistant": text[:500],  # Truncate long responses
                    "session_id": pending_user["session_id"],
                })
                pending_user = None

    return exchanges


# ── Session Summary Table Builder ──────────────────────────────────────


def _format_timestamp(ts: str) -> str:
    if not ts:
        return "unknown"
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts[:16]


def get_session_summaries(project_root: Path) -> list[dict]:
    """Get metadata summaries for all sessions (used by moon history too)."""
    session_files = _iter_project_session_files(project_root)
    summaries = []
    for sf in session_files[:MAX_SUMMARY_SESSIONS]:
        summaries.append(_extract_session_metadata(sf))
    return summaries


def _build_summary_table(summaries: list[dict]) -> str:
    if not summaries:
        return "No prior sessions found for this project."

    lines = [
        "| # | Session ID | Started | Objective | Exchanges | Files |",
        "|---|------------|---------|-----------|-----------|-------|",
    ]
    for i, s in enumerate(summaries, 1):
        sid = s["session_id"][:12] + "..."
        started = _format_timestamp(s["first_timestamp"])
        objective = s["first_user_msg"][:60] or "—"
        exchanges = str(s["exchange_count"])
        files_count = str(len(s["files_touched"]))
        lines.append(f"| {i} | `{sid}` | {started} | {objective} | {exchanges} | {files_count} |")

    return "\n".join(lines)


# ── Build Project Memory ───────────────────────────────────────────────


def _current_transcript_signature(project_root: Path) -> dict:
    session_files = _iter_project_session_files(project_root)
    if not session_files:
        return {"count": 0, "latest_mtime": 0}
    return {
        "count": len(session_files),
        "latest_mtime": max(f.stat().st_mtime for f in session_files),
    }


def _load_cached_memory_if_valid(project_root: Path) -> tuple[Path | None, str]:
    memory_path = project_memory_file(project_root)
    meta_path = _memory_meta_file(project_root)
    if not memory_path.exists() or not meta_path.exists():
        return None, ""

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ""

    if not isinstance(meta, dict):
        return None, ""

    signature = _current_transcript_signature(project_root)
    if meta.get("count") != signature["count"]:
        return None, ""
    if float(meta.get("latest_mtime", 0)) != float(signature["latest_mtime"]):
        return None, ""

    try:
        return memory_path, memory_path.read_text(encoding="utf-8")
    except OSError:
        return None, ""


def build_project_memory(project_root: Path) -> tuple[Path, str]:
    cached_path, cached_text = _load_cached_memory_if_valid(project_root)
    if cached_path is not None:
        return cached_path, cached_text

    project_dir = moon_project_dir(project_root)
    memory_path = project_memory_file(project_root)
    meta_path = _memory_meta_file(project_root)
    project_dir.mkdir(parents=True, exist_ok=True)

    session_files = _iter_project_session_files(project_root)
    summaries = []
    for sf in session_files[:MAX_SUMMARY_SESSIONS]:
        summaries.append(_extract_session_metadata(sf))

    lines = [
        "# Project Memory",
        "",
        f"- Project root: {project_root}",
        f"- Sessions found: {len(session_files)}",
        f"- Source transcripts: {claude_project_dir(project_root)}",
    ]

    if summaries:
        lines.append(f"- Last activity: {_format_timestamp(summaries[0]['first_timestamp'])}")
    else:
        lines.append("- Last activity: none yet")

    # Section 1: Compact 20-session summary table
    lines += ["", "## Session History (last 20)", ""]
    lines.append(_build_summary_table(summaries))

    # Section 2: Detailed transcripts for last 3 sessions
    lines += ["", "## Recent Session Details", ""]

    detailed_count = 0
    for sf in session_files[:MAX_DETAILED_SESSIONS]:
        exchanges = _extract_detailed_exchanges(sf)
        if not exchanges:
            continue

        meta = _extract_session_metadata(sf)
        lines.append(f"### Session {sf.stem[:12]}... ({_format_timestamp(meta['first_timestamp'])})")
        lines.append(f"**Objective:** {meta['first_user_msg'] or 'unknown'}")

        if meta["files_touched"]:
            files_str = ", ".join(f"`{f}`" for f in meta["files_touched"][:10])
            lines.append(f"**Files touched:** {files_str}")

        lines.append("")

        used_chars = 0
        for ex in exchanges[:MAX_DETAIL_EXCHANGES]:
            entry = f"- **User:** {ex['user'][:200]}\n- **AI:** {ex['assistant'][:300]}\n"
            if used_chars + len(entry) > MAX_DETAIL_CHARS:
                break
            lines.append(entry)
            used_chars += len(entry)

        detailed_count += 1

    if detailed_count == 0:
        lines.append("No detailed session data available yet.")

    memory_text = "\n".join(lines).strip() + "\n"
    memory_path.write_text(memory_text, encoding="utf-8")

    signature = _current_transcript_signature(project_root)
    meta_path.write_text(json.dumps(signature, indent=2) + "\n", encoding="utf-8")
    return memory_path, memory_text


# ── Knowledge Item Scaffold & Injection ────────────────────────────────


_KI_SEED_CONTENT = """# Project Knowledge

This folder acts as your permanent memory across sessions.
The AI agent will automatically save important context here as structured markdown files.

## Categories
- `01_architecture.md` — Project structure, key components, folder layout
- `02_preferences.md` — User preferences, coding style, tool choices
- `03_decisions.md` — Design decisions, trade-offs, rationale
- `04_bugs.md` — Known bugs, gotchas, workarounds
- `05_dependencies.md` — Key dependencies, versions, integrations
- `06_context.md` — General project context, business logic, domain knowledge

## Rules
- Files are automatically injected into the AI's system prompt on every session.
- The AI should UPDATE existing files rather than creating duplicates.
- Keep entries concise and factual.
"""

_KI_INSTRUCTIONS = """You are equipped with an Antigravity-style persistent memory system.
Your permanent 'brain' for this project is stored in: {knowledge_dir}

CRITICAL INSTRUCTIONS FOR KNOWLEDGE MANAGEMENT:
1. If you discover important project facts, architecture, user preferences, design decisions, bugs, or dependencies, you MUST quietly save them to the knowledge directory using your file tools.
2. Use these category files (create if missing, UPDATE if existing):
   - 01_architecture.md — Project structure, key components
   - 02_preferences.md — User preferences, coding style
   - 03_decisions.md — Design decisions and rationale
   - 04_bugs.md — Known bugs and workarounds
   - 05_dependencies.md — Key dependencies and versions
   - 06_context.md — General project context
3. Format each entry as a bullet point with a date: `- [2026-04-05] Description`
4. NEVER duplicate entries — read the file first, then append or update.
5. DO NOT ask the user for permission to read/write files. You have full filesystem access. Execute tools silently and immediately.

Everything in the knowledge directory is automatically injected into your system prompt on ALL future sessions — this is your permanent memory!"""


def _scaffold_brain(project_root: Path) -> Path:
    """Create .moonclaude/brain/knowledge/ scaffold if missing."""
    brain_dir = project_root / ".moonclaude" / "brain"
    knowledge_dir = brain_dir / "knowledge"

    if not brain_dir.exists():
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        gitignore_path = project_root / ".moonclaude" / ".gitignore"
        if not gitignore_path.exists():
            try:
                gitignore_path.parent.mkdir(parents=True, exist_ok=True)
                gitignore_path.write_text("*\n", encoding="utf-8")
            except OSError:
                pass

        readme_path = knowledge_dir / "00_memory_rules.md"
        if not readme_path.exists():
            try:
                readme_path.write_text(_KI_SEED_CONTENT, encoding="utf-8")
            except OSError:
                pass

    return knowledge_dir


def _load_knowledge_items(knowledge_dir: Path) -> str:
    """Read all KI markdown/txt files and stitch into XML block."""
    knowledge_items = []
    if knowledge_dir.exists():
        seen = set()
        for ki_file in sorted(knowledge_dir.rglob("*.md")) + sorted(knowledge_dir.rglob("*.txt")):
            if ki_file.name in seen:
                continue
            seen.add(ki_file.name)
            try:
                content = ki_file.read_text(encoding="utf-8").strip()
                if content:
                    knowledge_items.append(f"--- {ki_file.name} ---\n{content}")
            except OSError:
                pass

    if not knowledge_items:
        return ""

    ki_text = "\n\n".join(knowledge_items)
    return f"\n<antigravity_persistent_memory>\n{ki_text}\n</antigravity_persistent_memory>\n"


# ── Main Prompt Builder ────────────────────────────────────────────────


def build_memory_prompt(project_root: Path, memory_path: Path, memory_text: str) -> str:
    knowledge_dir = _scaffold_brain(project_root)

    # 1. Workspace rules (MOONCLAUDE.md)
    workspace_rules = load_workspace_rules(project_root)

    # 2. KI instructions
    ki_header = _KI_INSTRUCTIONS.format(knowledge_dir=knowledge_dir)

    # 3. Persisted knowledge items
    ki_section = _load_knowledge_items(knowledge_dir)

    # 4. Guidance
    guidance = (
        f"Memory summary file: {memory_path}\n"
        f"Raw session transcripts: {claude_project_dir(project_root)}"
    )

    # Assemble the full prompt
    parts = [
        f"<antigravity_memory_system>\n{ki_header}\n</antigravity_memory_system>",
    ]

    if workspace_rules:
        parts.append(workspace_rules)

    if ki_section:
        parts.append(ki_section)

    parts.append(f"\n{guidance}")
    parts.append(f"\n<conversation_history>\n{memory_text.strip()}\n</conversation_history>")

    return "\n".join(parts)


# ── Project Settings ───────────────────────────────────────────────────


def ensure_project_settings(project_root: Path) -> tuple[Path, Path]:
    project_dir = moon_project_dir(project_root)
    memory_dir = project_dir / "memory"
    settings_path = project_dir / "claude-settings.json"

    project_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)

    settings = {
        "autoMemoryEnabled": True,
        "autoMemoryDirectory": str(memory_dir),
    }
    with open(settings_path, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)

    return settings_path, memory_dir


def should_auto_resume(claude_args: list[str]) -> bool:
    return not bool(claude_args)
