"""`python -m cp_framework.app --check [--model P] [--all]`: validate configuration and test models."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import catalog as local_catalog
from .config import DATA_ROOT, MODE, REQUIRE_JEV, validate_mode
from .models import ModelProfile, ProfileError, load_profiles, paid_allowed, resolve_profile
from .providers import ChatCompletionsClient, JevClient, ProviderError


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def probe_model(client: ChatCompletionsClient) -> dict[str, Any]:
    """Two small calls: plain chat and structured JSON. Never prints secrets."""
    result: dict[str, Any] = {"chat": "fail", "json": "fail", "latency_s": None, "detail": ""}
    try:
        started = time.perf_counter()
        reply = client.complete("Você é um teste de conexão.", "Responda exatamente: OK", purpose="check")
        result["latency_s"] = round(time.perf_counter() - started, 2)
        result["chat"] = "ok"
        result["detail"] = f"respondeu {reply[:40]!r}"
    except ProviderError as exc:
        result["detail"] = str(exc)[:300]
        return result
    try:
        raw = client.complete(
            "Responda somente com um objeto JSON válido, sem texto fora dele.",
            'Devolva exatamente este objeto: {"status": "solved", "language": "cpp", "steps": ["a", "b"]}',
            json_output=True,
            purpose="check",
        )
    except ProviderError as exc:
        result["detail"] = str(exc)[:300]
        return result
    value = _parse_json_object(raw)
    if value and value.get("status") == "solved" and isinstance(value.get("steps"), list):
        result["json"] = "ok"
    else:
        result["json"] = "warn"
        result["detail"] += f"; JSON inválido: {re.sub(chr(10), ' ', raw)[:80]!r}"
    return result


def run_checks(client: ChatCompletionsClient | None = None) -> list[dict[str, Any]]:
    """Return check results: {id, status: ok|warn|fail, detail}."""
    results: list[dict[str, Any]] = []

    def add(check_id: str, status: str, detail: str) -> None:
        results.append({"id": check_id, "status": status, "detail": detail})

    try:
        add("mode", "ok", f"perfil {validate_mode(MODE)}")
    except ValueError as exc:
        add("mode", "fail", str(exc))

    profile: ModelProfile | None = None
    try:
        profile = resolve_profile()
        add("model_profile", "ok", f"{profile.name}: {profile.model} | {profile.endpoint} | "
            f"{'gratuito' if profile.is_free() else 'PAGO'} | chave {profile.key_status()}")
        if profile.provider == "copilot":
            from .copilot_backend import resolve_token, sdk_available, token_problem

            token, source = resolve_token(profile)
            problem = token_problem(token, source) or (None if sdk_available() else "Copilot SDK não instalado neste Python.")
            add("api_key", "fail" if problem else "ok", problem or f"token do Copilot via {source}")
        elif profile.api_key_env and not profile.api_key():
            add("api_key", "fail", f"coloque {profile.api_key_env}=... no .env")
    except ProfileError as exc:
        add("model_profile", "fail", str(exc))

    catalog = local_catalog.load_catalog(DATA_ROOT)
    articles = local_catalog.load_article_index(DATA_ROOT)
    if catalog and articles:
        add("catalog", "ok", f"{catalog.get('problem_count')} problemas, {len(articles.get('articles', []))} artigos")
    else:
        add("catalog", "warn", "catálogo local ausente; o app sincroniza na primeira mensagem (ou use /sync).")

    evaluator = os.environ.get("CP_EVALUATOR_PROFILE")
    if JevClient.available():
        add("evaluator", "ok", "Jev configurado.")
    elif evaluator:
        try:
            resolve_profile(evaluator)
            add("evaluator", "ok", f"avaliação pelo perfil {evaluator}.")
        except ProfileError as exc:
            add("evaluator", "fail", str(exc))
    elif REQUIRE_JEV:
        add("evaluator", "fail", "CP_REQUIRE_JEV=1, mas não há Jev nem CP_EVALUATOR_PROFILE.")
    else:
        add("evaluator", "warn", "sem avaliador: respostas passam pelos guardrails, mas ficam sem nota.")

    if profile is None or any(item["status"] == "fail" for item in results):
        return results
    probe = probe_model(client or ChatCompletionsClient(profile))
    if probe["chat"] != "ok":
        add("model_chat", "fail", probe["detail"])
        return results
    add("model_chat", "ok", f"{probe['latency_s']}s, {probe['detail']}")
    if probe["json"] == "ok":
        add("model_json", "ok", "respostas estruturadas (JSON) funcionam; o Solver pode ser usado.")
    else:
        add("model_json", "warn", "o modelo não devolveu o JSON pedido; o Solver ficará indisponível com ele.")
    return results


def format_results(results: list[dict[str, Any]]) -> str:
    icons = {"ok": "[ok]   ", "warn": "[aviso]", "fail": "[falha]"}
    lines = [f"{icons[item['status']]} {item['id']}: {item['detail']}" for item in results]
    failed = any(item["status"] == "fail" for item in results)
    lines += ["", "Configuração com falhas: corrija o .env/models.json e rode --check novamente."
              if failed else "Tudo pronto. Inicie o chat sem --check."]
    return "\n".join(lines)


def run_all_checks() -> tuple[str, bool]:
    """Probe every profile that is free (or allowed) and has its key; a first benchmark table."""
    rows = ["perfil | modelo | chat | JSON | latência | observação", "---|---|---|---|---|---"]
    tested = 0
    for name, profile in sorted(load_profiles().items()):
        if not profile.model:
            rows.append(f"{name} | - | - | - | - | sem modelo definido")
            continue
        if not profile.is_free() and not paid_allowed():
            rows.append(f"{name} | {profile.model} | - | - | - | pago: ignorado (CP_ALLOW_PAID=0)")
            continue
        if profile.api_key_env and not profile.api_key():
            rows.append(f"{name} | {profile.model} | - | - | - | sem chave ({profile.api_key_env})")
            continue
        tested += 1
        probe = probe_model(ChatCompletionsClient(profile))
        latency = f"{probe['latency_s']}s" if probe["latency_s"] is not None else "-"
        rows.append(f"{name} | {profile.model} | {probe['chat']} | {probe['json']} | {latency} | {probe['detail'][:80]}")
    rows.append("")
    rows.append(f"{tested} perfil(is) testado(s). Cada chamada foi registrada no log de uso (data/runs/usage.jsonl).")
    return "\n".join(rows), tested == 0
