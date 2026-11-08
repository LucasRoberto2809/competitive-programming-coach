"""Offline fixtures and an in-process session simulator for template use-case tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from cp_framework import app, config
from cp_framework.providers import ChatCompletionsClient
from cp_framework.services import guardrails, sources, templates

SERVICE_HANDLERS = {
    "guardrails": guardrails.handle,
    "templates": templates.handle,
}

# (rating, tags, count) groups; ids are generated deterministically.
PROBLEM_GROUPS: list[tuple[int, list[str], int]] = [
    (800, ["dp"], 3), (900, ["dp"], 2), (1000, ["dp"], 3), (1200, ["dp"], 3), (1400, ["dp"], 2),
    (1500, ["dp"], 2), (1800, ["dp"], 2), (2100, ["dp"], 1),
    (800, ["binary search"], 2), (1100, ["binary search"], 3), (1300, ["binary search"], 2),
    (1600, ["binary search"], 2),
    (1300, ["binary search", "dp"], 1), (1700, ["binary search", "dp"], 1),
    (800, ["graphs"], 6), (900, ["graphs", "dfs and similar"], 2), (1000, ["graphs"], 4),
    (1200, ["graphs", "shortest paths"], 2), (1600, ["graphs", "trees"], 2),
    (800, ["greedy", "math"], 4), (1100, ["greedy"], 3), (1900, ["greedy", "sortings"], 2),
    (1300, ["trees", "dfs and similar"], 2), (2000, ["trees", "dp"], 1),
    (1400, ["strings", "hashing"], 2), (900, ["strings"], 2),
    (1200, ["games"], 1), (2400, ["fft", "math"], 1),
]
NAMED_PROBLEMS = [
    {"contest_id": 492, "index": "B", "title": "Vanya and Lanterns", "rating": 1200,
     "tags": ["binary search", "implementation", "math", "sortings"], "solved_count": 95415},
    {"contest_id": 1950, "index": "D", "title": "Product of Binary Decimals", "rating": 1100,
     "tags": ["brute force", "dp", "implementation", "number theory"], "solved_count": 27021},
    {"contest_id": 4, "index": "A", "title": "Watermelon", "rating": 800,
     "tags": ["brute force", "math"], "solved_count": 400000},
]
UNINDEXABLE = [
    {"contest_id": 9001, "index": "A", "title": "No Tags Here", "rating": 1000, "tags": []},
    {"contest_id": 9001, "index": "B", "title": "April Fools Special", "rating": 1500, "tags": ["*special"]},
    {"contest_id": 9001, "index": "C", "title": "Unrated Dynamic", "rating": None, "tags": ["dp"]},
]
ARTICLE_PATHS = [
    "src/dynamic_programming/intro-to-dp.md",
    "src/dynamic_programming/knapsack.md",
    "src/num_methods/binary_search.md",
    "src/graph/breadth-first-search.md",
    "src/graph/depth-first-search.md",
    "src/graph/dijkstra.md",
    "src/graph/lca_binary_lifting.md",
    "src/string/prefix-function.md",
    "src/string/string-hashing.md",
    "src/game_theory/sprague-grundy-nim.md",
    "src/navigation.md",
    "src/tags.md",
]


def _record(contest_id: int, index: str, title: str, rating: Any, tags: list[str], solved: int = 0) -> dict[str, Any]:
    return {
        "id": f"{contest_id}{index}",
        "contest_id": contest_id,
        "index": index,
        "title": title,
        "rating": rating,
        "tags": tags,
        "solved_count": solved,
        "url": f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
    }


def problem_records() -> list[dict[str, Any]]:
    records = []
    contest = 3000
    for rating, tags, count in PROBLEM_GROUPS:
        for position in range(count):
            contest += 1
            slug = "-".join(tags).replace(" ", "_")
            records.append(_record(contest, "A", f"Fixture {slug} {rating} #{position}", rating, tags, solved=contest % 97))
    for item in NAMED_PROBLEMS + UNINDEXABLE:
        records.append(
            _record(item["contest_id"], item["index"], item["title"], item["rating"], item["tags"], item.get("solved_count", 0))
        )
    return records


def build_catalog() -> dict[str, Any]:
    return sources.build_codeforces_catalog({"source": "fixture", "problems": problem_records()})


def article_index() -> dict[str, Any]:
    return {
        "branch": "main",
        "articles": [
            {
                "id": path,
                "path": path,
                "title": Path(path).stem.replace("_", " ").replace("-", " "),
                "url": f"https://github.com/cp-algorithms/cp-algorithms/blob/main/{path}",
            }
            for path in ARTICLE_PATHS
        ],
    }


def article_snapshot() -> dict[str, Any]:
    index = article_index()
    return {
        "branch": "main",
        "articles": [
            {**article, "content_markdown": f"# {article['title']}\n\nConteúdo de teste para {article['title']}."}
            for article in index["articles"]
        ],
    }


def write_fixture_data(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "codeforces_catalog.json").write_text(json.dumps(build_catalog()), encoding="utf-8")
    (root / "cp_algorithms_index.json").write_text(json.dumps(article_index()), encoding="utf-8")
    (root / "cp_algorithms_articles.json").write_text(json.dumps(article_snapshot()), encoding="utf-8")


URL_RE = re.compile(r"https?://\S+")


def grounded_responder(context: dict[str, Any], system_prompt: str) -> str:
    """Default fake LLM: a short pedagogical answer citing only verified sources."""
    lines = ["Vamos por partes. Leia o material indicado e tente uma primeira observação."]
    for source in context.get("verified_sources", []):
        if source.get("url"):
            lines.append(f"- {source.get('title')}: {source['url']}")
    lines.append("Qual é a sua primeira observação sobre o problema?")
    return "\n".join(lines)


REFERENCE_CODE = (
    "#include <bits/stdc++.h>\n"
    "int main() {\n"
    "    long long best_value_so_far = 0;\n"
    "    for (int index = 1; index <= n; ++index) {\n"
    "        best_value_so_far = std::max(best_value_so_far, dp[index - 1] + values[index]);\n"
    "    }\n"
    "    std::cout << best_value_so_far << std::endl;\n"
    "}\n"
)


def solved_reference(task: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Default fake Solver output: a structured, solved reference."""
    value = {
        "status": "solved",
        "approach": "Programação dinâmica sobre prefixos.",
        "key_steps": ["Defina dp[i] como o melhor valor até i.", "Transição a partir de dp[i-1].", "Responda dp[n]."],
        "complexity": "O(n) tempo, O(n) memória",
        "language": "cpp",
        "solution_code": REFERENCE_CODE,
        "examples": [],
        "inconsistencies": [],
        "recognized_problems": [],
    }
    value.update(overrides)
    return value


class Simulator:
    """Runs app.process_turn with guardrails/templates in-process and a scripted LLM.

    `responder` answers template renders; `solver` answers internal Solver calls and may
    return a dict (serialized as JSON) or a raw string.
    """

    def __init__(
        self,
        responder: Callable[[dict[str, Any], str], str] | list[str] | None = None,
        with_data: bool = True,
        solver: Callable[[dict[str, Any]], Any] | None = None,
        context_budget: int | None = None,
    ) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self._tmp.name) / "sources"
        if with_data:
            write_fixture_data(self.data_root)
        else:
            self.data_root.mkdir(parents=True)
        self.responder = responder or grounded_responder
        self.solver = solver or solved_reference
        self.solver_calls: list[dict[str, Any]] = []
        self.command_output = ""
        self.renders: list[dict[str, Any]] = []
        self.service_calls: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
        self.answers: list[str] = []
        clean_env = {k: v for k, v in os.environ.items() if k not in {"TYPESAFE_API_KEY", "CP_ORCHESTRATOR_TOKEN"}}
        clean_env["CP_LLM_MODEL"] = "fake-model"
        self._patches = [
            mock.patch.dict(os.environ, clean_env, clear=True),
            mock.patch.object(app, "DATA_ROOT", self.data_root),
            mock.patch.object(config, "DATA_ROOT", self.data_root),
            mock.patch.object(sources, "DATA_ROOT", self.data_root),
            mock.patch.object(app, "MODE", "USER"),
            mock.patch.object(app, "MAX_REVISIONS", 2),
            mock.patch.object(app, "SESSIONS_ROOT", Path(self._tmp.name) / "sessions"),
            mock.patch.object(app, "CONTEXT_BUDGET_TOKENS", context_budget or 10**9),
            mock.patch.object(app, "run_service", self._run_service),
            mock.patch.object(ChatCompletionsClient, "complete", self._complete),
        ]
        for patch in self._patches:
            patch.start()
        self.session = app.new_session()

    def close(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        self._tmp.cleanup()

    def _run_service(self, name: str, payload: dict[str, Any], manager_token: str | None = None) -> dict[str, Any]:
        if name not in SERVICE_HANDLERS:
            raise AssertionError(f"serviço inesperado durante a simulação: {name} {payload}")
        request = json.loads(json.dumps(payload, ensure_ascii=False))
        if manager_token:
            request["manager_token"] = manager_token
        with mock.patch.dict(os.environ, {"CP_ORCHESTRATOR_TOKEN": manager_token or ""}):
            try:
                response = SERVICE_HANDLERS[name](request)
            except Exception as exc:
                self.service_calls.append((name, request, {"status": "error", "error": str(exc)}))
                raise RuntimeError(str(exc)) from exc
        response = json.loads(json.dumps(response, ensure_ascii=False))
        self.service_calls.append((name, request, response))
        if response.get("status") == "error":
            raise RuntimeError(response.get("error"))
        return response

    def _complete(self, system_prompt: str, user_prompt: str) -> str:
        context = json.loads(user_prompt.split("\n", 1)[1])
        if "## Contrato de saída" in system_prompt:
            self.solver_calls.append({"system": system_prompt, "task": context})
            result = self.solver(context)
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        self.renders.append({"system": system_prompt, "context": context})
        if isinstance(self.responder, list):
            index = min(len(self.renders) - 1, len(self.responder) - 1)
            return self.responder[index]
        return self.responder(context, system_prompt)

    def say(self, line: str) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            line, _ = app.apply_command(line, self.session)
        self.command_output = buffer.getvalue().strip()
        if not line.strip():
            return self.command_output
        answer = app.finish_turn(line, app.process_turn(line, self.session), self.session)
        self.answers.append(answer)
        return answer

    # Convenience accessors -------------------------------------------------
    def calls(self, name: str, action: str | None = None) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
        return [
            (request, response)
            for service, request, response in self.service_calls
            if service == name and (action is None or request.get("action") == action)
        ]

    @property
    def last_preflight(self) -> dict[str, Any]:
        return self.calls("guardrails", "preflight")[-1][1] or {}

    @property
    def last_postflight(self) -> dict[str, Any]:
        return self.calls("guardrails", "postflight")[-1][1] or {}

    @property
    def last_context(self) -> dict[str, Any]:
        return self.renders[-1]["context"]

    @property
    def last_system(self) -> str:
        return self.renders[-1]["system"]

    def last_problems(self) -> list[dict[str, Any]]:
        return [item for item in self.last_context["verified_sources"] if item.get("kind") == "problem"]
