"""Session application that coordinates Sources, Templates, and Guardrails processes."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    # Only the interactive app reads .env, and before config is imported. Services
    # receive just the variables run_service forwards to them.
    from .envfile import load_env_file

    load_env_file()

from . import catalog as local_catalog
from . import messages, transcript
from .models import ProfileError, active_profile_name, describe_profiles, forwarded_env, resolve_profile
from .config import (
    CONTEXT_BUDGET_TOKENS,
    CONTEXT_WARN_RATIO,
    DATA_ROOT,
    MAX_REVISIONS,
    MODE,
    REPOSITORY_ROOT,
    SERVICE_TIMEOUT_SECONDS,
    SESSIONS_ROOT,
    validate_mode,
)


SERVICE_MODULES = {
    "sources": "cp_framework.services.sources",
    "templates": "cp_framework.services.templates",
    "guardrails": "cp_framework.services.guardrails",
}
ASCII_BANNER = r"""   ___                           _   _ _   _               ___                                               _
  / __\___  _ __ ___  _ __   ___| |_(_) |_(_)_   _____    / _ \_ __ ___   __ _ _ __ __ _ _ __ ___  _ __ ___ (_)_ __   __ _    /\  /\__ _ _ __ _ __   ___  ___ ___
 / /  / _ \| '_ ` _ \| '_ \ / _ \ __| | __| \ \ / / _ \  / /_)/ '__/ _ \ / _` | '__/ _` | '_ ` _ \| '_ ` _ \| | '_ \ / _` |  / /_/ / _` | '__| '_ \ / _ \/ __/ __|
/ /__| (_) | | | | | | |_) |  __/ |_| | |_| |\ V /  __/ / ___/| | | (_) | (_| | | | (_| | | | | | | | | | | | | | | (_| | / __  / (_| | |  | | | |  __/\__ \__ \
\____\___/|_| |_| |_| .__/ \___|\__|_| \__|_| \_/ \___| \/    |_|  \___/ \__, |_| \__,_|_| |_| |_|_| |_| |_|_|_|_|\__, | \/ /_/ \__,_|_|  |_| |_|\___||___/___/
                     |_|                                                 |___/                                       |___/"""
LEARNING_STATE_KEYS = ("topic", "topic_tags", "current_problems", "problem_plan", "progress_seen", "focus_problem", "solution_code")
SETTER_STATE_KEYS = (
    "topic", "topic_tags", "current_problems", "problem_plan", "problem_statement", "constraints",
    "solution_code", "stress_hypothesis", "stress_intro_shown", "statement_reviewed",
)
SETTER_TEMPLATES_WITH_SOLVER = {"setter_statement_review", "setter_stress_intro", "setter_stress_tests"}


def startup_banner(width: int) -> str | None:
    if max(map(len, ASCII_BANNER.splitlines())) <= width:
        return ASCII_BANNER
    return None


def service_timeout(name: str) -> float | None:
    if name == "templates" and resolve_profile().provider == "ollama":
        return None
    evaluator_profile = os.environ.get("CP_EVALUATOR_PROFILE") if name == "guardrails" else None
    if evaluator_profile and resolve_profile(evaluator_profile).provider == "ollama":
        return None
    return SERVICE_TIMEOUT_SECONDS


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
        "CP_SESSION_ID",
        "CP_TRANSCRIPT_DIR",
        "CP_TRANSCRIPTS",
        "CP_USAGE_LOG",
        "CP_PROMPT_VARIANT",
        "CP_MODELS_FILE",
        "CP_ALLOW_PAID",
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
        env.update(forwarded_env(active_profile_name()))
    if name == "guardrails":
        for key in ("CP_EVALUATOR_BACKEND", "CP_EVALUATOR_PROFILE"):
            if key in os.environ:
                env[key] = os.environ[key]
        if os.environ.get("CP_EVALUATOR_PROFILE"):
            evaluator_env = forwarded_env(os.environ["CP_EVALUATOR_PROFILE"])
            evaluator_env.pop("CP_LLM_PROFILE", None)
            env.update(evaluator_env)
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
        timeout=service_timeout(name),
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
    if stripped in {"/quit", "/exit", "/sair"}:
        return "", True
    if stripped == "/help":
        print(
            "Comandos: /learn <tema>, /setter <tema>, /retomar (/resume), /mode, /difficulty <escala>, "
            "/statement <enunciado>, /constraints <limites>, /hypothesis <falha provável>, "
            "/consolidar (/consolidate), /recomecar (/restart), /sync, /sair (/exit, /quit).\n\n"
            + messages.FLOW[language]
        )
        return "", False
    if stripped == "/mode":
        print(f"Modo atual: {session['mode']} | ambiente confiável: {MODE}")
        return "", False
    if stripped == "/model" or stripped.startswith("/model "):
        print(select_model(stripped[len("/model") :].strip()))
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


def _preflight_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    keys = ("status", "reason", "template_id", "mode", "language", "intents", "missing", "problem_refs", "scope", "progress_stage")
    summary = {key: preflight.get(key) for key in keys if preflight.get(key) is not None}
    if preflight.get("mode_transition"):
        summary["mode_transition"] = {k: preflight["mode_transition"].get(k) for k in ("from", "to", "trigger")}
    if (preflight.get("similar_problems") or {}).get("matches"):
        summary["similar_problems"] = [m.get("problem_id") for m in preflight["similar_problems"]["matches"]]
    return summary


def process_turn(prompt: str, session: dict[str, Any]) -> str:
    turn: dict[str, Any] = {"outcome": None, "attempts": []}
    session["_turn"] = turn
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
    turn["preflight"] = _preflight_summary(preflight)
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
        turn["outcome"] = str(preflight.get("status"))
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
        turn.update(outcome="sources_error", error=str(exc)[:500])
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
    turn.update(
        template_id=template_id,
        problem_ids=[item.get("id") for item in problems],
        problem_urls=[item.get("url") for item in problems if item.get("url")],
        article_paths=[item.get("path") for item in articles],
        problem_plan={k: problem_plan.get(k) for k in ("status", "tags", "capped", "veteran_blocked", "exhausted", "reused")},
        focus_problem=(session.get("focus_problem") or {}).get("id"),
        solver_cached=bool(reference),
    )
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
            turn.update(outcome="templates_error", error=str(exc)[:500])
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
            turn.update(outcome="guardrails_error", error=str(exc)[:500])
            return f"O serviço Guardrails não conseguiu avaliar a resposta: {exc}"
        last_result = guardrail_result
        turn["attempts"].append(
            {
                "candidate": candidate,
                "situations": candidate_result.get("situations"),
                "generation_profile": candidate_result.get("generation_profile"),
                "generation_model": candidate_result.get("generation_model"),
                "solver_ran": candidate_result.get("solver_ran"),
                "solver_status": (reference or {}).get("status"),
                "approved": bool(guardrail_result.get("approved")),
                "failed_checks": [c.get("id") for c in guardrail_result.get("deterministic_checks", []) if not c.get("passed")],
                "evaluation": guardrail_result.get("evaluation"),
            }
        )
        if guardrail_result.get("approved"):
            turn["outcome"] = "approved"
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
    turn["outcome"] = "guardrail_fallback"
    if MODE == "ADMIN" and last_result:
        return "Candidato retido pelos Guardrails.\n" + json.dumps(last_result, ensure_ascii=False, indent=2)
    return compose(prefixes, messages.text("guardrail_fallback", language))


def finish_turn(line: str, answer: str, session: dict[str, Any]) -> str:
    """Record the turn (history + transcript) and warn once when the context window is running low."""
    session["history"].append({"role": "user", "content": line})
    session["history"].append({"role": "assistant", "content": answer})
    session["history"] = session["history"][-16:]
    if not session.get("context_warned") and estimate_context_tokens(session) >= CONTEXT_WARN_RATIO * CONTEXT_BUDGET_TOKENS:
        session["context_warned"] = True
        answer += "\n\n---\n" + consolidation_message(session, warning=True)
        session["history"][-1]["content"] = answer
    transcript.write_turn(
        {
            "kind": "turn",
            "profile": os.environ.get("CP_LLM_PROFILE") or active_profile_name(),
            "prompt_variant": os.environ.get("CP_PROMPT_VARIANT", "full"),
            "mode": session.get("mode"),
            "topic_tags": session.get("topic_tags"),
            "stage": stage_of(session),
            "user": line,
            "answer": answer,
            "pipeline": session.pop("_turn", None),
        }
    )
    return answer


def run_command(line: str, session: dict[str, Any]) -> tuple[str, bool, str]:
    """apply_command with its printed output captured and recorded in the transcript."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        remaining, should_exit = apply_command(line, session)
    output = buffer.getvalue()
    if line.strip().startswith("/") and not remaining.strip():
        transcript.write_turn({"kind": "command", "user": line.strip(), "output": output.strip(), "mode": session.get("mode")})
    return remaining, should_exit, output


def render_markdown(text: str, glow_executable: str | None) -> None:
    if not text:
        return
    if glow_executable is None:
        print(text, end="")
        return

    width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns)
    try:
        result = subprocess.run(
            [glow_executable, "-w", str(width), "-"],
            input=text,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        print(f"Aviso: não foi possível executar Glow: {exc}. Exibindo Markdown sem formatação.", file=sys.stderr)
        print(text, end="")
        return
    if result.returncode:
        detail = result.stderr.strip() or f"código de saída {result.returncode}"
        print(f"Aviso: Glow falhou ({detail}). Exibindo Markdown sem formatação.", file=sys.stderr)
        print(text, end="")


def local_time() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


def new_session_id(prefix: str = "chat") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def model_banner() -> str:
    try:
        profile = resolve_profile()
    except ProfileError as exc:
        return f"modelo não configurado ({exc})"
    return f"modelo {profile.name} ({profile.model})"


def select_model(name: str) -> str:
    """/model lists profiles; /model <name> switches the chat model for the next turns."""
    if not name:
        return describe_profiles() + "\n\nAtual: " + model_banner() + "\nUse /model <perfil> para trocar."
    try:
        profile = resolve_profile(name)
    except ProfileError as exc:
        return str(exc)
    if profile.api_key_env and not profile.api_key():
        return f"O perfil '{name}' precisa da chave {profile.api_key_env} no .env."
    os.environ["CP_LLM_PROFILE"] = name
    return f"Modelo trocado para {profile.name} ({profile.model})."


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    import argparse

    parser = argparse.ArgumentParser(description="Sessão interativa do CP framework.")
    parser.add_argument("--model", help="perfil de modelo definido em models.json")
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="permite chamadas a modelos pagos nesta execução",
    )
    parser.add_argument("--check", "--verificar", action="store_true", help="verifica a configuração")
    parser.add_argument("--all", action="store_true", help="verifica todos os perfis (com --check)")
    parser.add_argument("--contexto", type=Path, help="arquivo com contexto consolidado")
    args = parser.parse_args(argv)
    if args.model:
        os.environ["CP_LLM_PROFILE"] = args.model
    if args.allow_paid:
        os.environ["CP_ALLOW_PAID"] = "1"
    if args.check:
        from .check import format_results, run_all_checks, run_checks

        if args.all:
            report, failed = run_all_checks()
            print(report)
            raise SystemExit(1 if failed else 0)
        results = run_checks()
        print(format_results(results))
        raise SystemExit(1 if any(item["status"] == "fail" for item in results) else 0)
    trusted_mode = validate_mode(MODE)
    try:
        resolve_profile()
    except ProfileError as exc:
        raise SystemExit(f"{exc}\nConfigure o modelo (veja `python -m cp_framework.models list`) e rode com --check.")
    terminal_width = shutil.get_terminal_size(fallback=(100, 24)).columns
    banner = startup_banner(terminal_width)
    if banner:
        print(banner)
    glow_executable = shutil.which("glow")
    if glow_executable is None:
        print(
            "Glow não encontrado. Instale com `winget install charmbracelet.glow`; "
            "as respostas serão exibidas sem formatação Markdown até lá."
        )
    os.environ.setdefault("CP_SESSION_ID", new_session_id())
    session = new_session()
    if args.contexto:
        session["consolidated_context"] = args.contexto.read_text(encoding="utf-8")
        print("Contexto consolidado carregado.")
    profile = resolve_profile()
    transcript.write_meta(
        {
            "kind": "chat",
            "session_id": os.environ["CP_SESSION_ID"],
            "profile": profile.name,
            "model": profile.model,
            "provider": profile.provider,
            "prompt_variant": os.environ.get("CP_PROMPT_VARIANT", "full"),
            "trusted_mode": trusted_mode,
            "consolidated_context": bool(session.get("consolidated_context")),
        }
    )
    print(f"CP framework pronto | {model_banner()} | /help para comandos | /sair para sair")
    session_dir = transcript.session_dir()
    if session_dir:
        print(f"Sessão gravada em {session_dir}")
    while True:
        try:
            line = input("\nVocê> ")
        except (EOFError, KeyboardInterrupt):
            print("\nSessão encerrada.")
            break
        if line.strip() and not line.lstrip().startswith("/"):
            print(f"[{local_time()}] Mensagem enviada.")
        line, should_exit, output = run_command(line, session)
        render_markdown(output, glow_executable)
        if should_exit:
            print("Sessão encerrada.")
            break
        if not line.strip():
            continue
        try:
            answer = process_turn(line, session)
        except Exception as exc:
            answer = f"Falha interna do manager: {exc}"
        answer = finish_turn(line, answer, session)
        print(f"\n[{local_time()}] Manager> ", end="", flush=True)
        render_markdown(answer, glow_executable)


if __name__ == "__main__":
    main()
