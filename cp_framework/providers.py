from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import HTTP_TIMEOUT_SECONDS


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


RETRYABLE_STATUS = {429, 502, 503}


def _retry_after_seconds(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


def post_json(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read(4_000_001)
    except HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace")
        retry_after = _retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None)
        exc.close()
        raise ProviderError(f"HTTP {exc.code} em {url}: {detail}", status=exc.code, retry_after=retry_after) from exc
    except (URLError, TimeoutError) as exc:
        raise ProviderError(f"Falha ao conectar a {url}: {exc}") from exc
    if len(payload) > 4_000_000:
        raise ProviderError("Resposta do provedor excedeu 4 MB.")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProviderError("O provedor retornou JSON inválido.") from exc
    if not isinstance(value, dict):
        raise ProviderError("A resposta do provedor não é um objeto JSON.")
    return value


class JevClient:
    """Small HTTP adapter for TypeSafe's typed-decision API."""

    endpoint = os.environ.get("TYPESAFE_API_URL", "https://api.typesafe.ai/v1/systemone")
    model = os.environ.get("TYPESAFE_MODEL", "jev-latest")

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("TYPESAFE_API_KEY"))

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            raise ProviderError("TYPESAFE_API_KEY não está configurada.")
        response = post_json(
            self.endpoint,
            {"model": self.model, "state": state, "questions": questions},
            {"Authorization": f"Bearer {api_key}"},
        )
        answers = response.get("answers")
        if answers is None:
            answers = response.get("data", {}).get("result", {}).get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("Resposta Jev sem o mapa 'answers'.")
        return answers


class ChatCompletionsClient:
    """Chat model client for OpenAI-compatible APIs, Ollama, or the Copilot SDK."""

    def __init__(self, profile: Any = None) -> None:
        self._profile = profile

    @staticmethod
    def configured() -> bool:
        from .models import ProfileError, resolve_profile

        try:
            resolve_profile()
        except ProfileError:
            return False
        return True

    @property
    def profile(self) -> Any:
        from .models import ModelProfile, ProfileError, resolve_profile

        if isinstance(self._profile, ModelProfile):
            return self._profile
        try:
            self._profile = resolve_profile(self._profile)
        except ProfileError as exc:
            raise ProviderError(str(exc)) from exc
        return self._profile

    def _http_call(self, profile: Any, system_prompt: str, user_prompt: str, json_output: bool) -> tuple[str, dict[str, Any] | None]:
        headers = dict(profile.headers)
        api_key = profile.api_key()
        if profile.api_key_env and not api_key:
            raise ProviderError(f"A chave do perfil '{profile.name}' não está definida: coloque {profile.api_key_env}=... no .env.")
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": profile.temperature,
            **profile.extra_body,
        }
        if profile.max_tokens:
            body["max_tokens"] = profile.max_tokens
        if json_output and profile.json_mode:
            body["response_format"] = {"type": "json_object"}
        response = post_json(profile.endpoint, body, headers)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Resposta chat-completions não contém texto.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("O modelo retornou uma resposta vazia.")
        return content, usage

    def _ollama_call(self, profile: Any, system_prompt: str, user_prompt: str, json_output: bool) -> tuple[str, dict[str, Any] | None]:
        try:
            from ollama import Client, ResponseError
        except ImportError as exc:
            raise ProviderError("O SDK Ollama não está instalado. Instale as dependências do projeto com `uv sync`.") from exc

        options: dict[str, Any] = {"temperature": profile.temperature}
        if profile.max_tokens:
            options["num_predict"] = profile.max_tokens
        try:
            with Client(host=profile.base_url, timeout=None) as client:
                response = client.chat(
                    model=profile.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    options=options,
                    format="json" if json_output and profile.json_mode else None,
                )
        except ResponseError as exc:
            detail = exc.error
            if exc.status_code == 404:
                detail = f"modelo '{profile.model}' não encontrado. Baixe-o com `ollama pull {profile.model}`."
            raise ProviderError(f"Ollama: {detail}", status=exc.status_code) from exc
        except ConnectionError as exc:
            raise ProviderError(
                "Não foi possível conectar ao Ollama. Inicie o Ollama e confirme que ele está acessível em "
                f"{profile.base_url}."
            ) from exc

        content = response.message.content
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("O Ollama retornou uma resposta vazia.")
        usage = {
            key: value
            for key, value in {
                "prompt_tokens": response.prompt_eval_count,
                "completion_tokens": response.eval_count,
            }.items()
            if value is not None
        }
        return content, usage or None

    def complete(self, system_prompt: str, user_prompt: str, *, json_output: bool = False, purpose: str = "chat") -> str:
        from . import transcript

        profile = self.profile
        if profile.provider == "copilot":
            from .copilot_backend import complete_with_copilot

            def call() -> tuple[str, dict[str, Any] | None]:
                return complete_with_copilot(profile, system_prompt, user_prompt)
        elif profile.provider == "ollama":
            def call() -> tuple[str, dict[str, Any] | None]:
                return self._ollama_call(profile, system_prompt, user_prompt, json_output)
        else:
            def call() -> tuple[str, dict[str, Any] | None]:
                return self._http_call(profile, system_prompt, user_prompt, json_output)

        retries = max(0, int(os.environ.get("CP_LLM_RETRIES", "2")))
        backoff = float(os.environ.get("CP_LLM_RETRY_BASE_SECONDS", "2"))
        for attempt in range(retries + 1):
            started = time.perf_counter()
            try:
                content, usage = call()
                break
            except ProviderError as exc:
                elapsed = time.perf_counter() - started
                record_usage(profile, purpose, elapsed, None, error=str(exc), attempt=attempt)
                transcript.write_call(
                    profile=profile, purpose=purpose, system_prompt=system_prompt, user_prompt=user_prompt,
                    response=None, usage=None, latency_ms=round(elapsed * 1000), attempt=attempt, error=str(exc),
                )
                if exc.status not in RETRYABLE_STATUS or attempt >= retries:
                    if exc.status == 429:
                        raise ProviderError(
                            f"O modelo {profile.model} está com limite de uso (HTTP 429) no momento. "
                            "Tente de novo em instantes ou troque de modelo com /model.",
                            status=429,
                        ) from exc
                    raise
                time.sleep(min(30.0, exc.retry_after if exc.retry_after is not None else backoff * (2**attempt)))
        elapsed = time.perf_counter() - started
        record_usage(profile, purpose, elapsed, usage, attempt=attempt)
        transcript.write_call(
            profile=profile, purpose=purpose, system_prompt=system_prompt, user_prompt=user_prompt,
            response=content, usage=usage, latency_ms=round(elapsed * 1000), attempt=attempt,
        )
        return content.strip()


def usage_log_path() -> Path | None:
    from . import config

    value = os.environ.get("CP_USAGE_LOG", "")
    if value.strip().lower() in {"0", "false", "off", "no"}:
        return None
    return Path(value) if value else config.DATA_ROOT.parent / "runs" / "usage.jsonl"


EXTRA_USAGE_FIELDS = (
    "reasoning_tokens", "cache_read_tokens", "cache_write_tokens", "api_calls", "copilot_cost", "nano_aiu",
    "model_ms", "served_models",
)


def record_usage(
    profile: Any, purpose: str, seconds: float, usage: dict[str, Any] | None, error: str | None = None, attempt: int = 0
) -> None:
    """Append one JSON line per model call: the raw data for the cost/performance benchmark."""
    path = usage_log_path()
    if path is None:
        return
    usage = usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    reported_cost = usage.get("cost")
    list_cost = profile.list_cost_usd(prompt_tokens, completion_tokens)
    billed = profile.cost_usd(prompt_tokens, completion_tokens)
    nano_aiu = usage.get("nano_aiu")
    if isinstance(nano_aiu, (int, float)):
        # Copilot bills in AI credits (US$ 0.01); nano_aiu = credits x 1e9, cache discounts included.
        cost, source = nano_aiu * 1e-11, "copilot_billed"
    elif isinstance(reported_cost, (int, float)):
        cost, source = reported_cost, "provider"
    else:
        cost, source = billed, "profile_price" if billed is not None else "unknown"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": os.environ.get("CP_SESSION_ID"),
        "profile": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "prompt_variant": os.environ.get("CP_PROMPT_VARIANT", "full"),
        "purpose": purpose,
        "latency_ms": round(seconds * 1000),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost,
        "list_cost_usd": list_cost,
        "cost_source": source,
        "status": "error" if error else "ok",
        "attempt": attempt,
        "error": (error or "")[:300] or None,
    }
    record.update({key: usage[key] for key in EXTRA_USAGE_FIELDS if key in usage})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
