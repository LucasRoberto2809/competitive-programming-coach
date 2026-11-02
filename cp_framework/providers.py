from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import HTTP_TIMEOUT_SECONDS


class ProviderError(RuntimeError):
    pass


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
        raise ProviderError(f"HTTP {exc.code} em {url}: {detail}") from exc
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
    """OpenAI-compatible chat endpoint; provider and model are runtime config."""

    @staticmethod
    def configured() -> bool:
        return bool(os.environ.get("CP_LLM_MODEL"))

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        model = os.environ.get("CP_LLM_MODEL")
        if not model:
            raise ProviderError("Configure CP_LLM_MODEL para gerar respostas.")
        base_url = os.environ.get("CP_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        endpoint = os.environ.get(
            "CP_LLM_CHAT_COMPLETIONS_URL", f"{base_url}/chat/completions"
        )
        headers: dict[str, str] = {}
        api_key = os.environ.get("CP_LLM_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = post_json(
            endpoint,
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": float(os.environ.get("CP_LLM_TEMPERATURE", "0.2")),
            },
            headers,
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Resposta chat-completions não contém texto.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("O modelo retornou uma resposta vazia.")
        return content.strip()

