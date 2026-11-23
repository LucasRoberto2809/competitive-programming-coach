"""Run user code against proposed stress cases in the current environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from hooks._support.io import run_cli


MAX_CASES = 40
MAX_SOURCE_BYTES = 256_000
MAX_CASE_TEXT_BYTES = 16_000
MAX_OUTPUT_BYTES = 64_000
MAX_COMPILER_SECONDS = 20
MAX_TOTAL_SECONDS = 60


def _required_text(request: dict[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} precisa ser um texto não vazio.")
    return value


def _validate_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("task_mode") != "STRESS_TEST":
        raise ValueError("O hook de execução só aceita task_mode=STRESS_TEST.")
    if request.get("phase") != "case_proposal":
        raise ValueError("O hook de execução só pode ser usado na etapa case_proposal.")

    _required_text(request, "problem_statement")
    _required_text(request, "constraints")
    _required_text(request, "stress_hypothesis")

    solution = request.get("solution")
    if not isinstance(solution, dict):
        raise ValueError("solution precisa conter language e source.")
    language = solution.get("language")
    if not isinstance(language, str) or language not in {"cpp", "python"}:
        raise ValueError("solution.language deve ser cpp ou python.")
    source = solution.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("solution.source precisa ser um texto não vazio.")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"O código excede o limite de {MAX_SOURCE_BYTES} bytes.")

    cases = request.get("test_cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("test_cases precisa conter ao menos um caso.")
    if len(cases) > MAX_CASES:
        raise ValueError(f"São permitidos no máximo {MAX_CASES} casos por chamada.")

    checked_cases = []
    seen_ids: set[str] = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"test_cases[{index - 1}] precisa ser um objeto.")
        case_id = case.get("id", f"case-{index}")
        if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 80:
            raise ValueError(f"test_cases[{index - 1}].id deve ter de 1 a 80 caracteres.")
        case_id = case_id.strip()
        if case_id in seen_ids:
            raise ValueError(f"ID de caso duplicado: {case_id}.")
        seen_ids.add(case_id)
        input_text = case.get("input")
        expected_output = case.get("expected_output")
        if not isinstance(input_text, str) or not isinstance(expected_output, str):
            raise ValueError(f"O caso {case_id} precisa de input e expected_output em texto.")
        if len(input_text.encode("utf-8")) > MAX_CASE_TEXT_BYTES:
            raise ValueError(f"A entrada do caso {case_id} excede {MAX_CASE_TEXT_BYTES} bytes.")
        if len(expected_output.encode("utf-8")) > MAX_CASE_TEXT_BYTES:
            raise ValueError(f"A saída esperada do caso {case_id} excede {MAX_CASE_TEXT_BYTES} bytes.")
        checked_cases.append(
            {"id": case_id, "input": input_text, "expected_output": expected_output}
        )

    timeout_seconds = request.get("timeout_seconds", 1.0)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds precisa ser um número entre 0.1 e 5.")
    if not 0.1 <= timeout_seconds <= 5:
        raise ValueError("timeout_seconds precisa ser um número entre 0.1 e 5.")

    return {
        "language": language,
        "source": source,
        "test_cases": checked_cases,
        "timeout_seconds": float(timeout_seconds),
    }


def _execution_environment() -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _snippet(text: str) -> str:
    if len(text.encode("utf-8")) <= 2000:
        return text
    return text[:2000] + "\n[truncated]"


def _run_process(
    command: list[str],
    input_text: str | None,
    timeout: float,
    working_directory: Path,
) -> tuple[int | None, str, str, bool, bool]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=working_directory,
        env=_execution_environment(),
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdout = bytearray()
    stderr = bytearray()
    output_exceeded = threading.Event()

    def collect(stream: BinaryIO, output: bytearray) -> None:
        while True:
            chunk = stream.read(min(8192, MAX_OUTPUT_BYTES + 1 - len(output)))
            if not chunk:
                return
            remaining = MAX_OUTPUT_BYTES - len(output)
            output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                output_exceeded.set()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return

    def send_input() -> None:
        try:
            process.stdin.write((input_text or "").encode("utf-8"))
            process.stdin.flush()
        except OSError:
            pass
        finally:
            process.stdin.close()

    readers = [
        threading.Thread(target=collect, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=collect, args=(process.stderr, stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    writer = threading.Thread(target=send_input, daemon=True)
    writer.start()

    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()

    writer.join(timeout=1)
    for reader in readers:
        reader.join(timeout=1)
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        timed_out,
        output_exceeded.is_set(),
    )


def _summary(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "passed": sum(result["status"] == "passed" for result in results),
        "failed": sum(result["status"] == "failed" for result in results),
        "runtime_errors": sum(result["status"] == "runtime_error" for result in results),
        "timeouts": sum(result["status"] == "timeout" for result in results),
        "output_limits": sum(result["status"] == "output_limit" for result in results),
        "not_run": sum(result["status"] == "not_run" for result in results),
    }


def handle(request: dict[str, Any]) -> dict[str, Any]:
    """Validate the stress-test-only gate, then run with local tools."""
    payload = _validate_request(request)
    deadline = time.monotonic() + MAX_TOTAL_SECONDS

    with tempfile.TemporaryDirectory(prefix="cp-stress-") as temporary_directory:
        working_directory = Path(temporary_directory)
        if payload["language"] == "cpp":
            source_path = working_directory / "solution.cpp"
            source_path.write_text(payload["source"], encoding="utf-8")
            compiler_name = os.environ.get("CXX", "g++")
            compiler = shutil.which(compiler_name)
            if compiler is None:
                raise RuntimeError(
                    f"Compilador C++ '{compiler_name}' não encontrado no PATH."
                )
            binary_path = working_directory / (
                "solution.exe" if os.name == "nt" else "solution"
            )
            compile_timeout = min(
                MAX_COMPILER_SECONDS,
                max(0.1, deadline - time.monotonic()),
            )
            code, _, stderr, timed_out, output_exceeded = _run_process(
                [
                    compiler,
                    "-std=c++20",
                    "-O2",
                    "-pipe",
                    str(source_path),
                    "-o",
                    str(binary_path),
                ],
                None,
                compile_timeout,
                working_directory,
            )
            if timed_out:
                return {"status": "compile_timeout", "compiler_output": _snippet(stderr)}
            if output_exceeded:
                return {
                    "status": "compile_output_limit",
                    "compiler_output": _snippet(stderr),
                }
            if code != 0:
                return {"status": "compile_error", "compiler_output": _snippet(stderr)}
            run_command = [str(binary_path)]
        else:
            source_path = working_directory / "solution.py"
            source_path.write_text(payload["source"], encoding="utf-8")
            run_command = [sys.executable, "-I", "-B", str(source_path)]

        results = []
        for case in payload["test_cases"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                results.append({"case_id": case["id"], "status": "not_run"})
                continue
            code, actual, stderr, timed_out, output_exceeded = _run_process(
                run_command,
                case["input"],
                min(payload["timeout_seconds"], remaining),
                working_directory,
            )
            if timed_out:
                results.append({"case_id": case["id"], "status": "timeout"})
            elif output_exceeded:
                results.append({"case_id": case["id"], "status": "output_limit"})
            elif code != 0:
                results.append(
                    {
                        "case_id": case["id"],
                        "status": "runtime_error",
                        "exit_code": code,
                        "stderr": _snippet(stderr),
                    }
                )
            else:
                expected = case["expected_output"]
                matches = actual.split() == expected.split()
                results.append(
                    {
                        "case_id": case["id"],
                        "status": "passed" if matches else "failed",
                        "matches_expected": matches,
                        "actual_output": _snippet(actual),
                        "expected_output": _snippet(expected),
                    }
                )

        summary = _summary(results)
        return {
            "status": "completed" if summary["not_run"] == 0 else "deadline_exceeded",
            "language": payload["language"],
            "results": results,
            "summary": summary,
        }


if __name__ == "__main__":
    run_cli(handle)
