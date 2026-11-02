"""Session application that coordinates Sources, Templates, and Guardrails processes."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
from typing import Any

from .config import DATA_ROOT, MODE, MAX_REVISIONS, REPOSITORY_ROOT, validate_mode


SERVICE_MODULES = {
    "sources": "cp_framework.services.sources",
    "templates": "cp_framework.services.templates",
    "guardrails": "cp_framework.services.guardrails",
}
TOPIC_SYNONYMS = {
    "programação dinâmica": {"dp", "dynamic", "programming", "dynamic programming"},
    "programacao dinamica": {"dp", "dynamic", "programming", "dynamic programming"},
    "dynamic programming": {"dp", "dynamic", "programming"},
    "grafos": {"graph", "graphs", "bfs", "dfs", "shortest", "path"},
    "busca binária": {"binary", "search", "binary search"},
    "busca binaria": {"binary", "search", "binary search"},
    "binary search": {"binary", "search"},
    "árvore de segmentos": {"segment", "tree", "segment tree"},
    "arvore de segmentos": {"segment", "tree", "segment tree"},
    "segment tree": {"segment", "tree"},
    "soma de prefixos": {"prefix", "sum", "prefix sum"},
    "prefix sum": {"prefix", "sum"},
    "strings": {"string", "strings", "prefix", "hash"},
    "teoria dos números": {"number", "theory", "math", "gcd", "prime"},
    "number theory": {"number", "theory", "math", "gcd", "prime"},
}
TOKEN_RE = re.compile(r"[a-zA-Z0-9+#]+")


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


def topic_terms(topic: str) -> set[str]:
    lowered = topic.lower()
    terms = {word for word in TOKEN_RE.findall(lowered) if len(word) > 2}
    for phrase, synonyms in TOPIC_SYNONYMS.items():
        if phrase in lowered:
            terms.update(synonyms)
    return terms


def matching_score(topic: str, title: str, tags: list[str] | None = None) -> int:
    terms = topic_terms(topic)
    text = " ".join([title] + (tags or [])).lower()
    text_terms = set(TOKEN_RE.findall(text))
    score = len(terms & text_terms)
    for phrase in TOPIC_SYNONYMS:
        if phrase in topic.lower() and phrase in text:
            score += 3
    return score


def select_problem_refs(
    catalog: dict[str, Any], topic: str, difficulty_range: str = ""
) -> list[dict[str, Any]]:
    problems = catalog.get("problems", [])
    requested_range = re.search(r"(\d{3,4})\s*(?:-|–|to|a)\s*(\d{3,4})", difficulty_range, re.I)
    if requested_range:
        lower, upper = sorted((int(requested_range.group(1)), int(requested_range.group(2))))
        bands = [("requested_range", lambda rating: lower <= rating <= upper)]
    else:
        bands = [
            ("easy", lambda rating: 800 <= rating < 1000),
            ("medium", lambda rating: 1000 <= rating < 1500),
            ("hard", lambda rating: rating >= 1500),
        ]
    selected: list[dict[str, Any]] = []
    for label, predicate in bands:
        matches = []
        for problem in problems:
            rating = problem.get("rating")
            if not isinstance(rating, int) or not predicate(rating):
                continue
            relevance = matching_score(topic, str(problem.get("title", "")), problem.get("tags", []))
            if relevance:
                matches.append((relevance, int(problem.get("solved_count") or 0), problem))
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, problem in matches[:1]:
            selected.append({**problem, "difficulty_band": label})
    return selected


def select_article_paths(index: dict[str, Any], topic: str) -> list[str]:
    matches = []
    for article in index.get("articles", []):
        score = matching_score(topic, str(article.get("title", "")))
        if score:
            matches.append((score, article.get("path", "")))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _, path in matches[:5] if path]


def ensure_sources(topic: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    codeforces = read_snapshot("codeforces_problems.json")
    article_index = read_snapshot("cp_algorithms_index.json")
    if codeforces is None or article_index is None:
        run_service("sources", {"action": "sync"})
        codeforces = read_snapshot("codeforces_problems.json")
        article_index = read_snapshot("cp_algorithms_index.json")
    if codeforces is None or article_index is None:
        return [], []
    problems = select_problem_refs(codeforces, topic)
    article_paths = select_article_paths(article_index, topic)
    if article_paths:
        article_snapshot = read_snapshot("cp_algorithms_articles.json")
        existing_paths = {
            item.get("path") for item in (article_snapshot or {}).get("articles", [])
        }
        missing_paths = [path for path in article_paths if path not in existing_paths]
        if missing_paths:
            run_service("sources", {"action": "fetch_articles", "paths": missing_paths[:8]})
        article_snapshot = read_snapshot("cp_algorithms_articles.json")
        articles_by_path = {
            item.get("path"): item for item in (article_snapshot or {}).get("articles", [])
        }
        articles = [articles_by_path[path] for path in article_paths if path in articles_by_path]
    else:
        articles = []
    return problems, articles


def extract_fenced_code(prompt: str) -> str | None:
    matches = re.findall(r"```(?:[\w+#.-]+)?\s*\n(.*?)```", prompt, re.S)
    return matches[-1].strip() if matches else None


def apply_command(line: str, session: dict[str, Any]) -> tuple[str, bool]:
    stripped = line.strip()
    if stripped in {"/quit", "/exit"}:
        return "", True
    if stripped == "/help":
        print(
            "Comandos: /learn <tema>, /setter <tema>, /mode, /difficulty <escala>, "
            "/statement <enunciado>, /constraints <limites>, /hypothesis <falha provável>, /sync, /quit. "
            "Envie pseudocódigo na conversa; para stress tests, inclua o enunciado, limites e seu código."
        )
        return "", False
    if stripped == "/mode":
        print(f"Modo atual: {session['mode']} | ambiente confiável: {MODE}")
        return "", False
    if stripped.startswith("/learn"):
        session["mode"] = "LEARNING"
        session["topic"] = stripped[len("/learn") :].strip()
        session["progress_seen"] = False
        session["solution_code"] = ""
        session["stress_hypothesis"] = ""
        session["stress_intro_shown"] = False
        session["mode_selected_by_user"] = True
        print("Modo Aprendizado ativado." + (f" Tema: {session['topic']}" if session["topic"] else " Informe um tema."))
        return "", False
    if stripped.startswith("/setter"):
        session["mode"] = "PROBLEM_SETTER"
        new_topic = stripped[len("/setter") :].strip()
        if new_topic and new_topic != session.get("topic"):
            session["problem_statement"] = ""
            session["constraints"] = ""
            session["solution_code"] = ""
            session["stress_hypothesis"] = ""
            session["stress_intro_shown"] = False
        session["topic"] = new_topic
        session["mode_selected_by_user"] = True
        print("Modo Problem Setter ativado." + (f" Tema: {session['topic']}" if session["topic"] else ""))
        return "", False
    if stripped.startswith("/difficulty"):
        session["difficulty_range"] = stripped[len("/difficulty") :].strip()
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


def user_facing_block(decision: dict[str, Any]) -> str:
    missing = decision.get("missing", [])
    if missing:
        return (
            "Ainda não vou gerar os casos de estresse. Para seguir, envie: "
            + "; ".join(missing)
            + ". Se quiser começar pelo método, diga que quer entender como estressar o problema; "
            "nesse passo posso indicar exercícios semelhantes e explicar os limites que costumam causar falhas."
        )
    return str(decision.get("message", "Não foi possível seguir com esta solicitação."))


def process_turn(prompt: str, session: dict[str, Any]) -> str:
    if not session.get("mode_selected_by_user") and re.search(
        r"\b(stress\s*test|estress|casos? de teste|testes de estresse|gerar testes|gerar casos|"
        r"problem\s*setter|meu problema|minha solução)\b|"
        r"\b(crie|invente|gere)\s+(?:um|uma)\s+problema\b",
        prompt,
        re.I,
    ):
        session["mode"] = "PROBLEM_SETTER"
    if re.search(r"(?:problem\s*statement|statement|enunciado)\s*:", prompt, re.I):
        session["solution_code"] = ""
        session["stress_hypothesis"] = ""
        session["stress_intro_shown"] = False
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
            "session": session,
        },
        manager_token=session.get("manager_token"),
    )
    if preflight.get("status") != "ready":
        return user_facing_block(preflight)
    facts = preflight.get("facts", {})
    if facts.get("has_progress"):
        session["progress_seen"] = True
    if facts.get("has_problem_statement"):
        session["problem_statement"] = facts.get("problem_statement", "")
    if facts.get("has_constraints"):
        session["constraints"] = facts.get("constraints", "")
    if facts.get("has_user_code"):
        session["solution_code"] = facts.get("solution_code", "")
    if facts.get("has_stress_hypothesis"):
        session["stress_hypothesis"] = facts.get("stress_hypothesis", "")
    topic = str(session.get("topic") or prompt).strip()
    try:
        problems, articles = ensure_sources(topic)
        requested_range = session.get("difficulty_range", "")
        if re.search(r"\d{3,4}\s*(?:-|–|to|a)\s*\d{3,4}", requested_range, re.I):
            codeforces = read_snapshot("codeforces_problems.json") or {}
            problems = select_problem_refs(codeforces, topic, requested_range)
    except Exception as exc:
        return f"Não consegui atualizar as fontes locais: {exc}. Você pode tentar novamente com /sync."
    allowed_urls = [item.get("url") for item in problems + articles if item.get("url")]
    template_request = {
        "action": "render",
        "template_id": preflight["template_id"],
        "mode": preflight["mode"],
        "task_mode": "STRESS_TEST" if preflight["template_id"] == "setter_stress_tests" else "LEARNING",
        "prompt": prompt,
        "topic": topic,
        "difficulty_range": session.get("difficulty_range"),
        "progress_stage": preflight.get("progress_stage"),
        "history": session.get("history", []),
        "facts": facts,
        "problems": problems,
        "articles": articles,
    }
    retry_constraints: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for attempt in range(MAX_REVISIONS + 1):
        template_request["retry_constraints"] = retry_constraints
        try:
            candidate_result = run_service(
                "templates", template_request, manager_token=session.get("manager_token")
            )
        except Exception as exc:
            return f"O serviço Templates não conseguiu gerar a resposta: {exc}"
        candidate = str(candidate_result.get("candidate", ""))
        try:
            guardrail_result = run_service(
                "guardrails",
                {
                    "action": "postflight",
                    "template_id": preflight["template_id"],
                    "mode": preflight["mode"],
                    "prompt": prompt,
                    "facts": facts,
                    "candidate": candidate,
                    "sources": [item for item in problems + articles if item.get("url") in candidate],
                    "allowed_source_urls": allowed_urls,
                },
                manager_token=session.get("manager_token"),
            )
        except Exception as exc:
            return f"O serviço Guardrails não conseguiu avaliar a resposta: {exc}"
        last_result = guardrail_result
        if guardrail_result.get("approved"):
            if preflight["template_id"] == "setter_stress_intro":
                session["stress_intro_shown"] = True
            if MODE == "ADMIN":
                return (
                    candidate
                    + "\n\n---\nADMIN: "
                    + json.dumps(guardrail_result, ensure_ascii=False)
                )
            return candidate
        retry_constraints = guardrail_result.get("retry_constraints", [])
        if attempt >= MAX_REVISIONS:
            break
    if MODE == "ADMIN" and last_result:
        return "Candidato retido pelos Guardrails.\n" + json.dumps(last_result, ensure_ascii=False, indent=2)
    return "Não consegui preparar uma resposta que passasse pelos Guardrails. Tente reformular o pedido ou enviar mais contexto."


def main() -> None:
    trusted_mode = validate_mode(MODE)
    session: dict[str, Any] = {
        "mode": "LEARNING",
        "topic": "",
        "difficulty_range": "variada",
        "progress_seen": False,
        "problem_statement": "",
        "constraints": "",
        "solution_code": "",
        "stress_hypothesis": "",
        "stress_intro_shown": False,
        "history": [],
        "manager_token": secrets.token_urlsafe(32),
    }
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
        session["history"].append({"role": "user", "content": line})
        session["history"].append({"role": "assistant", "content": answer})
        session["history"] = session["history"][-16:]
        print(f"\nManager> {answer}")


if __name__ == "__main__":
    main()

