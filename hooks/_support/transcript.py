"""Full session transcripts for later manual analysis.

Layout (default root data/sessions, override with CP_TRANSCRIPT_DIR; CP_TRANSCRIPTS=0 disables):

    <root>/<session_id>/meta.json        session settings (profile, model, prompt variant, ...)
    <root>/<session_id>/turns.jsonl      every command and turn: user text, final answer, pipeline details
    <root>/<session_id>/calls.jsonl      every model call: purpose, user prompt, response, usage
    <root>/<session_id>/prompts/<sha>.md system prompts, stored once and referenced by hash
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def enabled() -> bool:
    return os.environ.get("CP_TRANSCRIPTS", "1").strip().lower() not in {"0", "false", "off", "no"}


def root() -> Path:
    from . import config

    value = os.environ.get("CP_TRANSCRIPT_DIR")
    return Path(value) if value else config.DATA_ROOT.parent / "sessions"


def session_dir(session_id: str | None = None) -> Path | None:
    session_id = session_id or os.environ.get("CP_SESSION_ID")
    if not enabled() or not session_id:
        return None
    path = root() / SAFE_ID_RE.sub("_", session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, record: dict[str, Any]) -> None:
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def write_meta(meta: dict[str, Any], session_id: str | None = None) -> None:
    directory = session_dir(session_id)
    if directory is None:
        return
    target = directory / "meta.json"
    existing: dict[str, Any] = {}
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.setdefault("created_at", _now())
    existing.update(meta)
    target.write_text(json.dumps(existing, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def store_prompt(directory: Path, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    prompts = directory / "prompts"
    prompts.mkdir(exist_ok=True)
    target = prompts / f"{digest}.md"
    if not target.exists():
        target.write_text(text, encoding="utf-8")
    return digest


def write_call(
    *,
    profile: Any,
    purpose: str,
    system_prompt: str,
    user_prompt: str,
    response: str | None,
    usage: dict[str, Any] | None,
    latency_ms: int,
    attempt: int,
    error: str | None = None,
) -> None:
    directory = session_dir()
    if directory is None:
        return
    _append(
        directory / "calls.jsonl",
        {
            "ts": _now(),
            "profile": getattr(profile, "name", None),
            "provider": getattr(profile, "provider", None),
            "model": getattr(profile, "model", None),
            "prompt_variant": os.environ.get("CP_PROMPT_VARIANT", "full"),
            "purpose": purpose,
            "attempt": attempt,
            "latency_ms": latency_ms,
            "system_prompt_sha": store_prompt(directory, system_prompt),
            "user_prompt": user_prompt,
            "response": response,
            "usage": usage,
            "error": error,
        },
    )


def write_turn(record: dict[str, Any], session_id: str | None = None) -> None:
    directory = session_dir(session_id)
    if directory is None:
        return
    _append(directory / "turns.jsonl", {"ts": _now(), **record})


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
