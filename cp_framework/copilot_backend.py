"""Copilot models through the official GitHub Copilot SDK.

Install with `make dependencies` or `uv sync`.
Authentication: a fine-grained PAT (github_pat_...) in the profile's key variable, by default
COPILOT_GITHUB_TOKEN. Sessions run in the SDK's isolated "empty" mode with a dedicated
home directory, no tools, and our system prompt replacing the agent's, so only the task is
measured and nothing touches the user's ~/.copilot history, skills, or MCP servers.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import HTTP_TIMEOUT_SECONDS

INSTALL_HINT = (
    "O SDK github-copilot-sdk não está instalado neste ambiente. Rode `make dependencies` ou `uv sync` "
    "e inicie o app com `uv run python -m cp_framework.app`."
)


def copilot_home() -> Path:
    from . import config

    value = os.environ.get("CP_COPILOT_HOME")
    path = Path(value) if value else config.DATA_ROOT.parent / "copilot-home"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sdk_available() -> bool:
    try:
        import copilot  # noqa: F401
    except ImportError:
        return False
    return True


GH_CANDIDATES = (
    "gh",
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI", "gh.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GitHub CLI", "gh.exe"),
)
SUPPORTED_PREFIXES = ("gho_", "ghu_", "github_pat_")


def gh_cli_token() -> str | None:
    """Token of the user logged in with the GitHub CLI (`gh auth login`), never stored by us."""
    import shutil
    import subprocess

    for candidate in GH_CANDIDATES:
        executable = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if not executable:
            continue
        try:
            result = subprocess.run([executable, "auth", "token", "--hostname", "github.com"], capture_output=True,
                                    text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        token = result.stdout.strip()
        if result.returncode == 0 and token:
            return token
    return None


def resolve_token(profile: Any) -> tuple[str | None, str]:
    """Token and its source: the profile's variable, GH_TOKEN, or the GitHub CLI login."""
    if profile.api_key_env and os.environ.get(profile.api_key_env):
        return os.environ[profile.api_key_env], profile.api_key_env
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"], "GH_TOKEN"
    token = gh_cli_token()
    return (token, "gh auth token") if token else (None, "nenhum")


def token_problem(token: str | None, source: str) -> str | None:
    if not token:
        return (
            "Nenhum token do Copilot encontrado: faça login com `gh auth login --web` (seu usuário do GitHub) ou defina "
            "COPILOT_GITHUB_TOKEN=github_pat_... (fine-grained, permissão Copilot Requests) no .env."
        )
    if token.startswith("ghp_"):
        return f"O token de {source} é clássico (ghp_), que o Copilot SDK não aceita; use gho_, ghu_ ou github_pat_."
    return None


def _ms(value: Any) -> int | None:
    if isinstance(value, timedelta):
        return round(value.total_seconds() * 1000)
    if isinstance(value, (int, float)):
        return round(value)
    return None


def summarize_usage(usage_events: list[Any], checkpoints: list[Any]) -> dict[str, Any]:
    """Aggregate AssistantUsageData events (one per model API call) and the last usage checkpoint."""

    def total(name: str) -> int | None:
        values = [getattr(event, name, None) for event in usage_events]
        values = [value for value in values if isinstance(value, (int, float))]
        return int(sum(values)) if values else None

    costs = [getattr(event, "cost", None) for event in usage_events]
    costs = [value for value in costs if isinstance(value, (int, float))]
    durations = [_ms(getattr(event, "duration", None)) for event in usage_events]
    durations = [value for value in durations if value is not None]
    nano_aiu = getattr(checkpoints[-1], "total_nano_aiu", None) if checkpoints else None
    models = {getattr(event, "model", None) for event in usage_events} - {None}
    return {
        "prompt_tokens": total("input_tokens"),
        "completion_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "cache_read_tokens": total("cache_read_tokens"),
        "cache_write_tokens": total("cache_write_tokens"),
        "api_calls": len(usage_events),
        "copilot_cost": sum(costs) if costs else None,
        "nano_aiu": nano_aiu,
        "model_ms": sum(durations) if durations else None,
        "served_models": sorted(models),
    }


async def _complete(profile: Any, system_prompt: str, user_prompt: str, token: str | None, timeout: float) -> tuple[str | None, dict[str, Any]]:
    from copilot import CopilotClient
    from copilot.session_events import AssistantMessageData, AssistantUsageData, SessionUsageCheckpointData

    usage_events: list[Any] = []
    checkpoints: list[Any] = []

    def on_event(event: Any) -> None:
        if getattr(event, "agent_id", None):
            return
        if isinstance(event.data, AssistantUsageData):
            usage_events.append(event.data)
        elif isinstance(event.data, SessionUsageCheckpointData):
            checkpoints.append(event.data)

    client_options: dict[str, Any] = {"mode": "empty", "base_directory": str(copilot_home())}
    if token:
        client_options["github_token"] = token
    session_options: dict[str, Any] = {
        "model": profile.model,
        "system_message": {"mode": "replace", "content": system_prompt},
        "available_tools": [],
    }
    if getattr(profile, "reasoning_effort", None):
        session_options["reasoning_effort"] = profile.reasoning_effort
    async with CopilotClient(**client_options) as client:
        async with await client.create_session(**session_options) as session:
            session.on(on_event)
            event = await session.send_and_wait(user_prompt, timeout=timeout)
    content = event.data.content if event is not None and isinstance(event.data, AssistantMessageData) else None
    return content, summarize_usage(usage_events, checkpoints)


RATE_LIMIT_RE = re.compile(r"rate.?limit|429|too many requests|quota|budget", re.I)


def complete_with_copilot(profile: Any, system_prompt: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
    from .providers import ProviderError

    if not sdk_available():
        raise ProviderError(INSTALL_HINT)
    token, source = resolve_token(profile)
    problem = token_problem(token, source)
    if problem:
        raise ProviderError(problem)
    try:
        content, usage = asyncio.run(_complete(profile, system_prompt, user_prompt, token, HTTP_TIMEOUT_SECONDS))
    except ProviderError:
        raise
    except Exception as exc:
        message = f"Copilot SDK ({profile.model}): {type(exc).__name__}: {exc}"
        raise ProviderError(message[:600], status=429 if RATE_LIMIT_RE.search(str(exc)) else None) from exc
    if not content or not content.strip():
        raise ProviderError("O modelo do Copilot retornou uma resposta vazia.")
    return content, usage


async def _list_models(token: str | None) -> list[dict[str, Any]]:
    import dataclasses

    from copilot import CopilotClient

    options: dict[str, Any] = {"mode": "empty", "base_directory": str(copilot_home())}
    if token:
        options["github_token"] = token
    async with CopilotClient(**options) as client:
        models = await client.list_models()

    def plain(value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            return {k: plain(v) for k, v in dataclasses.asdict(value).items() if v not in (None, [], {})}
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, list):
            return [plain(v) for v in value]
        return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)

    return [plain(model) for model in models]


def list_copilot_models(token: str | None) -> list[dict[str, Any]]:
    if not sdk_available():
        raise RuntimeError(INSTALL_HINT)
    return asyncio.run(_list_models(token))
