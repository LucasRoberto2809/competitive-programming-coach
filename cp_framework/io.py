from __future__ import annotations

import json
import sys
from typing import Any


def read_request() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("Envie um objeto JSON pela entrada padrão.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("A requisição precisa ser um objeto JSON.")
    return value


def write_response(value: dict[str, Any]) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def run_cli(handler) -> None:
    try:
        write_response(handler(read_request()))
    except Exception as exc:  # CLI boundary: return machine-readable errors.
        write_response({"status": "error", "error": str(exc)})
        raise SystemExit(2) from exc

