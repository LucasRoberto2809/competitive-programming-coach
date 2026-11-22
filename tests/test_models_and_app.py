"""Model profiles, .env loading, the HTTP client, the LLM evaluator, --check, and an end-to-end chat.

A local fake OpenAI-compatible server stands in for the provider, so these tests are offline
but exercise the real HTTP path and the real multi-process application.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

from cp_framework import app, check, envfile, local_file_tools, models
from cp_framework.providers import ChatCompletionsClient, ProviderError
from cp_framework.services import guardrails
from tests.fixtures import solved_reference, write_fixture_data

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "test-key-123"
MODEL_REPLY = "Resposta do modelo falso: qual é a sua primeira observação?"


class FakeProvider:
    """Minimal OpenAI-compatible /chat/completions server on 127.0.0.1."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.fail_with: int | None = None
        self.fail_times: int | None = None
        self.tool_calls: list[dict[str, Any]] | None = None
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                if provider.fail_with and (provider.fail_times is None or provider.fail_times > 0):
                    if provider.fail_times is not None:
                        provider.fail_times -= 1
                    self._send(provider.fail_with, {"error": {"message": "falha simulada"}})
                    return
                if self.headers.get("Authorization") != f"Bearer {FAKE_KEY}":
                    self._send(401, {"error": {"message": "chave inválida"}})
                    return
                calls = provider.tool_calls
                provider.tool_calls = None
                message = (
                    {"role": "assistant", "content": None, "tool_calls": calls}
                    if calls is not None
                    else {"role": "assistant", "content": provider.reply(body)}
                )
                self._send(200, {
                    "choices": [{"message": message}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                })

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    @staticmethod
    def reply(body: dict[str, Any]) -> str:
        system = body["messages"][0]["content"]
        if "## Contrato de saída" in system:
            return json.dumps(solved_reference({}))
        if "## Contrato do avaliador" in system:
            return json.dumps({"criteria": {key: 4 for key in guardrails.LEARNING_RUBRIC}, "total": 0})
        if "teste de conexão" in system:
            return "OK"
        if "objeto JSON" in system:
            return '{"status": "solved", "language": "cpp", "steps": ["a", "b"]}'
        return MODEL_REPLY

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def write_models(path: Path, base_url: str) -> None:
    path.write_text(json.dumps({
        "default": "fake",
        "profiles": {
            "fake": {"provider": "custom", "base_url": base_url, "model": "fake/model:free", "api_key_env": "FAKE_API_KEY",
                     "price_input_per_mtok": 0, "price_output_per_mtok": 0, "json_mode": True},
            "fake-plain": {"provider": "custom", "base_url": base_url, "model": "fake/plain:free", "api_key_env": "FAKE_API_KEY",
                           "price_input_per_mtok": 0, "price_output_per_mtok": 0},
            "paid": {"provider": "custom", "base_url": base_url, "model": "fake/paid", "api_key_env": "FAKE_API_KEY",
                     "price_input_per_mtok": 3, "price_output_per_mtok": 15},
            "unpriced": {"provider": "custom", "base_url": base_url, "model": "fake/unknown", "api_key_env": "FAKE_API_KEY"},
            "groq-tier": {"provider": "groq", "model": "some-model", "free_tier": True},
            "local": {"provider": "ollama", "model": "llama3.2:1b", "temperature": 0.4, "max_tokens": 64,
                      "json_mode": True},
            "other-key": {"provider": "custom", "base_url": base_url, "model": "x:free", "api_key_env": "OTHER_KEY",
                          "price_input_per_mtok": 0, "price_output_per_mtok": 0},
            "no-model": {"provider": "openrouter"},
        },
    }), encoding="utf-8")


class ProviderCase(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FakeProvider()
        self.addCleanup(self.provider.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.models_file = self.root / "models.json"
        write_models(self.models_file, self.provider.base_url)
        self.usage_log = self.root / "usage.jsonl"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CP_", "TYPESAFE_", "OPENROUTER", "FAKE_", "OTHER_"))}
        env.update({"CP_MODELS_FILE": str(self.models_file), "FAKE_API_KEY": FAKE_KEY, "CP_USAGE_LOG": str(self.usage_log),
                    "CP_SESSION_ID": "sess-1", "CP_LLM_RETRY_BASE_SECONDS": "0"})
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def usage(self) -> list[dict[str, Any]]:
        if not self.usage_log.is_file():
            return []
        return [json.loads(line) for line in self.usage_log.read_text(encoding="utf-8").splitlines()]


class EnvFileTest(unittest.TestCase):
    def test_parse_formats(self) -> None:
        text = (
            "# comentário\nexport A=1\nB = \"com espaço # não é comentário\"\nC='x=y'\n"
            "D=valor # comentário\nE=\n linha inválida\n1X=bad\n"
        )
        self.assertEqual(
            envfile.parse_env_file(text),
            {"A": "1", "B": "com espaço # não é comentário", "C": "x=y", "D": "valor", "E": ""},
        )

    def test_load_does_not_override_or_set_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KEEP": "env"}, clear=False):
            path = Path(tmp) / ".env"
            path.write_text("\ufeffKEEP=file\nNEW_ONE=ok\nEMPTY_ONE=\n", encoding="utf-8")
            loaded = envfile.load_env_file(path)
            self.assertEqual(loaded, ["NEW_ONE"])
            self.assertEqual(os.environ["KEEP"], "env")
            self.assertEqual(os.environ["NEW_ONE"], "ok")
            self.assertNotIn("EMPTY_ONE", os.environ)
            os.environ.pop("NEW_ONE")
        self.assertEqual(envfile.load_env_file(Path(tmp) / "missing.env"), [])


class LocalFileToolTest(unittest.TestCase):
    def test_reads_utf8_text_relative_to_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "main.py").write_bytes(b"print('oi')\n")

            path, content = local_file_tools.read_local_file("main.py", root)

        self.assertEqual(path, "main.py")
        self.assertEqual(content, "print('oi')\n")

    def test_rejects_paths_outside_repository_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            (base / "outside.py").write_text("not allowed", encoding="utf-8")
            (root / ".env").write_text("TOKEN=secret", encoding="utf-8")

            with self.assertRaisesRegex(local_file_tools.LocalFileReadError, "relativos"):
                local_file_tools.read_local_file("../outside.py", root)
            with self.assertRaisesRegex(local_file_tools.LocalFileReadError, "credenciais"):
                local_file_tools.read_local_file(".env", root)

    def test_rejects_binary_and_oversized_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "binary.dat").write_bytes(b"a\0b")
            (root / "large.txt").write_bytes(b"x" * (local_file_tools.MAX_LOCAL_FILE_BYTES + 1))

            with self.assertRaisesRegex(local_file_tools.LocalFileReadError, "binários"):
                local_file_tools.read_local_file("binary.dat", root)
            with self.assertRaisesRegex(local_file_tools.LocalFileReadError, "excede o limite"):
                local_file_tools.read_local_file("large.txt", root)


class ProfileTest(ProviderCase):
    def test_ollama_is_the_default_profile(self) -> None:
        config = models.load_config(REPOSITORY_ROOT / "models.json")
        profile = models.load_profiles(REPOSITORY_ROOT / "models.json")[config["default"]]
        self.assertEqual((profile.name, profile.provider, profile.model),
                         ("ollama-llama3.2", "ollama", "llama3.2"))
        self.assertEqual(profile.endpoint, "http://localhost:11434")
        self.assertTrue(profile.is_free())
        self.assertEqual(models.load_profiles(REPOSITORY_ROOT / "models.json")["ollama-llama3.2-1b"].model,
                         "llama3.2:1b")

    def test_resolution_order(self) -> None:
        self.assertEqual(models.resolve_profile().name, "fake")
        self.assertEqual(models.resolve_profile("fake-plain").name, "fake-plain")
        with mock.patch.dict(os.environ, {"CP_LLM_PROFILE": "fake-plain"}):
            self.assertEqual(models.resolve_profile().name, "fake-plain")
        with mock.patch.dict(os.environ, {"CP_LLM_MODEL": "legacy:free", "CP_LLM_BASE_URL": self.provider.base_url}):
            with self.assertRaisesRegex(models.ProfileError, "não é gratuito"):
                models.resolve_profile()

    def test_only_free_profiles_unless_explicitly_allowed(self) -> None:
        for name in ["fake", "groq-tier", "local"]:
            with self.subTest(name=name):
                self.assertTrue(models.resolve_profile(name).is_free())
        for name in ["paid", "unpriced"]:
            with self.subTest(name=name):
                with self.assertRaisesRegex(models.ProfileError, "CP_ALLOW_PAID=1"):
                    models.resolve_profile(name)
        with mock.patch.dict(os.environ, {"CP_ALLOW_PAID": "1"}):
            self.assertEqual(models.resolve_profile("paid").model, "fake/paid")

    def test_errors_and_presets(self) -> None:
        with self.assertRaisesRegex(models.ProfileError, "não existe"):
            models.resolve_profile("nope")
        with self.assertRaisesRegex(models.ProfileError, "não tem 'model'"):
            models.resolve_profile("no-model")
        groq = models.load_profiles()["groq-tier"]
        self.assertEqual((groq.base_url, groq.api_key_env), ("https://api.groq.com/openai/v1", "GROQ_API_KEY"))
        self.assertEqual(groq.endpoint, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(models.load_profiles()["local"].key_status(), "sem chave (servidor local)")
        self.assertEqual(models.load_profiles()["local"].endpoint, "http://localhost:11434")

    def test_cost(self) -> None:
        profiles = models.load_profiles()
        self.assertAlmostEqual(profiles["paid"].cost_usd(1_000_000, 100_000), 4.5)
        self.assertEqual(profiles["fake"].cost_usd(500, 50), 0.0)
        self.assertEqual(profiles["groq-tier"].cost_usd(None, None), 0.0)
        self.assertIsNone(profiles["unpriced"].cost_usd(10, 10))

    def test_forwarded_env_carries_only_the_selected_key(self) -> None:
        with mock.patch.dict(os.environ, {"OTHER_KEY": "secret-2", "CP_LLM_PROFILE": "fake"}):
            env = models.forwarded_env("fake")
            self.assertEqual(env["FAKE_API_KEY"], FAKE_KEY)
            self.assertNotIn("OTHER_KEY", env)
            self.assertEqual(env["CP_LLM_PROFILE"], "fake")

    def test_run_service_isolates_keys_per_service(self) -> None:
        captured: dict[str, dict[str, str]] = {}

        def fake_run(cmd: list[str], **kwargs: Any) -> Any:
            captured[cmd[-1].rsplit(".", 1)[-1]] = kwargs["env"]
            return subprocess.CompletedProcess(cmd, 0, stdout='{"status": "ok"}', stderr="")

        extra = {"OTHER_KEY": "secret-2", "CP_EVALUATOR_PROFILE": "other-key", "GITHUB_TOKEN": "gh"}
        with mock.patch.dict(os.environ, extra), mock.patch.object(app.subprocess, "run", fake_run):
            for name in ["sources", "templates", "guardrails"]:
                app.run_service(name, {}, manager_token="t")
        self.assertEqual(captured["templates"]["FAKE_API_KEY"], FAKE_KEY)
        self.assertNotIn("OTHER_KEY", captured["templates"])
        self.assertEqual(captured["guardrails"]["OTHER_KEY"], "secret-2")
        self.assertNotIn("FAKE_API_KEY", captured["guardrails"])
        for key in ["FAKE_API_KEY", "OTHER_KEY"]:
            self.assertNotIn(key, captured["sources"])
        self.assertEqual(captured["sources"]["GITHUB_TOKEN"], "gh")

    def test_ollama_services_have_no_outer_timeout(self) -> None:
        captured: dict[str, float | None] = {}

        def fake_run(cmd: list[str], **kwargs: Any) -> Any:
            captured[cmd[-1].rsplit(".", 1)[-1]] = kwargs["timeout"]
            return subprocess.CompletedProcess(cmd, 0, stdout='{"status": "ok"}', stderr="")

        with mock.patch.dict(os.environ, {"CP_LLM_PROFILE": "local", "CP_EVALUATOR_PROFILE": "local"}), \
                mock.patch.object(app.subprocess, "run", fake_run):
            app.run_service("templates", {})
            app.run_service("guardrails", {})
            app.run_service("sources", {})

        self.assertIsNone(captured["templates"])
        self.assertIsNone(captured["guardrails"])
        self.assertEqual(captured["sources"], app.SERVICE_TIMEOUT_SECONDS)

    def test_openrouter_fields_and_cli(self) -> None:
        catalog = {
            "a/free:free": {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"], "context_length": 8},
            "a/paid": {"pricing": {"prompt": "0.000003", "completion": "0.000015"}, "supported_parameters": [], "context_length": 8},
        }
        self.assertEqual(models.openrouter_profile_fields("a/paid", catalog)["price_input_per_mtok"], 3.0)
        with self.assertRaisesRegex(models.ProfileError, "não lista"):
            models.openrouter_profile_fields("nope", catalog)
        with mock.patch.object(models, "fetch_openrouter_models", return_value=catalog), \
                mock.patch.object(models, "load_env_file"), \
                mock.patch("builtins.print") as printed:
            models.main(["add", "new-free", "--model", "a/free:free"])
            models.main(["add", "new-paid", "--model", "a/paid"])
            models.main(["search"])
        saved = json.loads(self.models_file.read_text(encoding="utf-8"))["profiles"]
        self.assertTrue(saved["new-free"]["json_mode"])
        self.assertEqual(saved["new-paid"]["price_output_per_mtok"], 15.0)
        output = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("não é gratuito", output)
        self.assertIn("a/free:free | gratuito", output)
        self.assertNotIn("a/paid |", output)


class ClientTest(ProviderCase):
    def test_ollama_sdk_request_and_usage(self) -> None:
        captured: dict[str, Any] = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                captured["path"] = self.path
                captured["request"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps({
                    "model": "llama3.2:1b",
                    "message": {"role": "assistant", "content": MODEL_REPLY},
                    "done": True,
                    "prompt_eval_count": 100,
                    "eval_count": 20,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = models.ModelProfile(
            name="local",
            provider="ollama",
            model="llama3.2:1b",
            base_url=f"http://127.0.0.1:{server.server_address[1]}",
            temperature=0.4,
            max_tokens=64,
            json_mode=True,
        )
        try:
            reply = ChatCompletionsClient(profile).complete("sistema", "usuário", json_output=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

        self.assertEqual(reply, MODEL_REPLY)
        self.assertEqual(captured["path"], "/api/chat")
        self.assertEqual(captured["request"]["model"], "llama3.2:1b")
        self.assertEqual(captured["request"]["messages"], [
            {"role": "system", "content": "sistema"},
            {"role": "user", "content": "usuário"},
        ])
        self.assertEqual(captured["request"]["options"], {"temperature": 0.4, "num_predict": 64})
        self.assertEqual(captured["request"]["format"], "json")
        self.assertEqual(
            {key: self.usage()[-1][key] for key in ("profile", "model", "prompt_tokens", "completion_tokens", "cost_usd")},
            {"profile": "local", "model": "llama3.2:1b", "prompt_tokens": 100, "completion_tokens": 20, "cost_usd": 0.0},
        )

    def test_ollama_sdk_executes_tool_calls_and_returns_to_model(self) -> None:
        from types import SimpleNamespace

        captured: dict[str, Any] = {"calls": []}

        class FakeOllamaClient:
            def __init__(self, **kwargs: Any) -> None:
                captured["client"] = kwargs

            def __enter__(self) -> FakeOllamaClient:
                return self

            def __exit__(self, *_args: Any) -> None:
                pass

            def chat(self, **kwargs: Any) -> Any:
                captured["calls"].append(kwargs)
                if len(captured["calls"]) == 1:
                    message = SimpleNamespace(
                        content=None,
                        tool_calls=[SimpleNamespace(function=SimpleNamespace(
                            name="read_local_file", arguments={"path": "main.py"}
                        ))],
                        model_dump=lambda **_kwargs: {
                            "role": "assistant",
                            "tool_calls": [{"function": {"name": "read_local_file", "arguments": {"path": "main.py"}}}],
                        },
                    )
                else:
                    message = SimpleNamespace(content=MODEL_REPLY, tool_calls=[])
                return SimpleNamespace(message=message, prompt_eval_count=100, eval_count=20)

        fake_ollama = type("OllamaModule", (), {"Client": FakeOllamaClient, "ResponseError": RuntimeError})()
        handler = mock.Mock(return_value='{"path":"main.py","content":"print(1)"}')
        with mock.patch.dict(sys.modules, {"ollama": fake_ollama}):
            reply = ChatCompletionsClient("local").complete(
                "system",
                "analyze main.py",
                tools=[local_file_tools.READ_LOCAL_FILE_TOOL],
                tool_handler=handler,
            )

        self.assertEqual(reply, MODEL_REPLY)
        self.assertIsNone(captured["client"]["timeout"])
        self.assertEqual(captured["calls"][0]["tools"], [local_file_tools.READ_LOCAL_FILE_TOOL])
        self.assertEqual(captured["calls"][1]["messages"][-1], {
            "role": "tool",
            "tool_name": "read_local_file",
            "content": '{"path":"main.py","content":"print(1)"}',
        })
        handler.assert_called_once_with("read_local_file", {"path": "main.py"})

    def test_copilot_file_tool_registration(self) -> None:
        from copilot import ToolInvocation

        from cp_framework.copilot_backend import _copilot_tools

        handler = mock.Mock(return_value="file content")
        tool = _copilot_tools([local_file_tools.READ_LOCAL_FILE_TOOL], handler)[0]
        result = asyncio.run(tool.handler(ToolInvocation(arguments={"path": "main.py"})))

        self.assertEqual(tool.name, "read_local_file")
        self.assertIn("path", tool.parameters["properties"])
        self.assertEqual(result.text_result_for_llm, "file content")
        handler.assert_called_once_with("read_local_file", {"path": "main.py"})

    def test_ollama_connection_error_is_actionable(self) -> None:
        captured: dict[str, Any] = {}

        class FakeOllamaClient:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

            def __enter__(self) -> FakeOllamaClient:
                return self

            def __exit__(self, *_args: Any) -> None:
                pass

            def chat(self, **_kwargs: Any) -> Any:
                raise ConnectionError("connection refused")

        fake_ollama = type("OllamaModule", (), {"Client": FakeOllamaClient, "ResponseError": RuntimeError})()
        with mock.patch.dict(sys.modules, {"ollama": fake_ollama}):
            with self.assertRaisesRegex(ProviderError, "Inicie o Ollama"):
                ChatCompletionsClient("local").complete("s", "u")
        self.assertIsNone(captured["timeout"])

    def test_request_shape_auth_and_usage_log(self) -> None:
        reply = ChatCompletionsClient("fake").complete("sistema", "usuário", purpose="template:learning_start")
        self.assertEqual(reply, MODEL_REPLY)
        sent = self.provider.requests[-1]
        self.assertEqual(sent["path"], "/v1/chat/completions")
        self.assertEqual(sent["auth"], f"Bearer {FAKE_KEY}")
        self.assertEqual(sent["body"]["model"], "fake/model:free")
        self.assertEqual([m["role"] for m in sent["body"]["messages"]], ["system", "user"])
        self.assertNotIn("response_format", sent["body"])
        record = self.usage()[-1]
        self.assertEqual(
            {k: record[k] for k in ("profile", "model", "purpose", "prompt_tokens", "completion_tokens", "cost_usd", "status", "session_id")},
            {"profile": "fake", "model": "fake/model:free", "purpose": "template:learning_start", "prompt_tokens": 100,
             "completion_tokens": 20, "cost_usd": 0.0, "status": "ok", "session_id": "sess-1"},
        )
        self.assertNotIn(FAKE_KEY, self.usage_log.read_text(encoding="utf-8"))

    def test_openai_tool_call_reads_file_then_resumes_model_response(self) -> None:
        self.provider.tool_calls = [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "read_local_file", "arguments": '{"path":"main.py"}'},
        }]
        handler = mock.Mock(return_value='{"path":"main.py","content":"print(1)"}')

        reply = ChatCompletionsClient("fake").complete(
            "system",
            "analyze main.py",
            tools=[local_file_tools.READ_LOCAL_FILE_TOOL],
            tool_handler=handler,
        )

        self.assertEqual(reply, MODEL_REPLY)
        handler.assert_called_once_with("read_local_file", {"path": "main.py"})
        first_body = self.provider.requests[0]["body"]
        second_body = self.provider.requests[1]["body"]
        self.assertEqual(first_body["tools"], [local_file_tools.READ_LOCAL_FILE_TOOL])
        self.assertEqual(first_body["tool_choice"], "auto")
        self.assertEqual(second_body["messages"][-1], {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"path":"main.py","content":"print(1)"}',
        })

    def test_json_mode_only_when_profile_supports_it(self) -> None:
        ChatCompletionsClient("fake").complete("objeto JSON", "x", json_output=True)
        self.assertEqual(self.provider.requests[-1]["body"]["response_format"], {"type": "json_object"})
        ChatCompletionsClient("fake-plain").complete("objeto JSON", "x", json_output=True)
        self.assertNotIn("response_format", self.provider.requests[-1]["body"])

    def test_errors(self) -> None:
        self.provider.fail_with = 429
        with self.assertRaisesRegex(ProviderError, r"limite de uso \(HTTP 429\).*/model"):
            ChatCompletionsClient("fake").complete("s", "u", purpose="solver")
        self.assertEqual(len(self.provider.requests), 3)
        self.assertEqual([(r["status"], r["attempt"]) for r in self.usage()], [("error", 0), ("error", 1), ("error", 2)])
        self.assertEqual(self.usage()[-1]["purpose"], "solver")
        self.provider.fail_with = None
        with mock.patch.dict(os.environ, {"FAKE_API_KEY": ""}):
            os.environ.pop("FAKE_API_KEY")
            with self.assertRaisesRegex(ProviderError, "FAKE_API_KEY"):
                ChatCompletionsClient("fake").complete("s", "u")
        with self.assertRaisesRegex(ProviderError, "CP_ALLOW_PAID"):
            ChatCompletionsClient("paid").complete("s", "u")

    def test_rate_limit_is_retried_then_succeeds(self) -> None:
        self.provider.fail_with, self.provider.fail_times = 429, 1
        self.assertEqual(ChatCompletionsClient("fake").complete("s", "u"), MODEL_REPLY)
        self.assertEqual([(r["status"], r["attempt"]) for r in self.usage()], [("error", 0), ("ok", 1)])

    def test_non_retryable_errors_fail_immediately(self) -> None:
        self.provider.fail_with = 401
        with self.assertRaisesRegex(ProviderError, "HTTP 401"):
            ChatCompletionsClient("fake").complete("s", "u")
        self.assertEqual(len(self.provider.requests), 1)
        with mock.patch.dict(os.environ, {"CP_LLM_RETRIES": "0"}):
            self.provider.fail_with = 503
            with self.assertRaisesRegex(ProviderError, "HTTP 503"):
                ChatCompletionsClient("fake").complete("s", "u")
        self.assertEqual(len(self.provider.requests), 2)

    def test_usage_log_can_be_disabled(self) -> None:
        with mock.patch.dict(os.environ, {"CP_USAGE_LOG": "0"}):
            ChatCompletionsClient("fake").complete("s", "u")
        self.assertEqual(self.usage(), [])


class LlmEvaluatorTest(ProviderCase):
    REQUEST = {"template_id": "learning_start", "candidate": "Dica.", "prompt": "quero aprender dp", "facts": {}}

    def test_backend_selection(self) -> None:
        self.assertEqual(guardrails.evaluator_backend(), "none")
        with mock.patch.dict(os.environ, {"CP_EVALUATOR_PROFILE": "fake"}):
            self.assertEqual(guardrails.evaluator_backend(), "llm")
        with mock.patch.dict(os.environ, {"CP_EVALUATOR_BACKEND": "none", "CP_EVALUATOR_PROFILE": "fake"}):
            self.assertEqual(guardrails.evaluator_backend(), "none")

    def test_scores_come_from_model_total_from_code(self) -> None:
        with mock.patch.dict(os.environ, {"CP_EVALUATOR_PROFILE": "fake"}):
            result = guardrails._score_candidate(self.REQUEST)
        self.assertEqual((result["status"], result["backend"], result["total"], result["pass"]), ("scored", "llm", 100, True))
        self.assertEqual(self.provider.requests[-1]["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(self.usage()[-1]["purpose"], "evaluator")

    def test_invalid_or_failed_evaluator_is_not_a_pass(self) -> None:
        cases = [
            ('{"criteria": {"source_fidelity": 4}}', "invalid_output"),
            ("não sei avaliar", "invalid_output"),
            ('{"criteria": {"source_fidelity": "x", "learner_fit": 4, "pedagogy": 4, "problem_references": 4, "format_boundary": 4}}', "invalid_output"),
        ]
        for raw, status in cases:
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"CP_EVALUATOR_PROFILE": "fake"}), \
                    mock.patch.object(FakeProvider, "reply", staticmethod(lambda body, raw=raw: raw)):
                result = guardrails._score_candidate(self.REQUEST)
                self.assertEqual((result["status"], result["pass"]), (status, None))
        self.provider.fail_with = 500
        with mock.patch.dict(os.environ, {"CP_EVALUATOR_PROFILE": "fake"}):
            result = guardrails._score_candidate(self.REQUEST)
        self.assertEqual((result["status"], result["pass"]), ("evaluator_error", None))

    def test_low_scores_reject_and_become_retry_constraints(self) -> None:
        low = json.dumps({"criteria": {key: 1 for key in guardrails.LEARNING_RUBRIC}})
        with mock.patch.dict(os.environ, {"CP_EVALUATOR_PROFILE": "fake"}), \
                mock.patch.object(FakeProvider, "reply", staticmethod(lambda body: low)):
            result = guardrails.postflight({**self.REQUEST, "allowed_source_urls": []})
        self.assertFalse(result["approved"])
        self.assertEqual(result["review_status"], "llm_scored")
        self.assertIn({"criterion_id": "pedagogy", "score": 1}, result["retry_constraints"])


class CheckTest(ProviderCase):
    def test_app_cli_selects_paid_profile_only_with_explicit_opt_in(self) -> None:
        with mock.patch(
            "cp_framework.check.run_checks",
            side_effect=lambda: [{"id": "model_profile", "status": "ok", "detail": models.resolve_profile().name}],
        ), mock.patch("cp_framework.check.format_results", return_value="OK"), \
                mock.patch("builtins.print") as printed, \
                mock.patch.dict(os.environ, {"CP_ALLOW_PAID": "", "CP_LLM_PROFILE": ""}):
            with self.assertRaises(SystemExit) as result:
                app.main(["--model", "paid", "--allow-paid", "--check"])
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(os.environ["CP_LLM_PROFILE"], "paid")
            self.assertEqual(os.environ["CP_ALLOW_PAID"], "1")
            printed.assert_called_once_with("OK")

    def test_check_reports_profile_chat_and_json(self) -> None:
        results = {item["id"]: item for item in check.run_checks()}
        self.assertEqual(results["model_profile"]["status"], "ok")
        self.assertIn("gratuito", results["model_profile"]["detail"])
        self.assertEqual(results["model_chat"]["status"], "ok")
        self.assertEqual(results["model_json"]["status"], "ok")
        self.assertIn("Tudo pronto", check.format_results(list(results.values())))

    def test_check_fails_without_key_and_for_paid_profile(self) -> None:
        os.environ.pop("FAKE_API_KEY")
        results = {item["id"]: item for item in check.run_checks()}
        self.assertEqual(results["api_key"]["status"], "fail")
        self.assertNotIn("model_chat", results)
        with mock.patch.dict(os.environ, {"CP_LLM_PROFILE": "paid", "FAKE_API_KEY": FAKE_KEY}):
            results = {item["id"]: item for item in check.run_checks()}
        self.assertEqual(results["model_profile"]["status"], "fail")
        self.assertIn("CP_ALLOW_PAID", results["model_profile"]["detail"])

    def test_check_all_skips_paid_and_keyless(self) -> None:
        report, failed = check.run_all_checks()
        self.assertFalse(failed)
        self.assertRegex(report, r"fake \| fake/model:free \| ok \| ok")
        self.assertIn("paid | fake/paid | - | - | - | pago: ignorado", report)
        self.assertIn("other-key | x:free | - | - | - | sem chave (OTHER_KEY)", report)
        self.assertIn("no-model | - |", report)


class TerminalOutputTest(unittest.TestCase):
    def test_banner_is_omitted_when_it_does_not_fit(self) -> None:
        self.assertIsNone(app.startup_banner(100))
        self.assertEqual(app.startup_banner(162), app.ASCII_BANNER)

    def test_render_markdown_passes_source_to_glow_with_terminal_width(self) -> None:
        completed = subprocess.CompletedProcess(["glow"], 0, stdout="", stderr="")
        with mock.patch.object(app.shutil, "get_terminal_size", return_value=os.terminal_size((88, 24))), \
                mock.patch.object(app.subprocess, "run", return_value=completed) as run:
            app.render_markdown("**texto**", "glow")

        args, kwargs = run.call_args
        self.assertEqual(args[0], ["glow", "-w", "88", "-"])
        self.assertEqual(kwargs["input"], "**texto**")
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertNotIn("stdout", kwargs)

    def test_render_markdown_falls_back_to_plain_text_without_glow(self) -> None:
        with mock.patch("builtins.print") as printed:
            app.render_markdown("**texto**", None)

        printed.assert_called_once_with("**texto**", end="")

    def test_glow_failure_is_reported_and_falls_back_to_plain_text(self) -> None:
        failed = subprocess.CompletedProcess(["glow"], 1, stdout="", stderr="falha")
        with mock.patch.object(app.subprocess, "run", return_value=failed), \
                mock.patch("builtins.print") as printed, \
                mock.patch("sys.stderr") as stderr:
            app.render_markdown("**texto**", "glow")

        self.assertEqual(printed.call_count, 2)
        self.assertIn("Glow falhou", printed.call_args_list[0].args[0])
        self.assertIn("file", printed.call_args_list[0].kwargs)
        printed.assert_called_with("**texto**", end="")
        self.assertIs(printed.call_args_list[0].kwargs["file"], stderr)


class EndToEndChatTest(ProviderCase):
    """Starts the real app (with real service subprocesses) and chats through stdin."""

    def run_app(self, lines: list[str], *args: str) -> subprocess.CompletedProcess[str]:
        data_root = self.root / "data" / "sources"
        if not data_root.exists():
            write_fixture_data(data_root)
        env = dict(os.environ)
        env.update({
            "PYTHONPATH": str(REPOSITORY_ROOT),
            "PYTHONIOENCODING": "utf-8",
            "CP_DATA_DIR": str(data_root),
            "CP_ENV_FILE": str(self.root / "missing.env"),
            "CP_USAGE_LOG": str(self.usage_log),
        })
        env.pop("CP_SESSION_ID", None)
        return subprocess.run(
            [sys.executable, "-m", "cp_framework.app", *args],
            input="\n".join(lines) + "\n", text=True, encoding="utf-8", capture_output=True,
            cwd=REPOSITORY_ROOT, env=env, timeout=180,
        )

    def test_chat_session_with_configured_model(self) -> None:
        result = self.run_app(["/model", "/help", "/learn dp", "quero dicas do 1950D", "/quit"], "--model", "fake")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("modelo fake (fake/model:free)", result.stdout)
        self.assertNotIn("COMPETITIVE PROGRAMMING COACH", result.stdout)
        self.assertNotIn("perfil USER", result.stdout)
        self.assertNotIn("O modo ADMIN vem apenas", result.stdout)
        self.assertNotIn("/model [perfil]", result.stdout)
        self.assertIn("/consolidar (/consolidate)", result.stdout)
        self.assertIn("* fake: custom | fake/model:free | gratuito", result.stdout)
        self.assertTrue(any(
            any(tool["function"]["name"] == "read_local_file" for tool in request["body"].get("tools", []))
            for request in self.provider.requests
        ))
        self.assertIn("\nVocê> ", result.stdout)
        self.assertRegex(result.stdout, r"\[\d{2}:\d{2}:\d{2}\] Mensagem enviada\.")
        self.assertRegex(result.stdout, r"\[\d{2}:\d{2}:\d{2}\] Manager>")
        self.assertIn(MODEL_REPLY, result.stdout)
        self.assertIn("Sessão encerrada.", result.stdout)
        purposes = [record["purpose"] for record in self.usage()]
        self.assertEqual(purposes, ["solver", "template:learning_start"])
        self.assertEqual(len({record["session_id"] for record in self.usage()}), 1)
        self.assertTrue(self.usage()[0]["session_id"])

    def test_switching_model_mid_chat(self) -> None:
        result = self.run_app(["/model fake-plain", "/model paid", "quero aprender dp", "/quit"], "--model", "fake")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Modelo trocado para fake-plain (fake/plain:free).", result.stdout)
        self.assertIn("CP_ALLOW_PAID=1", result.stdout)
        self.assertEqual(self.provider.requests[-1]["body"]["model"], "fake/plain:free")

    def test_sair_command_returns_to_terminal_without_model_call(self) -> None:
        result = self.run_app(["/sair"], "--model", "fake")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Sessão encerrada.", result.stdout)
        self.assertEqual(self.provider.requests, [])

    def test_startup_refuses_paid_or_unknown_profiles(self) -> None:
        for name, message in [("paid", "não é gratuito"), ("nope", "não existe")]:
            with self.subTest(name=name):
                result = self.run_app(["/quit"], "--model", name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
        self.assertEqual(self.provider.requests, [])

    def test_check_command(self) -> None:
        result = self.run_app([], "--check", "--model", "fake")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[ok]    model_json", result.stdout)


if __name__ == "__main__":
    unittest.main()
