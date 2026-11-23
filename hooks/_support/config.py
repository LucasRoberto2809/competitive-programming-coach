from __future__ import annotations

import os
from pathlib import Path


REPOSITORY_ROOT = Path(
    os.environ.get("CP_REPOSITORY_ROOT", Path(__file__).resolve().parents[2])
).resolve()
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
DATA_ROOT = Path(
    os.environ.get("CP_DATA_DIR", REPOSITORY_ROOT / "data" / "sources")
).resolve()
MAX_REVISIONS = max(0, int(os.environ.get("CP_MAX_REVISIONS", "2")))
PASS_THRESHOLD = int(os.environ.get("CP_EVALUATOR_PASS_THRESHOLD", "85"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("CP_HTTP_TIMEOUT_SECONDS", "120"))
SERVICE_TIMEOUT_SECONDS = float(os.environ.get("CP_SERVICE_TIMEOUT_SECONDS", "600"))
CONTEXT_BUDGET_TOKENS = max(1000, int(os.environ.get("CP_CONTEXT_BUDGET_TOKENS", "12000")))
CONTEXT_WARN_RATIO = float(os.environ.get("CP_CONTEXT_WARN_RATIO", "0.8"))
SESSIONS_ROOT = DATA_ROOT.parent / "sessions"
