"""Minimal .env loader (standard library only)."""

from __future__ import annotations

import os
import re
from pathlib import Path

LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; supports comments, `export`, and single/double quotes."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        key, raw = match.groups()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            value = raw[1:-1]
        else:
            value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        values[key] = value
    return values


def load_env_file(path: Path | str | None = None, override: bool = False) -> list[str]:
    """Load variables from a .env file into os.environ; real environment variables win.

    Empty values are skipped so a blank `CP_LLM_API_KEY=` in the file does not mask a
    value set elsewhere. Returns the names that were loaded.
    """
    target = Path(path) if path else Path(os.environ.get("CP_ENV_FILE", DEFAULT_ENV_FILE))
    if not target.is_file():
        return []
    loaded = []
    for key, value in parse_env_file(target.read_text(encoding="utf-8-sig")).items():
        if value == "" or (key in os.environ and not override):
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded
