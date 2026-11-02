"""Guardrails service: deterministic input/output gates and score-only Jev evaluation."""

from __future__ import annotations

import re
import hmac
import os
from typing import Any

from ..config import MODE, PASS_THRESHOLD, REQUIRE_JEV, validate_mode
from ..io import run_cli
from ..providers import JevClient
from ..skills import load_skill


LEARNING_RUBRIC = {
    "source_fidelity": 25,
    "learner_fit": 20,
    "pedagogy": 25,
    "problem_references": 10,
    "format_boundary": 20,
}
STRESS_RUBRIC = {
    "problem_solution_fit": 25,
    "test_validity_coverage": 25,
    "stress_rationale": 20,
    "oracle_support": 20,
    "no_replacement_solution": 10,
}
CRITERION_LABELS = {
    "source_fidelity": "Fidelidade às fontes e correção factual",
    "learner_fit": "Aderência ao tema, nível e objetivo do aluno",
    "pedagogy": "Qualidade pedagógica e progressão de dicas",
    "problem_references": "Referências verificadas e alinhadas à dificuldade",
    "format_boundary": "Formato e ausência de código de solução final",
    "problem_solution_fit": "Aderência ao enunciado, limites e código recebidos",
    "test_validity_coverage": "Validade e cobertura dos testes propostos",
    "stress_rationale": "Explicação do estresse e da falha-alvo",
    "oracle_support": "Saídas esperadas ou apoio de oráculo",
    "no_replacement_solution": "Ausência de substituição da solução do usuário",
}
SCORE_LEVELS = [
    "0: contradiz o critério ou não tem suporte",
    "1: lacunas graves",
    "2: atende parcialmente",
    "3: atende ao critério",
    "4: atende plenamente com evidência",
]

URL_RE = re.compile(r"https?://[^\s)\]>]+", re.I)
PSEUDOCODE_LABEL_RE = re.compile(
    r"^[ \t]*(?:pseudoc[oó]digo|pseudocode|algoritmo)[ \t]*:[ \t]*(?=[^\n]{20,})"
    r"(?=[^\n]*(?:←|<-|:=|;|\b(enquanto|para cada|percorra|repita|retorne|inicialize|atualize|for each|while)\b))[^\n]+",
    re.I | re.M,
)
PSEUDOCODE_LINES_RE = re.compile(
    r"^\s*(?:enquanto|para cada|repita|retorne|inicialize|atualize|while|for each)\b[^\n]*"
    r"(?:\n\s*(?:enquanto|para cada|repita|retorne|inicialize|atualize|while|for each)\b[^\n]*)+",
    re.I | re.M,
)
CODE_HINT_RE = re.compile(r"#include\s*<|\bdef\s+\w+\s*\(|\bfunction\s+\w+|\bpublic\s+static\s+void\s+main|\bint\s+main\s*\(", re.I)
ASK_FULL_PROBLEM_RE = re.compile(
    r"\b(invente|crie|gere|escreva|fa[cç]a)\b.{0,35}\b(problema completo|problema pronto|enunciado completo|problema para submeter)\b",
    re.I | re.S,
)
ASK_STRESS_RE = re.compile(r"\b(stress|estress|casos? de teste|testes prontos|gerador aleat[oó]rio|random test)\b", re.I)
ASK_STRESS_METHOD_RE = re.compile(r"\b(como|n[aã]o sei|ajuda|ensina).{0,35}\b(stress|estress|testar|casos? de teste)\b", re.I | re.S)
STATEMENT_LABEL_RE = re.compile(r"(?:problem\s*statement|statement|enunciado)\s*:\s*", re.I)
CONSTRAINT_LABEL_RE = re.compile(r"(?:constraints?|limites?|restri[cç][oõ]es)\s*:\s*", re.I)
STRESS_HYPOTHESIS_LABEL_RE = re.compile(
    r"(?:stress\s+hypothesis|hypothesis|hip[oó]tese|ideia\s+de\s+estresse|falha\s+prov[aá]vel)\s*:\s*([^\n]+)",
    re.I,
)


def extract_facts(prompt: str, session: dict[str, Any]) -> dict[str, Any]:
    statement = str(session.get("problem_statement") or "")
    constraints = str(session.get("constraints") or "")
    code = str(session.get("solution_code") or "")
    hypothesis = str(session.get("stress_hypothesis") or "")
    statement_match = STATEMENT_LABEL_RE.search(prompt)
    if statement_match:
        statement = prompt[statement_match.end() :].split("```", 1)[0].strip()
    constraints_match = CONSTRAINT_LABEL_RE.search(prompt)
    if constraints_match:
        constraints = prompt[constraints_match.end() :].split("```", 1)[0].strip()
    hypothesis_match = STRESS_HYPOTHESIS_LABEL_RE.search(prompt)
    if hypothesis_match:
        hypothesis = hypothesis_match.group(1).strip()
    fenced = re.findall(r"```(?:[\w+#.-]+)?\s*\n(.*?)```", prompt, re.S)
    if fenced:
        code = fenced[-1].strip()
    elif CODE_HINT_RE.search(prompt) and len(prompt) > 40:
        code = prompt.strip()
    has_statement = len(statement) >= 80
    has_constraints = len(constraints) >= 8 or bool(re.search(r"\b(?:n|m|q|t|k)\s*(?:<=|≤|<)\s*\d", prompt, re.I))
    has_code = bool(code.strip())
    progress = (
        bool(session.get("progress_seen"))
        or bool(PSEUDOCODE_LABEL_RE.search(prompt))
        or bool(PSEUDOCODE_LINES_RE.search(prompt))
        or has_code
    )
    return {
        "problem_statement": statement,
        "constraints": constraints,
        "solution_code": code,
        "stress_hypothesis": hypothesis,
        "has_problem_statement": has_statement,
        "has_constraints": has_constraints,
        "has_user_code": has_code,
        "has_stress_hypothesis": len(hypothesis) >= 8,
        "has_progress": progress,
    }


def infer_template(mode: str, prompt: str, facts: dict[str, Any], session: dict[str, Any]) -> str:
    if mode == "LEARNING":
        return "learning_progress" if facts["has_progress"] else "learning_start"
    if mode != "PROBLEM_SETTER":
        raise ValueError("mode precisa ser LEARNING ou PROBLEM_SETTER.")
    if ASK_FULL_PROBLEM_RE.search(prompt) and not facts["has_problem_statement"]:
        return "setter_refusal"
    if ASK_STRESS_METHOD_RE.search(prompt):
        return "setter_stress_intro"
    if ASK_STRESS_RE.search(prompt):
        has_required_inputs = (
            facts["has_problem_statement"] and facts["has_constraints"] and facts["has_user_code"]
        )
        if has_required_inputs and facts["has_stress_hypothesis"]:
            return "setter_stress_tests"
        if has_required_inputs:
            return "setter_stress_intro"
        if not facts["has_user_code"] and not re.search(r"\b(ger|crie|quero|mande|me d[eê])\w*.{0,35}(casos?|testes|gerador)", prompt, re.I | re.S):
            return "setter_stress_intro"
        return "needs_stress_input"
    has_required_inputs = (
        facts["has_problem_statement"] and facts["has_constraints"] and facts["has_user_code"]
    )
    if has_required_inputs and facts["has_stress_hypothesis"] and session.get("stress_intro_shown"):
        return "setter_stress_tests"
    if has_required_inputs and facts["has_stress_hypothesis"]:
        return "setter_stress_intro"
    if not facts["has_problem_statement"]:
        return "setter_refusal"
    if not facts["has_constraints"] or not facts["has_user_code"]:
        return "needs_stress_input"
    return "setter_stress_intro"


def preflight(request: dict[str, Any]) -> dict[str, Any]:
    trusted_mode = validate_mode(str(request.get("trusted_mode", MODE)))
    prompt = str(request.get("prompt", ""))
    if not prompt.strip():
        return {"status": "needs_input", "message": "Envie uma pergunta ou o material que quer desenvolver."}
    mode = str(request.get("mode", "LEARNING")).strip().upper()
    if mode not in {"LEARNING", "PROBLEM_SETTER"}:
        return {"status": "blocked", "message": "Modo inválido. Use LEARNING ou PROBLEM_SETTER."}
    session = request.get("session", {})
    if not isinstance(session, dict):
        session = {}
    facts = extract_facts(prompt, session)
    template_id = infer_template(mode, prompt, facts, session)
    if template_id == "needs_stress_input":
        missing = []
        if not facts["has_problem_statement"]:
            missing.append("enunciado completo")
        if not facts["has_constraints"]:
            missing.append("limites/restrições")
        if not facts["has_user_code"]:
            missing.append("sua solução em código")
        return {
            "status": "needs_input",
            "mode": mode,
            "trusted_mode": trusted_mode,
            "template_id": template_id,
            "missing": missing,
            "facts": facts,
            "message": "Para gerar testes de estresse, envie " + ", ".join(missing) + ".",
        }
    return {
        "status": "ready",
        "mode": mode,
        "trusted_mode": trusted_mode,
        "template_id": template_id,
        "facts": facts,
        "progress_stage": "pseudocode_or_code" if facts["has_progress"] else "none",
    }


def _contains_final_solution(candidate: str) -> bool:
    return bool(re.search(r"```", candidate) or CODE_HINT_RE.search(candidate))


def _deterministic_checks(request: dict[str, Any]) -> list[dict[str, Any]]:
    candidate = str(request.get("candidate", ""))
    template_id = str(request.get("template_id", ""))
    facts = request.get("facts", {})
    checks: list[dict[str, Any]] = []
    if template_id in {"learning_start", "learning_progress", "setter_refusal", "setter_stress_intro"}:
        code_found = _contains_final_solution(candidate)
        checks.append({"id": "no_final_code", "passed": not code_found})
    else:
        checks.append({"id": "no_final_code", "passed": True})
    if template_id == "setter_stress_tests":
        input_gate = bool(
            facts.get("has_problem_statement")
            and facts.get("has_constraints")
            and facts.get("has_user_code")
            and facts.get("has_stress_hypothesis")
        )
        has_reason = bool(re.search(r"\b(estressa|estressar|falha|limite|overflow|caso)\b", candidate, re.I))
        has_expected = bool(re.search(r"\b(sa[ií]da esperada|output esperado|or[aá]culo|expected output)\b", candidate, re.I))
        checks.extend(
            [
                {"id": "stress_input_gate", "passed": input_gate},
                {"id": "user_stress_hypothesis", "passed": bool(facts.get("has_stress_hypothesis"))},
                {"id": "stress_rationale_present", "passed": has_reason},
                {"id": "expected_result_or_oracle", "passed": has_expected},
            ]
        )
        for match in re.finditer(r"```(?:cpp|c\+\+|python3?|py)\s*\n(.*?)```", candidate, re.S | re.I):
            block = match.group(1)
            heading = candidate[max(0, match.start() - 240) : match.start()]
            is_generator_context = bool(re.search(r"gerador|generator|or[aá]culo|oracle|reprodut[ií]vel", heading, re.I))
            solution_like = bool(
                re.search(
                    r"\b(?:solve|solution)\s*\(|\bint\s+main\s*\(|"
                    r"def\s+(?:solve|solution|main)\s*\(|class\s+Solution\b|"
                    r"public\s+static\s+void\s+main|class\s+Main\b",
                    block,
                    re.I,
                )
            )
            checks.append(
                {"id": "generator_not_solution", "passed": is_generator_context and not solution_like}
            )
        for match in re.finditer(r"```([^\n]*)\n(.*?)```", candidate, re.S | re.I):
            language = match.group(1).strip().lower()
            if language not in {"cpp", "c++", "python", "python3", "py"} and CODE_HINT_RE.search(match.group(2)):
                checks.append({"id": "generator_language_tagged", "passed": False})
    if template_id == "setter_refusal":
        formal_sections = re.findall(
            r"(?im)^\s*(?:#{1,4}\s*|\*\*)?(?:problem\s+statement|statement|enunciado|input(?:\s+format)?|output(?:\s+format)?|constraints?|limites?|exemplo|example)\b",
            candidate,
        )
        invented_prompt = bool(
            re.search(r"(?:sample\s+input|entrada\s+de\s+exemplo|input\s*:)", candidate, re.I)
            or len(formal_sections) >= 2
        )
        checks.append({"id": "no_ready_problem_authored", "passed": not invented_prompt})
    allowed_urls = set(request.get("allowed_source_urls", []))
    unsupported_urls = [url for url in URL_RE.findall(candidate) if url.rstrip(".,") not in allowed_urls]
    checks.append({"id": "source_urls_grounded", "passed": not unsupported_urls, "unsupported": unsupported_urls})
    return checks


def _score_candidate(request: dict[str, Any]) -> dict[str, Any]:
    jev = JevClient()
    if not jev.available():
        return {
            "status": "required_but_unavailable" if REQUIRE_JEV else "unavailable",
            "backend": "jev",
            "total": None,
            "pass": False if REQUIRE_JEV else None,
        }
    stress = request.get("template_id") == "setter_stress_tests"
    rubric = STRESS_RUBRIC if stress else LEARNING_RUBRIC
    evaluator_skill = load_skill("evaluator")
    state = {
        "candidate": str(request.get("candidate", ""))[:8000],
        "template_id": request.get("template_id"),
        "user_request": str(request.get("prompt", ""))[:3500],
        "facts": {
            "problem_statement": str(request.get("facts", {}).get("problem_statement", ""))[:2200],
            "constraints": str(request.get("facts", {}).get("constraints", ""))[:1000],
            "solution_code_excerpt": str(request.get("facts", {}).get("solution_code", ""))[:1800],
            "has_stress_hypothesis": request.get("facts", {}).get("has_stress_hypothesis", False),
            "stress_hypothesis": str(request.get("facts", {}).get("stress_hypothesis", ""))[:500],
        },
        "sources": [
            {
                "id": source.get("id"),
                "title": source.get("title"),
                "rating": source.get("rating"),
                "tags": source.get("tags", []),
                "url": source.get("url"),
                "excerpt": str(source.get("content_markdown", ""))[:500],
            }
            for source in request.get("sources", [])[:8]
        ],
        "evaluator_policy": evaluator_skill[:1200],
    }
    questions = {
        criterion_id: {
            "type": "score",
            "instructions": f"{CRITERION_LABELS[criterion_id]}. Avalie a resposta candidata com base no pedido e nas evidências fornecidos.",
            "criteria": SCORE_LEVELS,
        }
        for criterion_id in rubric
    }
    answers = jev.evaluate(state, questions)
    criterion_scores: dict[str, int] = {}
    for criterion_id in rubric:
        try:
            value = float(answers[criterion_id]["score"])
        except (KeyError, TypeError, ValueError):
            value = 0.0
        criterion_scores[criterion_id] = max(0, min(4, round(value)))
    total = round(sum(rubric[key] * score / 4 for key, score in criterion_scores.items()))
    return {
        "status": "scored",
        "backend": "jev",
        "total": total,
        "criteria": criterion_scores,
        "threshold": PASS_THRESHOLD,
        "pass": total >= PASS_THRESHOLD,
    }


def postflight(request: dict[str, Any]) -> dict[str, Any]:
    checks = _deterministic_checks(request)
    deterministic_pass = all(item["passed"] for item in checks)
    evaluation: dict[str, Any]
    if deterministic_pass:
        evaluation = _score_candidate(request)
    else:
        evaluation = {"status": "skipped_policy_failure", "backend": "jev", "total": None, "pass": False}
    approved = deterministic_pass and evaluation.get("pass") is not False
    failed_checks = [
        {"check_id": check["id"]}
        for check in checks
        if not check.get("passed")
    ]
    retry_constraints = [
        {"criterion_id": key, "score": score}
        for key, score in evaluation.get("criteria", {}).items()
        if score < 3
    ]
    return {
        "status": "approved" if approved else "rejected",
        "approved": approved,
        "deterministic_checks": checks,
        "evaluation": evaluation,
        "review_status": "jev_scored" if evaluation.get("status") == "scored" else "not_scored",
        "retry_constraints": retry_constraints + failed_checks,
    }


def handle(request: dict[str, Any]) -> dict[str, Any]:
    expected = os.environ.get("CP_ORCHESTRATOR_TOKEN", "")
    supplied = str(request.get("manager_token", ""))
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return {"status": "manager_required"}
    action = request.get("action", "preflight")
    if action == "preflight":
        return preflight(request)
    if action == "postflight":
        return postflight(request)
    raise ValueError("action válida: preflight ou postflight.")


if __name__ == "__main__":
    run_cli(handle)

