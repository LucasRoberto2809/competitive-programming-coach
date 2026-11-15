"""Run scenarios against model profiles and prompt variants through the real app pipeline."""

from __future__ import annotations

import copy
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .. import app, transcript
from ..config import DATA_ROOT
from ..models import ModelProfile, ProfileError, load_profiles, resolve_profile
from .scenarios import Scenario, TurnResult, evaluate

BENCHMARKS_ROOT = DATA_ROOT.parent / "benchmarks"
VARIANTS = ("full", "compact")
# Token averages per call used before a run has its own data (measured on real runs).
DEFAULT_TOKENS = {
    ("full", "template"): (12000, 2500),
    ("compact", "template"): (3500, 1500),
    ("full", "solver"): (3000, 6000),
    ("compact", "solver"): (1500, 6000),
}
SOLVER_MARKERS = ("1950D", "Enunciado:")


def run_dir(run_id: str) -> Path:
    return BENCHMARKS_ROOT / run_id


def new_run_id() -> str:
    return datetime.now().strftime("run-%Y%m%d-%H%M%S")


def combo_key(profile: str, variant: str) -> str:
    return f"{profile} · {variant}"


@contextmanager
def scoped_env(values: dict[str, str | None]) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_results(directory: Path) -> list[dict[str, Any]]:
    return transcript.load_jsonl(directory / "results.jsonl")


def usage_for(directory: Path, session_id: str) -> list[dict[str, Any]]:
    return [row for row in transcript.load_jsonl(directory / "usage.jsonl") if row.get("session_id") == session_id]


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), (int, float))]
    return sum(values) if values else None


def token_profile(variant: str) -> dict[str, tuple[float, float]]:
    """Average (input, output) tokens per call by purpose kind, from earlier benchmark runs if any."""
    stats: dict[str, list[tuple[int, int]]] = {"template": [], "solver": []}
    if BENCHMARKS_ROOT.is_dir():
        for usage_file in BENCHMARKS_ROOT.glob("*/usage.jsonl"):
            for row in transcript.load_jsonl(usage_file):
                if row.get("status") != "ok" or row.get("prompt_variant", "full") != variant:
                    continue
                kind = "solver" if row.get("purpose") == "solver" else "template" if str(row.get("purpose", "")).startswith("template") else None
                if kind and isinstance(row.get("prompt_tokens"), int) and isinstance(row.get("completion_tokens"), int):
                    stats[kind].append((row["prompt_tokens"], row["completion_tokens"]))
    result = {}
    for kind, rows in stats.items():
        if len(rows) >= 3:
            result[kind] = (sum(r[0] for r in rows) / len(rows), sum(r[1] for r in rows) / len(rows))
        else:
            result[kind] = DEFAULT_TOKENS[(variant, kind)]
    return result


def estimate_scenario(profile: ModelProfile, variant: str, scenario: Scenario, tokens: dict[str, tuple[float, float]]) -> float | None:
    """List-price estimate: one template call per model turn (x1.3 for retries) plus one Solver call if needed."""
    model_turns = [line for line in scenario.turns if not line.startswith("/")]
    template_in, template_out = tokens["template"]
    calls = [(template_in * 1.3, template_out * 1.3)] * len(model_turns)
    if any(marker in line for line in scenario.turns for marker in SOLVER_MARKERS):
        calls.append(tokens["solver"])
    costs = [profile.list_cost_usd(int(i), int(o)) for i, o in calls]
    return None if any(c is None for c in costs) else sum(costs)  # type: ignore[arg-type]


def estimate(profile_names: list[str], variants: list[str], scenarios: list[Scenario]) -> list[dict[str, Any]]:
    profiles = load_profiles()
    rows = []
    for name in profile_names:
        profile = profiles.get(name)
        if profile is None:
            raise ProfileError(f"Perfil '{name}' não existe.")
        for variant in variants:
            tokens = token_profile(variant)
            per = [estimate_scenario(profile, variant, s, tokens) for s in scenarios]
            known = [p for p in per if p is not None]
            rows.append({
                "profile": name, "model": profile.model, "variant": variant, "scenarios": len(scenarios),
                "list_cost_usd": sum(known) if len(known) == len(per) else None,
                "billed_usd": 0.0 if profile.is_free() else (sum(known) if len(known) == len(per) else None),
            })
    return rows


def run_scenario(profile: ModelProfile, variant: str, scenario: Scenario, run_id: str, directory: Path, judge: str | None) -> dict[str, Any]:
    session_id = f"{run_id}__{profile.name}__{variant}__{scenario.id}"
    env = {
        "CP_LLM_PROFILE": profile.name,
        "CP_PROMPT_VARIANT": variant,
        "CP_SESSION_ID": session_id,
        "CP_USAGE_LOG": str(directory / "usage.jsonl"),
        "CP_TRANSCRIPT_DIR": str(directory / "sessions"),
        "CP_TRANSCRIPTS": "1",
        "CP_EVALUATOR_PROFILE": judge,
        "CP_EVALUATOR_BACKEND": "llm" if judge else "none",
    }
    started = time.perf_counter()
    turns: list[TurnResult] = []
    with scoped_env(env):
        transcript.write_meta({
            "kind": "benchmark", "run_id": run_id, "session_id": session_id, "scenario": scenario.id,
            "scenario_title": scenario.title, "profile": profile.name, "model": profile.model,
            "provider": profile.provider, "prompt_variant": variant, "judge": judge, "turns": scenario.turns,
        })
        session = app.new_session()
        session["context_warned"] = True
        for line in scenario.turns:
            remaining, _, _ = app.run_command(line, session)
            if not remaining.strip():
                continue
            try:
                answer = app.process_turn(remaining, session)
            except Exception as exc:
                answer = f"Falha interna do manager: {exc}"
                session.setdefault("_turn", {}).update(outcome="internal_error", error=str(exc)[:500])
            pipeline = copy.deepcopy(session.get("_turn"))
            answer = app.finish_turn(remaining, answer, session)
            turns.append(TurnResult(remaining, answer, pipeline))
    wall_ms = round((time.perf_counter() - started) * 1000)
    final = turns[-1] if turns else TurnResult("", "", None)
    checks = evaluate(scenario, final)
    usage = usage_for(directory, session_id)
    errors = [t.pipeline.get("error") for t in turns if t.pipeline and t.pipeline.get("outcome", "").endswith("_error")]
    passed = sum(c["passed"] for c in checks)
    attempts = sum(len((t.pipeline or {}).get("attempts", [])) for t in turns)
    judge_scores = [
        a["evaluation"]["total"] for t in turns for a in (t.pipeline or {}).get("attempts", [])
        if isinstance(a.get("evaluation"), dict) and a["evaluation"].get("status") == "scored"
    ]
    return {
        "run_id": run_id,
        "session_id": session_id,
        "profile": profile.name,
        "model": profile.model,
        "provider": profile.provider,
        "variant": variant,
        "scenario": scenario.id,
        "scenario_title": scenario.title,
        "category": scenario.category,
        "status": "provider_error" if errors else "ok",
        "errors": errors,
        "checks": checks,
        "score": passed / len(checks) if checks else None,
        "success": bool(checks) and passed == len(checks) and not errors,
        "final_outcome": (final.pipeline or {}).get("outcome"),
        "attempts": attempts,
        "fallbacks": sum(1 for t in turns if (t.pipeline or {}).get("outcome") == "guardrail_fallback"),
        "judge_score": sum(judge_scores) / len(judge_scores) if judge_scores else None,
        "llm_calls": len([u for u in usage if u.get("status") == "ok"]),
        "failed_calls": len([u for u in usage if u.get("status") == "error"]),
        "prompt_tokens": _sum(usage, "prompt_tokens"),
        "completion_tokens": _sum(usage, "completion_tokens"),
        "reasoning_tokens": _sum(usage, "reasoning_tokens"),
        "cost_usd": _sum(usage, "cost_usd") or 0.0,
        "list_cost_usd": _sum(usage, "list_cost_usd"),
        "latency_ms": _sum(usage, "latency_ms"),
        "model_ms": sum((u.get("model_ms") if isinstance(u.get("model_ms"), (int, float)) else u.get("latency_ms") or 0) for u in usage if u.get("status") == "ok"),
        "wall_ms": wall_ms,
        "answer_chars": len(final.answer),
        "final_answer": final.answer,
    }


def run(
    profile_names: list[str],
    variants: list[str],
    scenarios: list[Scenario],
    run_id: str | None = None,
    budget_usd: float = 1.0,
    judge: str | None = None,
    allow_paid: bool = False,
    pause_seconds: float = 0.0,
    progress: Callable[[str], None] = print,
) -> Path:
    run_id = run_id or new_run_id()
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    env = {"CP_ALLOW_PAID": "1" if allow_paid else os.environ.get("CP_ALLOW_PAID")}
    with scoped_env(env):
        profiles = [resolve_profile(name) for name in profile_names]
        if judge:
            resolve_profile(judge)
    config_path = directory / "config.json"
    config = {
        "run_id": run_id, "profiles": profile_names, "variants": variants, "scenarios": [s.id for s in scenarios],
        "budget_usd": budget_usd, "judge": judge, "started_at": datetime.now().isoformat(),
    }
    if not config_path.exists():
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    # Provider errors and budget skips are retried when a run is resumed; the latest row wins in reports.
    done = {(r["profile"], r["variant"], r["scenario"]) for r in load_results(directory) if r.get("status") == "ok"}
    spent = sum(r.get("cost_usd") or 0.0 for r in load_results(directory))
    for profile in profiles:
        for variant in variants:
            tokens = token_profile(variant)
            costs_so_far: list[float] = []
            for scenario in scenarios:
                key = (profile.name, variant, scenario.id)
                if key in done:
                    continue
                expected = (sum(costs_so_far) / len(costs_so_far)) if costs_so_far else estimate_scenario(profile, variant, scenario, tokens)
                if not profile.is_free() and expected is not None and spent + expected > budget_usd:
                    progress(f"[orçamento] {combo_key(profile.name, variant)} {scenario.id}: pulado (gasto ${spent:.4f} + previsto ${expected:.4f} > ${budget_usd:.2f})")
                    _append(directory / "results.jsonl", {
                        "run_id": run_id, "profile": profile.name, "model": profile.model, "provider": profile.provider,
                        "variant": variant, "scenario": scenario.id, "scenario_title": scenario.title,
                        "category": scenario.category, "status": "budget_skipped",
                    })
                    continue
                progress(f"[{combo_key(profile.name, variant)}] {scenario.id} ...")
                with scoped_env(env):
                    result = run_scenario(profile, variant, scenario, run_id, directory, judge)
                spent += result["cost_usd"]
                costs_so_far.append(result["cost_usd"])
                _append(directory / "results.jsonl", result)
                score = f"{result['score']:.0%}" if result["score"] is not None else "-"
                progress(f"    {result['status']} | nota {score} | ${result['cost_usd']:.4f} | {result['llm_calls']} chamadas | {result['wall_ms'] / 1000:.1f}s")
                if pause_seconds:
                    time.sleep(pause_seconds)
    return directory


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def rescore(directory: Path) -> tuple[int, int]:
    """Re-evaluate checks from the saved transcripts (no model calls); returns (rescored, changed)."""
    from .scenarios import SCENARIOS_BY_ID

    rows = load_results(directory)
    changed = 0
    for row in rows:
        scenario = SCENARIOS_BY_ID.get(row.get("scenario"))
        if scenario is None or row.get("status") not in {"ok", "provider_error"} or not row.get("session_id"):
            continue
        turns = [t for t in transcript.load_jsonl(directory / "sessions" / row["session_id"] / "turns.jsonl") if t.get("kind") == "turn"]
        if not turns:
            continue
        last = turns[-1]
        checks = evaluate(scenario, TurnResult(last.get("user", ""), last.get("answer", ""), last.get("pipeline")))
        passed = sum(c["passed"] for c in checks)
        score = passed / len(checks) if checks else None
        if checks != row.get("checks"):
            changed += 1
        row.update(checks=checks, score=score, success=bool(checks) and passed == len(checks) and not row.get("errors"))
    with (directory / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return len(rows), changed
