"""Benchmark runner/report, prompt variants, transcripts, and the Copilot SDK backend (with a fake SDK)."""

from __future__ import annotations

import json
import os
import sys
import types
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from cp_framework import app, config, transcript
from cp_framework.benchmark import report, runner, scenarios
from cp_framework.models import load_profiles
from cp_framework.providers import ChatCompletionsClient, ProviderError
from cp_framework.services import templates
from tests.fixtures import solved_reference, write_fixture_data
from tests.test_models_and_app import FakeProvider, ProviderCase


def citing_reply(body: dict[str, Any]) -> str:
    """Fake model that follows the templates well enough to pass the objective checks."""
    system = body["messages"][0]["content"]
    if "## Contrato de saída" in system:
        return json.dumps(solved_reference({}))
    context = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
    urls = [s["url"] for s in context.get("verified_sources", []) if s.get("url")]
    lines = ["Leia o material e tente uma primeira observação ou pseudocódigo."] + [f"- {u}" for u in urls]
    if context.get("template_id") == "setter_statement_review":
        lines.append("Revisei o exemplo de entrada e saída.")
    return "\n".join(lines)


class BenchmarkRunTest(ProviderCase):
    def setUp(self) -> None:
        super().setUp()
        data_root = self.root / "data" / "sources"
        write_fixture_data(data_root)
        self.bench_root = self.root / "data" / "benchmarks"
        for patcher in (
            mock.patch.object(runner, "BENCHMARKS_ROOT", self.bench_root),
            mock.patch.object(app, "DATA_ROOT", data_root),
            mock.patch.object(config, "DATA_ROOT", data_root),
            mock.patch.object(FakeProvider, "reply", staticmethod(citing_reply)),
            mock.patch.dict(os.environ, {"CP_DATA_DIR": str(data_root)}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("CP_SESSION_ID", None)

    def test_run_writes_results_transcripts_and_report(self) -> None:
        chosen = scenarios.select("learn_start,setter_review")
        directory = runner.run(["fake"], ["full", "compact"], chosen, run_id="t1", budget_usd=0, progress=lambda _m: None)
        rows = runner.load_results(directory)
        self.assertEqual(len(rows), 4)
        by_key = {(r["variant"], r["scenario"]): r for r in rows}
        start = by_key[("full", "learn_start")]
        self.assertEqual(start["status"], "ok")
        self.assertEqual(start["final_outcome"], "approved")
        failed = [c["name"] for c in start["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        self.assertTrue(start["success"])
        self.assertEqual(start["llm_calls"], 1)
        self.assertEqual(start["prompt_tokens"], 100)
        self.assertEqual(start["cost_usd"], 0.0)
        self.assertEqual(by_key[("full", "setter_review")]["llm_calls"], 2)

        session = directory / "sessions" / start["session_id"]
        meta = json.loads((session / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual((meta["kind"], meta["scenario"], meta["prompt_variant"]), ("benchmark", "learn_start", "full"))
        turns = transcript.load_jsonl(session / "turns.jsonl")
        self.assertEqual([t["kind"] for t in turns], ["command", "turn"])
        self.assertEqual(turns[1]["pipeline"]["template_id"], "learning_start")
        self.assertEqual(turns[1]["pipeline"]["attempts"][0]["candidate"], start["final_answer"])
        calls = transcript.load_jsonl(session / "calls.jsonl")
        self.assertEqual([c["purpose"] for c in calls], ["template:learning_start"])
        prompt = (session / "prompts" / f"{calls[0]['system_prompt_sha']}.md").read_text(encoding="utf-8")
        self.assertIn("## Skill Coach", prompt)

        compact_session = directory / "sessions" / by_key[("compact", "learn_start")]["session_id"]
        compact_call = transcript.load_jsonl(compact_session / "calls.jsonl")[0]
        compact_prompt = (compact_session / "prompts" / f"{compact_call['system_prompt_sha']}.md").read_text(encoding="utf-8")
        self.assertNotIn("## Skill Coach", compact_prompt)
        self.assertLess(len(compact_prompt), len(prompt) / 4)
        self.assertEqual(compact_call["prompt_variant"], "compact")

        html_path, md_path = report.build_report(directory)
        page = html_path.read_text(encoding="utf-8")
        for expected in ("Custo × qualidade", "Nota por caso de uso", "fake · full", "fake · compact", "sessions/"):
            self.assertIn(expected, page)
        self.assertTrue((directory / "charts" / "cenario_learn_start.svg").is_file())
        self.assertIn("| fake · full |", md_path.read_text(encoding="utf-8"))

    def test_rescore_recomputes_checks_from_transcripts(self) -> None:
        directory = runner.run(["fake"], ["compact"], scenarios.select("learn_start"), run_id="t4", budget_usd=0, progress=lambda _m: None)
        results_file = directory / "results.jsonl"
        row = runner.load_results(directory)[0]
        row.update(checks=[{"name": "antiga", "passed": False}], score=0.0, success=False)
        results_file.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertEqual(runner.rescore(directory), (1, 1))
        rescored = runner.load_results(directory)[0]
        self.assertEqual((rescored["score"], rescored["success"]), (1.0, True))
        self.assertEqual(len(self.provider.requests), 1)

    def test_resume_skips_done_and_budget_blocks_paid(self) -> None:
        chosen = scenarios.select("learn_start")
        runner.run(["fake"], ["compact"], chosen, run_id="t2", budget_usd=0, progress=lambda _m: None)
        calls_before = len(self.provider.requests)
        messages: list[str] = []
        directory = runner.run(["fake", "paid"], ["compact"], chosen, run_id="t2", budget_usd=0.0001,
                               allow_paid=True, progress=messages.append)
        self.assertEqual(len(self.provider.requests), calls_before)
        rows = runner.load_results(directory)
        self.assertEqual([(r["profile"], r["status"]) for r in rows], [("fake", "ok"), ("paid", "budget_skipped")])
        self.assertTrue(any("orçamento" in m for m in messages))
        summary = {s["profile"]: s for s in report.summarize(report.latest_rows(rows))}
        self.assertEqual((summary["paid"]["ran"], summary["paid"]["skipped"]), (0, 1))

    def test_paid_profiles_need_allow_paid(self) -> None:
        with self.assertRaisesRegex(Exception, "CP_ALLOW_PAID"):
            runner.run(["paid"], ["full"], scenarios.select("learn_start"), run_id="t3", progress=lambda _m: None)

    def test_estimate_uses_list_prices(self) -> None:
        rows = {r["profile"]: r for r in runner.estimate(["fake", "paid"], ["full", "compact"], scenarios.select("learn_start"))}
        self.assertEqual(rows["fake"]["billed_usd"], 0.0)
        estimates = runner.estimate(["paid"], ["full", "compact"], scenarios.select("learn_start"))
        full, compact = (r["list_cost_usd"] for r in estimates)
        self.assertGreater(full, compact)
        self.assertGreater(compact, 0)


class ReportUnitTest(ProviderCase):
    def test_pareto_and_latest_rows(self) -> None:
        points = [("a", 1.0, 0.9), ("b", 0.1, 0.7), ("c", 2.0, 0.8), ("d", 0.1, 0.5)]
        self.assertEqual(report.pareto(points), {"a", "b"})
        rows = [
            {"profile": "p", "variant": "full", "scenario": "s", "status": "budget_skipped"},
            {"profile": "p", "variant": "full", "scenario": "s", "status": "ok", "score": 1.0},
        ]
        self.assertEqual(report.latest_rows(rows)[0]["status"], "ok")

    def test_scenarios_are_well_formed(self) -> None:
        check = scenarios.ends_with_next_step()
        for answer, expected in [
            ("Texto.\n\nQual informação você guardaria em cada estado?", True),
            ("Dica.\n\nConfira esse detalhe com n = 10.", True),
            ("Dica.\n\nMe envie seu pseudocódigo.", True),
            ("Aqui está tudo explicado.\n\nFim.", False),
        ]:
            with self.subTest(answer=answer):
                self.assertEqual(check.fn(scenarios.TurnResult("u", answer, {})), expected)
        self.assertEqual(len({s.id for s in scenarios.SCENARIOS}), len(scenarios.SCENARIOS))
        for scenario in scenarios.SCENARIOS:
            with self.subTest(scenario=scenario.id):
                self.assertTrue(any(not t.startswith("/") for t in scenario.turns))
                self.assertGreaterEqual(len(scenario.checks), 2)
        with self.assertRaisesRegex(ValueError, "desconhecido"):
            scenarios.select("nope")


class PromptVariantTest(ProviderCase):
    def test_compact_drops_skills_and_shortens_sources(self) -> None:
        full = templates.make_system_prompt("learning_start", ["solution_request"], variant="full")
        compact = templates.make_system_prompt("learning_start", ["solution_request"], variant="compact")
        self.assertIn("## Skill Manager", full)
        self.assertNotIn("## Skill", compact)
        self.assertIn(templates.COMPACT_COACH_RULES, compact)
        self.assertIn(templates.SITUATION_GUIDES["solution_request"].strip(), compact)
        self.assertTrue(compact.rstrip().endswith(templates.TEMPLATE_GUIDES["learning_start"].strip()))
        source = {"content_markdown": "x" * 5000}
        with mock.patch.dict(os.environ, {"CP_PROMPT_VARIANT": "compact"}):
            self.assertLess(len(templates._compact_source(source)["content_markdown"]), 1300)
            self.assertEqual(templates.prompt_variant(), "compact")
        with mock.patch.dict(os.environ, {"CP_PROMPT_VARIANT": "weird"}):
            self.assertEqual(templates.prompt_variant(), "full")


class TranscriptTest(ProviderCase):
    def test_calls_are_written_per_session_with_deduplicated_prompts(self) -> None:
        with mock.patch.dict(os.environ, {"CP_SESSION_ID": "s/1", "CP_TRANSCRIPT_DIR": str(self.root / "tx")}):
            ChatCompletionsClient("fake").complete("sistema longo", "u1", purpose="template:x")
            ChatCompletionsClient("fake").complete("sistema longo", "u2", purpose="solver")
            self.provider.fail_with = 401
            with self.assertRaises(ProviderError):
                ChatCompletionsClient("fake").complete("sistema longo", "u3")
        session = self.root / "tx" / "s_1"
        calls = transcript.load_jsonl(session / "calls.jsonl")
        self.assertEqual([c["user_prompt"] for c in calls], ["u1", "u2", "u3"])
        self.assertEqual(calls[2]["error"][:8], "HTTP 401")
        self.assertEqual(len(list((session / "prompts").iterdir())), 1)
        self.assertNotIn("test-key", (session / "calls.jsonl").read_text(encoding="utf-8"))

    def test_disabled_or_without_session(self) -> None:
        with mock.patch.dict(os.environ, {"CP_TRANSCRIPTS": "0", "CP_SESSION_ID": "x"}):
            self.assertIsNone(transcript.session_dir())
        os.environ.pop("CP_SESSION_ID", None)
        self.assertIsNone(transcript.session_dir())


# --- Copilot backend with a fake `copilot` package --------------------------------------------


@dataclass
class _Usage:
    model: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost: float
    duration: timedelta
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class _Checkpoint:
    total_nano_aiu: int


@dataclass
class _Message:
    content: str


class _Event:
    def __init__(self, data: Any, agent_id: str | None = None) -> None:
        self.data, self.agent_id = data, agent_id


def fake_copilot_module(record: dict[str, Any], reply: str | Exception = "Resposta do Copilot") -> dict[str, types.ModuleType]:
    class Session:
        def __init__(self) -> None:
            self.handler = None

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            record["session_closed"] = True

        def on(self, handler: Any) -> None:
            self.handler = handler

        async def send_and_wait(self, prompt: str, timeout: float = 60.0) -> Any:
            record["prompt"], record["timeout"] = prompt, timeout
            if isinstance(reply, Exception):
                raise reply
            self.handler(_Event(_Usage("gpt-x", 1000, 200, 50, 0.5, timedelta(milliseconds=800))))
            self.handler(_Event(_Usage("sub", 999, 999, 0, 9, timedelta(seconds=9)), agent_id="sub-agent"))
            self.handler(_Event(_Usage("gpt-x", 500, 100, 0, 0.25, timedelta(milliseconds=400))))
            self.handler(_Event(_Checkpoint(total_nano_aiu=123456)))
            return _Event(_Message(reply))

    class CopilotClient:
        def __init__(self, **options: Any) -> None:
            record["client_options"] = options

        async def __aenter__(self) -> "CopilotClient":
            return self

        async def __aexit__(self, *exc: Any) -> None:
            record["client_closed"] = True

        async def create_session(self, **options: Any) -> Session:
            record["session_options"] = options
            return Session()

        async def list_models(self) -> list[Any]:
            return [_Message("m")]

    package = types.ModuleType("copilot")
    package.CopilotClient = CopilotClient  # type: ignore[attr-defined]
    events = types.ModuleType("copilot.session_events")
    events.AssistantMessageData = _Message  # type: ignore[attr-defined]
    events.AssistantUsageData = _Usage  # type: ignore[attr-defined]
    events.SessionUsageCheckpointData = _Checkpoint  # type: ignore[attr-defined]
    return {"copilot": package, "copilot.session_events": events}


class CopilotBackendTest(ProviderCase):
    def setUp(self) -> None:
        super().setUp()
        models = json.loads(self.models_file.read_text(encoding="utf-8"))
        models["profiles"]["cop"] = {"provider": "copilot", "model": "gpt-x", "price_input_per_mtok": 0.1, "price_output_per_mtok": 0.5,
                                     "reasoning_effort": "low"}
        self.models_file.write_text(json.dumps(models), encoding="utf-8")
        os.environ.update({"COPILOT_GITHUB_TOKEN": "github_pat_fake", "CP_ALLOW_PAID": "1",
                           "CP_COPILOT_HOME": str(self.root / "copilot-home"), "CP_SESSION_ID": "cop-session",
                           "CP_TRANSCRIPT_DIR": str(self.root / "tx")})
        from cp_framework import copilot_backend

        patcher = mock.patch.object(copilot_backend, "gh_cli_token", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_isolated_session_and_usage(self) -> None:
        record: dict[str, Any] = {}
        with mock.patch.dict(sys.modules, fake_copilot_module(record)):
            reply = ChatCompletionsClient("cop").complete("SISTEMA", "pergunta", json_output=True, purpose="solver")
        self.assertEqual(reply, "Resposta do Copilot")
        self.assertEqual(record["client_options"], {"mode": "empty", "base_directory": str(self.root / "copilot-home"), "github_token": "github_pat_fake"})
        self.assertEqual(record["session_options"], {
            "model": "gpt-x", "system_message": {"mode": "replace", "content": "SISTEMA"}, "available_tools": [], "reasoning_effort": "low",
        })
        self.assertEqual(record["prompt"], "pergunta")
        self.assertTrue(record["session_closed"] and record["client_closed"])
        usage = self.usage()[-1]
        self.assertEqual((usage["prompt_tokens"], usage["completion_tokens"], usage["reasoning_tokens"]), (1500, 300, 50))
        self.assertEqual((usage["api_calls"], usage["copilot_cost"], usage["nano_aiu"], usage["model_ms"]), (2, 0.75, 123456, 1200))
        self.assertAlmostEqual(usage["cost_usd"], 123456e-11)
        self.assertEqual(usage["cost_source"], "copilot_billed")
        self.assertAlmostEqual(usage["list_cost_usd"], (1500 * 0.1 + 300 * 0.5) / 1e6)
        self.assertEqual(usage["provider"], "copilot")
        calls = transcript.load_jsonl(self.root / "tx" / "cop-session" / "calls.jsonl")
        self.assertEqual(calls[-1]["usage"]["served_models"], ["gpt-x"])

    def test_errors_map_to_provider_errors(self) -> None:
        with mock.patch.dict(sys.modules, fake_copilot_module({}, RuntimeError("rate limit exceeded"))), \
                mock.patch.dict(os.environ, {"CP_LLM_RETRIES": "1"}):
            with self.assertRaisesRegex(ProviderError, "limite de uso"):
                ChatCompletionsClient("cop").complete("s", "u")
        self.assertEqual([u["status"] for u in self.usage()], ["error", "error"])
        with mock.patch.dict(sys.modules, fake_copilot_module({}, "   ")):
            with self.assertRaisesRegex(ProviderError, "vazia"):
                ChatCompletionsClient("cop").complete("s", "u")
        os.environ.pop("COPILOT_GITHUB_TOKEN")
        with mock.patch.dict(sys.modules, fake_copilot_module({})):
            with self.assertRaisesRegex(ProviderError, "gh auth login"):
                ChatCompletionsClient("cop").complete("s", "u")
        from cp_framework import copilot_backend

        record: dict[str, Any] = {}
        with mock.patch.object(copilot_backend, "gh_cli_token", return_value="gho_from_cli"), \
                mock.patch.dict(sys.modules, fake_copilot_module(record)):
            ChatCompletionsClient("cop").complete("s", "u")
        self.assertEqual(record["client_options"]["github_token"], "gho_from_cli")
        with mock.patch.dict(os.environ, {"GH_TOKEN": "ghp_classic"}), mock.patch.dict(sys.modules, fake_copilot_module({})):
            with self.assertRaisesRegex(ProviderError, "clássico"):
                ChatCompletionsClient("cop").complete("s", "u")

    def test_paid_guard_and_sdk_missing(self) -> None:
        os.environ.pop("CP_ALLOW_PAID")
        with self.assertRaisesRegex(ProviderError, "CP_ALLOW_PAID"):
            ChatCompletionsClient("cop").complete("s", "u")
        os.environ["CP_ALLOW_PAID"] = "1"
        with mock.patch.dict(sys.modules, {"copilot": None}):
            with self.assertRaisesRegex(ProviderError, "github-copilot-sdk"):
                ChatCompletionsClient("cop").complete("s", "u")

    def test_profile_and_env_forwarding(self) -> None:
        from cp_framework import models

        profile = load_profiles()["cop"]
        self.assertEqual((profile.endpoint, profile.api_key_env, profile.is_free()), ("copilot-sdk://gpt-x", "COPILOT_GITHUB_TOKEN", False))
        self.assertTrue(profile.is_ready())
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "C:/x", "OTHER_SECRET": "s"}):
            env = models.forwarded_env("cop")
        self.assertEqual((env["COPILOT_GITHUB_TOKEN"], env["LOCALAPPDATA"]), ("github_pat_fake", "C:/x"))
        with mock.patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "AMD64"}):
            self.assertEqual(models.forwarded_env("cop")["PROCESSOR_ARCHITECTURE"], "AMD64")
        self.assertNotIn("OTHER_SECRET", env)
        self.assertNotIn("LOCALAPPDATA", models.forwarded_env("fake"))
