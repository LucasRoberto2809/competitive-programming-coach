"""Session application that coordinates Sources, Templates, and Guardrails processes."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import catalog as local_catalog
from . import messages
from .config import (
    CONTEXT_BUDGET_TOKENS,
    CONTEXT_WARN_RATIO,
    DATA_ROOT,
    MAX_REVISIONS,
    MODE,
    REPOSITORY_ROOT,
    SESSIONS_ROOT,
    validate_mode,
)


SERVICE_MODULES = {
    "sources": "cp_framework.services.sources",
    "templates": "cp_framework.services.templates",
    "guardrails": "cp_framework.services.guardrails",
}
LEARNING_STATE_KEYS = ("topic", "topic_tags", "current_problems", "problem_plan", "progress_seen", "focus_problem", "solution_code")
SETTER_STATE_KEYS = (
    "topic", "topic_tags", "current_problems", "problem_plan", "problem_statement", "constraints",
    "solution_code", "stress_hypothesis", "stress_intro_shown", "statement_reviewed",
)
SETTER_TEMPLATES_WITH_SOLVER = {"setter_statement_review", "setter_stress_intro", "setter_stress_tests"}


def run_service(
    name: str,
    payload: dict[str, Any],
    manager_token: str | None = None,
) -> dict[str, Any]:
    module = SERVICE_MODULES[name]
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONHOME"}
    }
    common_keys = {
        "CP_FRAMEWORK_ROOT",
        "CP_DATA_DIR",
        "CP_FRAMEWORK_MODE",
        "CP_MAX_REVISIONS",
        "CP_EVALUATOR_PASS_THRESHOLD",
        "CP_HTTP_TIMEOUT_SECONDS",
        "CP_REQUIRE_JEV",
    }
    for key in common_keys:
        if key in os.environ:
            env[key] = os.environ[key]
    env["CP_FRAMEWORK_ROOT"] = str(REPOSITORY_ROOT)
    env["PYTHONPATH"] = str(REPOSITORY_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    child_payload = dict(payload)
    if name == "sources" and "GITHUB_TOKEN" in os.environ:
        env["GITHUB_TOKEN"] = os.environ["GITHUB_TOKEN"]
    if name in {"templates", "guardrails"}:
        for key in {"TYPESAFE_API_KEY", "TYPESAFE_API_URL", "TYPESAFE_MODEL"}:
            if key in os.environ:
                env[key] = os.environ[key]
    if name == "templates":
        for key in {
            "CP_LLM_MODEL",
            "CP_LLM_BASE_URL",
            "CP_LLM_CHAT_COMPLETIONS_URL",
            "CP_LLM_API_KEY",
            "CP_LLM_TEMPERATURE",
        }:
            if key in os.environ:
                env[key] = os.environ[key]
    if name in {"templates", "guardrails"} and manager_token:
        env["CP_ORCHESTRATOR_TOKEN"] = manager_token
        child_payload["manager_token"] = manager_token
    result = subprocess.run(
        [sys.executable, "-m", module],
        input=json.dumps(child_payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        env=env,
        timeout=180,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Serviço {name} retornou saída inválida (exit {result.returncode}): {result.stderr[:1000]}"
        ) from exc
    if result.returncode != 0 or response.get("status") == "error":
        raise RuntimeError(response.get("error", result.stderr.strip() or f"Serviço {name} falhou."))
    return response


def read_snapshot(filename: str) -> dict[str, Any] | None:
    path = DATA_ROOT / filename
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_local_sources() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    catalog = local_catalog.load_catalog(DATA_ROOT)
    article_index = local_catalog.load_article_index(DATA_ROOT)
    if catalog is None or article_index is None:
        run_service("sources", {"action": "sync"})
        catalog = local_catalog.load_catalog(DATA_ROOT)
        article_index = local_catalog.load_article_index(DATA_ROOT)
    return catalog, article_index


def load_articles(paths: list[str]) -> list[dict[str, Any]]:
    if not paths:
        return []
    article_snapshot = read_snapshot("cp_algorithms_articles.json")
    existing_paths = {item.get("path") for item in (article_snapshot or {}).get("articles", [])}
    missing_paths = [path for path in paths if path not in existing_paths]
    if missing_paths:
        run_service("sources", {"action": "fetch_articles", "paths": missing_paths[:8]})
        article_snapshot = read_snapshot("cp_algorithms_articles.json")
    articles_by_path = {item.get("path"): item for item in (article_snapshot or {}).get("articles", [])}
    return [{**articles_by_path[path], "catalog_match": True} for path in paths if path in articles_by_path]


def new_session() -> dict[str, Any]:
    return {
        "mode": "LEARNING",
        "topic": "",
        "difficulty_range": "variada",
        "progress_seen": False,
        "problem_statement": "",
        "constraints": "",
        "solution_code": "",
        "stress_hypothesis": "",
        "stress_intro_shown": False,
        "statement_reviewed": False,
        "topic_tags": [],
        "current_problems": [],
        "shown_problem_ids": [],
        "problem_plan": None,
        "focus_problem": None,
        "references": {},
        "paused": {},
        "studied": [],
        "code_snippets": [],
        "language": "pt-BR",
        "consolidated_context": "",
        "context_warned": False,
        "history": [],
        "manager_token": secrets.token_urlsafe(32),
    }


def stage_of(session: dict[str, Any], mode: str | None = None) -> str:
    mode = mode or session.get("mode", "LEARNING")
    if mode == "LEARNING":
        if session.get("progress_seen"):
            return "tentativa enviada (pseudocódigo/código em análise)"
        if session.get("current_problems"):
            return "material inicial e problemas indicados"
        return "escolha de tema"
    if session.get("stress_intro_shown") and session.get("stress_hypothesis"):
        return "testes de estresse"
    if session.get("stress_intro_shown"):
        return "dimensões de estresse"
    if session.get("statement_reviewed"):
        return "enunciado revisado"
    if session.get("problem_statement"):
        return "enunciado recebido"
    return "texto inicial"


def topic_label(session: dict[str, Any]) -> str:
    return str(session.get("topic") or ", ".join(session.get("topic_tags", [])) or "sem tema")


def problem_refs_view(problems: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return [
        {"id": item.get("id"), "title": item.get("title"), "rating": item.get("rating"), "url": item.get("url")}
        for item in problems[:limit]
    ]


def snapshot_state(session: dict[str, Any]) -> dict[str, Any]:
    mode = session.get("mode", "LEARNING")
    return {
        "mode": mode,
        "mode_label": messages.mode_label(mode, session.get("language", "pt-BR")),
        "topic": topic_label(session),
        "topic_tags": session.get("topic_tags", []),
        "stage": stage_of(session),
        "difficulty_range": session.get("difficulty_range"),
        "problems_shown": problem_refs_view(session.get("current_problems") or []),
        "has_problem_statement": bool(session.get("problem_statement")),
    }


def has_progress_to_pause(session: dict[str, Any]) -> bool:
    if session.get("mode") == "LEARNING":
        return bool(session.get("current_problems") or session.get("progress_seen"))
    return bool(session.get("problem_statement"))


def pause_mode(session: dict[str, Any]) -> dict[str, Any]:
    """Save the current mode's state so /retomar can restore it exactly."""
    mode = session.get("mode", "LEARNING")
    keys = LEARNING_STATE_KEYS if mode == "LEARNING" else SETTER_STATE_KEYS
    snapshot = snapshot_state(session)
    session.setdefault("paused", {})[mode] = {
        "state": {key: copy.deepcopy(session.get(key)) for key in keys},
        "summary": snapshot,
    }
    session["solution_code"] = ""
    if mode == "LEARNING":
        session["progress_seen"] = False
        session["focus_problem"] = None
    return snapshot


def resume_mode(session: dict[str, Any]) -> str:
    language = session.get("language", "pt-BR")
    paused = session.get("paused") or {}
    target = next((mode for mode in ("LEARNING", "PROBLEM_SETTER") if mode != session.get("mode") and mode in paused), None)
    target = target or next(iter(paused), None)
    if not target:
        return messages.text("nothing_to_resume", language)
    if has_progress_to_pause(session) and target != session.get("mode"):
        pause_mode(session)
    saved = paused.pop(target)
    session.update(copy.deepcopy(saved["state"]))
    session["mode"] = target
    session["mode_selected_by_user"] = True
    summary = saved["summary"]
    return messages.text(
        "resumed", language, label=messages.mode_label(target, language), topic=summary["topic"], stage=summary["stage"]
    )


def record_studied(session: dict[str, Any]) -> None:
    if not session.get("topic_tags"):
        return
    session.setdefault("studied", []).append(
        {
            "mode": session.get("mode"),
            "topic": topic_label(session),
            "stage": stage_of(session),
            "problems": problem_refs_view(session.get("current_problems") or [], limit=20),
        }
    )
    session["studied"] = session["studied"][-12:]


def reset_for_new_topic(session: dict[str, Any], mode: str) -> None:
    """A new topic restarts the flow from the initial stage of the current mode."""
    record_studied(session)
    session["current_problems"] = []
    session["progress_seen"] = False
    session["solution_code"] = ""
    session["focus_problem"] = None
    if mode == "PROBLEM_SETTER":
        for key in ("problem_statement", "constraints", "stress_hypothesis"):
            session[key] = ""
        session["stress_intro_shown"] = False
        session["statement_reviewed"] = False


def prepare_sources(
    prompt: str, preflight: dict[str, Any], session: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], bool]:
    """Pick catalog problems and articles; reuse the current set unless the turn asks for more.

    Returns (problems, articles, plan, topic_changed) where topic_changed means an existing
    topic was replaced, which restarts the flow of the current mode.
    """
    catalog, article_index = load_local_sources()
    if catalog is None or article_index is None:
        return [], [], {"status": "catalog_unavailable", "tags": [], "bands": []}, False
    mode = preflight["mode"]
    intents = preflight.get("intents") or {}
    scope = preflight.get("scope") or {}
    turn_text = local_catalog.strip_code(prompt)
    request = local_catalog.parse_problem_request(turn_text, str(session.get("difficulty_range") or ""), mode)
    turn_tags = list(scope.get("tags") or [])
    current_tags = list(session.get("topic_tags") or [])
    if not current_tags and not turn_tags:
        turn_tags = local_catalog.resolve_tags(str(session.get("topic") or ""))
    asked_for_topic = bool(
        scope.get("topic_phrase") or request["explicit"] or intents.get("learning_intent") or intents.get("setter_intent")
    )
    topic_changed = bool(turn_tags) and turn_tags != current_tags and (not current_tags or asked_for_topic)
    if topic_changed:
        if current_tags:
            reset_for_new_topic(session, mode)
        session["topic_tags"] = turn_tags
        session["topic"] = ", ".join(turn_tags)
    tags = list(session.get("topic_tags") or [])
    plan_mode = (session.get("problem_plan") or {}).get("mode")
    if tags and (topic_changed or request["explicit"] or not session.get("current_problems") or plan_mode != mode):
        problems, plan = local_catalog.sample_problems(
            catalog, tags, request, exclude=set(session.get("shown_problem_ids", []))
        )
        plan["mode"] = mode
        session["current_problems"] = problems
        session["problem_plan"] = plan
        session["shown_problem_ids"] = list(
            dict.fromkeys([*session.get("shown_problem_ids", []), *(item["id"] for item in problems)])
        )
    elif not tags:
        session["current_problems"] = []
        session["problem_plan"] = {"status": "needs_topic", "tags": [], "bands": [], "mode": mode}
    problems = list(session.get("current_problems") or [])
    plan = dict(session.get("problem_plan") or {})
    plan["reused"] = bool(tags) and not (topic_changed or request["explicit"]) and bool(problems)
    articles = load_articles(local_catalog.select_article_paths(article_index, tags))
    return problems, articles, plan, topic_changed and bool(current_tags)


def solver_key_and_task(
    template_id: str, mode: str, facts: dict[str, Any], session: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    """The Solver runs on the first interaction with a problem; its result is cached per problem."""
    if mode == "LEARNING" and template_id.startswith("learning") and session.get("focus_problem"):
        focus = session["focus_problem"]
        return f"cf:{focus['id']}", {
            "mode": "LEARNING",
            "focus_problem": focus,
            "user_attempt": facts.get("solution_code") or "",
            "language": "cpp",
        }
    if mode == "PROBLEM_SETTER" and template_id in SETTER_TEMPLATES_WITH_SOLVER and facts.get("has_problem_statement"):
        statement = str(facts.get("problem_statement") or "")
        digest = hashlib.sha1((statement + "\n" + str(facts.get("constraints") or "")).encode("utf-8")).hexdigest()[:16]
        return f"st:{digest}", {
            "mode": "PROBLEM_SETTER",
            "problem_statement": statement,
            "constraints": facts.get("constraints", ""),
            "language": "cpp",
        }
    return None, None


def merge_similar(
    similar: dict[str, Any] | None, reference: dict[str, Any] | None, extra_urls: list[str]
) -> dict[str, Any] | None:
    """Add Solver-recognized problems (already verified against the catalog) to the preflight matches."""
    matches = list((similar or {}).get("matches") or [])
    if extra_urls:
        catalog_problems = (local_catalog.load_catalog(DATA_ROOT) or {}).get("problems", {})
        known = {match.get("url") for match in matches}
        relations = {item.get("problem_id"): item.get("relation") for item in (reference or {}).get("recognized_problems", [])}
        for pid, relation in relations.items():
            problem = catalog_problems.get(pid)
            if problem and problem.get("url") in extra_urls and problem.get("url") not in known:
                matches.append({"relation": relation, "evidence": "solver", "problem_id": pid, **local_catalog.match_fields(problem)})
    return {"matches": matches} if matches else similar


def similar_notice(similar: dict[str, Any] | None, language: str) -> str:
    matches = (similar or {}).get("matches") or []
    if not matches:
        return ""
    identical = [match for match in matches if match.get("relation") == "identical"]
    chosen = identical or matches
    listed = "; ".join(f"{m.get('problem_id')} {m.get('title')} ({m.get('url')})" for m in chosen[:3])
    return "\n\n" + messages.text("identical_problem" if identical else "similar_problem", language, listed=listed)


def transition_notice(transition: dict[str, Any], language: str) -> str:
    previous = transition.get("previous_state", {})
    return messages.text(
        "transition",
        language,
        from_label=messages.mode_label(transition.get("from", ""), language),
        to_label=messages.mode_label(transition.get("to", ""), language),
        topic=previous.get("topic", "sem tema"),
        stage=previous.get("stage", "início"),
    )


def estimate_context_tokens(session: dict[str, Any]) -> int:
    payload = {
        "history": session.get("history", []),
        "consolidated": session.get("consolidated_context", ""),
        "statement": session.get("problem_statement", ""),
        "code": session.get("solution_code", ""),
        "problems": session.get("current_problems", []),
    }
    return len(json.dumps(payload, ensure_ascii=False)) // 4


def build_consolidation(session: dict[str, Any]) -> str:
    """Summary to continue in a clean chat: topics studied, problems, and the user's code snippets."""
    language = session.get("language", "pt-BR")
    entries = list(session.get("studied", []))
    if session.get("topic_tags"):
        entries.append(
            {
                "mode": session.get("mode"),
                "topic": topic_label(session),
                "stage": stage_of(session),
                "problems": problem_refs_view(session.get("current_problems") or [], limit=20),
            }
        )
    lines = ["# Contexto consolidado" if language == "pt-BR" else "# Consolidated context", ""]
    lines.append(f"- Modo atual / current mode: {messages.mode_label(session.get('mode', 'LEARNING'), language)}")
    lines.append(f"- Etapa / stage: {stage_of(session)}")
    lines += ["", "## Temas estudados / topics studied"]
    lines += [f"- {e['topic']} ({messages.mode_label(e['mode'], language)}; {e['stage']})" for e in entries] or ["- (nenhum)"]
    lines += ["", "## Problemas de referência / reference problems"]
    seen: set[str] = set()
    for entry in entries:
        for problem in entry.get("problems", []):
            if problem.get("id") and problem["id"] not in seen:
                seen.add(problem["id"])
                lines.append(f"- {problem['id']} {problem.get('title')} (rating {problem.get('rating')}): {problem.get('url')}")
    if not seen:
        lines.append("- (nenhum)")
    snippets = session.get("code_snippets", [])[-2:]
    lines += ["", "## Trechos do seu código / your code snippets"]
    for snippet in snippets:
        lines += ["```", "\n".join(snippet.splitlines()[:20]), "```"]
    if not snippets:
        lines.append("- (nenhum)")
    if session.get("problem_statement"):
        lines += ["", "## Enunciado em desenvolvimento / statement in progress", session["problem_statement"][:800]]
    return "\n".join(lines)


def save_consolidation(summary: str) -> Path:
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_ROOT / f"contexto-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.md"
    path.write_text(summary, encoding="utf-8")
    return path


def consolidation_message(session: dict[str, Any], warning: bool) -> str:
    language = session.get("language", "pt-BR")
    summary = build_consolidation(session)
    path = save_consolidation(summary)
    session["last_consolidation"] = summary
    parts = []
    if warning:
        used = round(100 * estimate_context_tokens(session) / CONTEXT_BUDGET_TOKENS)
        parts.append(messages.text("context_low", language, used=used))
    parts += [summary, messages.text("consolidation_options", language, path=str(path))]
    return "\n\n".join(parts)


def restart_from_consolidation(session: dict[str, Any]) -> None:
    summary = session.get("last_consolidation") or build_consolidation(session)
    keep = {
        key: copy.deepcopy(session.get(key))
        for key in ("mode", "topic", "topic_tags", "shown_problem_ids", "language", "difficulty_range", "studied")
    }
    token = session.get("manager_token")
    session.clear()
    session.update(new_session())
    session.update(keep)
    session["manager_token"] = token or session["manager_token"]
    session["consolidated_context"] = summary


def extract_fenced_code(prompt: str) -> str | None:
    matches = re.findall(r"```(?:[\w+#.-]+)?\s*\n(.*?)```", prompt, re.S)
    return matches[-1].strip() if matches else None


def switch_mode_command(session: dict[str, Any], mode: str, topic: str) -> str:
    """Explicit /learn or /setter: pause the current stage visibly, then start the requested one."""
    language = session.get("language", "pt-BR")
    lines = []
    if session.get("mode") != mode and has_progress_to_pause(session):
        snapshot = pause_mode(session)
        lines.append(
            messages.text(
                "transition",
                language,
                from_label=snapshot["mode_label"],
                to_label=messages.mode_label(mode, language),
                topic=snapshot["topic"],
                stage=snapshot["stage"],
            )
        )
    tags = local_catalog.resolve_tags(topic)
    if topic and tags != session.get("topic_tags"):
        record_studied(session)
        session["topic_tags"] = tags
        session["current_problems"] = []
        session["focus_problem"] = None
    session["mode"] = mode
    session["topic"] = topic or session.get("topic", "")
    session["mode_selected_by_user"] = True
    if topic:
        lines.append(messages.text("topic_change", language, topic=topic))
    label = messages.mode_label(mode, language)
    lines.append(f"Modo {label} ativado." if language == "pt-BR" else f"{label} mode on.")
    return "\n".join(lines)


def apply_command(line: str, session: dict[str, Any]) -> tuple[str, bool]:
    stripped = line.strip()
    language = session.get("language", "pt-BR")
    if stripped in {"/quit", "/exit"}:
        return "", True
    if stripped == "/help":
        print(
            "Comandos: /learn <tema>, /setter <tema>, /retomar (/resume), /mode, /difficulty <escala>, "
            "/statement <enunciado>, /constraints <limites>, /hypothesis <falha provável>, "
            "/consolidar (/consolidate), /recomecar (/restart), /sync, /quit.\n\n" + messages.FLOW[language]
        )
        return "", False
    if stripped == "/mode":
        print(f"Modo atual: {session['mode']} | ambiente confiável: {MODE}")
        return "", False
    if stripped.startswith("/learn"):
        print(switch_mode_command(session, "LEARNING", stripped[len("/learn") :].strip()))
        session["progress_seen"] = False
        session["solution_code"] = ""
        return "", False
    if stripped.startswith("/setter"):
        new_topic = stripped[len("/setter") :].strip()
        if new_topic and new_topic != session.get("topic"):
            for key in ("problem_statement", "constraints", "solution_code", "stress_hypothesis"):
                session[key] = ""
            session["stress_intro_shown"] = False
            session["statement_reviewed"] = False
        print(switch_mode_command(session, "PROBLEM_SETTER", new_topic))
        return "", False
    if stripped in {"/retomar", "/resume"}:
        print(resume_mode(session))
        return "", False
    if stripped in {"/consolidar", "/consolidate"}:
        print(consolidation_message(session, warning=False))
        return "", False
    if stripped in {"/recomecar", "/recomeçar", "/restart"}:
        restart_from_consolidation(session)
        print(
            "Chat limpo; o resumo consolidado é o contexto inicial."
            if language == "pt-BR"
            else "Chat cleared; the consolidated summary is now the initial context."
        )
        return "", False
    if stripped.startswith("/difficulty"):
        session["difficulty_range"] = stripped[len("/difficulty") :].strip()
        session["current_problems"] = []
        print(f"Faixa de dificuldade registrada: {session['difficulty_range']}")
        return "", False
    if stripped == "/sync":
        try:
            print(json.dumps(run_service("sources", {"action": "sync"}), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"Falha ao sincronizar Sources: {exc}")
        return "", False
    if stripped.startswith("/statement"):
        session["problem_statement"] = stripped[len("/statement") :].strip()
        session["solution_code"] = ""
        session["stress_hypothesis"] = ""
        session["stress_intro_shown"] = False
        session["statement_reviewed"] = False
        print("Enunciado registrado nesta sessão.")
        return "", False
    if stripped.startswith("/constraints"):
        session["constraints"] = stripped[len("/constraints") :].strip()
        print("Limites registrados nesta sessão.")
        return "", False
    if stripped.startswith("/hypothesis"):
        session["stress_hypothesis"] = stripped[len("/hypothesis") :].strip()
        print("Hipótese de estresse registrada nesta sessão.")
        return "", False
    return line, False


def compose(prefixes: list[str], body: str, suffix: str = "") -> str:
    return "\n\n".join([item for item in prefixes if item] + [body]) + suffix


def process_turn(prompt: str, session: dict[str, Any]) -> str:
    if re.search(r"(?:problem\s*statement|statement|enunciado)\s*:", prompt, re.I):
        session["solution_code"] = ""
        session["stress_hypothesis"] = ""
        session["stress_intro_shown"] = False
        session["statement_reviewed"] = False
    fenced_code = extract_fenced_code(prompt)
    if fenced_code:
        session["solution_code"] = fenced_code
    preflight = run_service(
        "guardrails",
        {
            "action": "preflight",
            "trusted_mode": MODE,
            "mode": session["mode"],
            "prompt": prompt,
            "session": {key: value for key, value in session.items() if key not in {"references", "paused", "history"}},
        },
        manager_token=session.get("manager_token"),
    )
    language = preflight.get("language") or session.get("language", "pt-BR")
    session["language"] = language
    prefixes: list[str] = []
    transition = preflight.get("mode_transition")
    if transition:
        snapshot = pause_mode(session) if has_progress_to_pause(session) else snapshot_state(session)
        transition = {**transition, "previous_state": snapshot}
        preflight["mode_transition"] = transition
        session["mode"] = preflight["mode"]
        session["last_transition"] = transition
        prefixes.append(transition_notice(transition, language))
        if fenced_code:
            session["solution_code"] = fenced_code
    similar = preflight.get("similar_problems")
    if preflight.get("status") != "ready":
        body = str(preflight.get("message") or messages.text("guardrail_fallback", language))
        return compose(prefixes, body, similar_notice(similar, language))

    facts = preflight.get("facts", {})
    if facts.get("has_progress") and preflight["mode"] == "LEARNING":
        session["progress_seen"] = True
    for key, flag in (
        ("problem_statement", "has_problem_statement"),
        ("constraints", "has_constraints"),
        ("solution_code", "has_user_code"),
        ("stress_hypothesis", "has_stress_hypothesis"),
    ):
        if facts.get(flag):
            session[key] = facts.get(key, "")
    if facts.get("turn_has_attempt"):
        snippet = fenced_code or local_catalog.strip_code(prompt).strip()
        session.setdefault("code_snippets", []).append(snippet[:2000])
        session["code_snippets"] = session["code_snippets"][-5:]

    try:
        problems, articles, problem_plan, topic_changed = prepare_sources(prompt, preflight, session)
    except Exception as exc:
        return f"Não consegui atualizar as fontes locais: {exc}. Você pode tentar novamente com /sync."
    template_id = preflight["template_id"]
    if topic_changed:
        prefixes.append(messages.text("topic_change", language, topic=topic_label(session)))
        if preflight["mode"] == "LEARNING" and not facts.get("turn_has_attempt"):
            template_id = "learning_start"
        elif preflight["mode"] == "PROBLEM_SETTER" and not facts.get("statement_in_turn"):
            template_id = "setter_refusal"
    refs = preflight.get("problem_refs") or []
    if refs:
        catalog_problems = (local_catalog.load_catalog(DATA_ROOT) or {}).get("problems", {})
        problem = catalog_problems.get(refs[0])
        if problem:
            session["focus_problem"] = {"id": refs[0], **local_catalog.match_fields(problem), "tags": problem.get("tags", [])}

    solver_key, solver_task = solver_key_and_task(template_id, preflight["mode"], facts, session)
    reference = (session.get("references") or {}).get(solver_key) if solver_key else None
    topic = topic_label(session) if session.get("topic_tags") or session.get("topic") else prompt.strip()
    previous_problems = (transition or {}).get("previous_state", {}).get("problems_shown", [])
    focus = session.get("focus_problem")
    template_request = {
        "action": "render",
        "template_id": template_id,
        "mode": preflight["mode"],
        "task_mode": "STRESS_TEST" if template_id == "setter_stress_tests" else preflight["mode"],
        "prompt": prompt,
        "topic": topic,
        "difficulty_range": session.get("difficulty_range"),
        "progress_stage": preflight.get("progress_stage"),
        "history": session.get("history", []),
        "consolidated_context": session.get("consolidated_context") or None,
        "facts": facts,
        "problems": problems,
        "articles": articles,
        "intents": preflight.get("intents"),
        "mode_transition": transition,
        "problem_plan": problem_plan,
        "similar_problems": similar,
        "focus_problem": focus,
        "reference_solution": reference,
        "solver_task": None if reference else solver_task,
        "language": language,
        "supported_topics": sorted(local_catalog.TAG_SYNONYMS),
    }
    base_urls = [
        item.get("url")
        for item in problems + articles + ((similar or {}).get("matches") or []) + previous_problems + ([focus] if focus else [])
        if item and item.get("url")
    ]
    retry_constraints: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for attempt in range(MAX_REVISIONS + 1):
        template_request["retry_constraints"] = retry_constraints
        try:
            candidate_result = run_service("templates", template_request, manager_token=session.get("manager_token"))
        except Exception as exc:
            return f"O serviço Templates não conseguiu gerar a resposta: {exc}"
        if candidate_result.get("solver_ran") and solver_key:
            reference = candidate_result.get("reference_solution")
            if (reference or {}).get("status") != "invalid_output":
                session.setdefault("references", {})[solver_key] = reference
            template_request["reference_solution"] = reference
            template_request["solver_task"] = None
        extra_urls = list(candidate_result.get("extra_source_urls") or [])
        candidate = str(candidate_result.get("candidate", ""))
        try:
            guardrail_result = run_service(
                "guardrails",
                {
                    "action": "postflight",
                    "template_id": template_id,
                    "mode": preflight["mode"],
                    "prompt": prompt,
                    "facts": facts,
                    "candidate": candidate,
                    "sources": [item for item in problems + articles if item.get("url") in candidate],
                    "allowed_source_urls": base_urls + extra_urls,
                    "reference_code": (reference or {}).get("solution_code", ""),
                },
                manager_token=session.get("manager_token"),
            )
        except Exception as exc:
            return f"O serviço Guardrails não conseguiu avaliar a resposta: {exc}"
        last_result = guardrail_result
        if guardrail_result.get("approved"):
            if template_id == "setter_stress_intro":
                session["stress_intro_shown"] = True
            if template_id == "setter_statement_review":
                session["statement_reviewed"] = True
            notice = similar_notice(merge_similar(similar, reference, extra_urls), language)
            answer = compose(prefixes, candidate, notice)
            if MODE == "ADMIN":
                answer += "\n\n---\nADMIN: " + json.dumps(guardrail_result, ensure_ascii=False)
            return answer
        retry_constraints = guardrail_result.get("retry_constraints", [])
        if attempt >= MAX_REVISIONS:
            break
    if MODE == "ADMIN" and last_result:
        return "Candidato retido pelos Guardrails.\n" + json.dumps(last_result, ensure_ascii=False, indent=2)
    return compose(prefixes, messages.text("guardrail_fallback", language))


def finish_turn(line: str, answer: str, session: dict[str, Any]) -> str:
    """Record the turn and warn once when the context window is running low."""
    session["history"].append({"role": "user", "content": line})
    session["history"].append({"role": "assistant", "content": answer})
    session["history"] = session["history"][-16:]
    if not session.get("context_warned") and estimate_context_tokens(session) >= CONTEXT_WARN_RATIO * CONTEXT_BUDGET_TOKENS:
        session["context_warned"] = True
        answer += "\n\n---\n" + consolidation_message(session, warning=True)
        session["history"][-1]["content"] = answer
    return answer


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    trusted_mode = validate_mode(MODE)
    session = new_session()
    if "--contexto" in argv:
        position = argv.index("--contexto")
        if position + 1 < len(argv):
            session["consolidated_context"] = Path(argv[position + 1]).read_text(encoding="utf-8")
            print("Contexto consolidado carregado.")
    print(f"CP framework pronto | perfil {trusted_mode} | /help para comandos | /quit para sair")
    print("O modo ADMIN vem apenas da configuração confiável CP_FRAMEWORK_MODE.")
    while True:
        try:
            line = input("\nVocê> ")
        except (EOFError, KeyboardInterrupt):
            print("\nSessão encerrada.")
            break
        line, should_exit = apply_command(line, session)
        if should_exit:
            print("Sessão encerrada.")
            break
        if not line.strip():
            continue
        try:
            answer = process_turn(line, session)
        except Exception as exc:
            answer = f"Falha interna do manager: {exc}"
        print(f"\nManager> {finish_turn(line, answer, session)}")


if __name__ == "__main__":
    main()
