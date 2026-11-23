"""Read-only local file tools exposed to chat models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import REPOSITORY_ROOT

MAX_LOCAL_FILE_BYTES = 256 * 1024
READ_LOCAL_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_local_file",
        "description": "Read a UTF-8 text file inside the current repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative path to the text file.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}
BLOCKED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "copilot-home",
}
BLOCKED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class LocalFileReadError(ValueError):
    """A requested file is outside the safe, readable workspace scope."""


def read_local_file(path: str, root: Path = REPOSITORY_ROOT) -> tuple[str, str]:
    if not isinstance(path, str) or not path.strip():
        raise LocalFileReadError("Informe um caminho relativo ao repositório.")

    relative = Path(path.strip())
    if relative.is_absolute() or relative.drive or ".." in path.replace("\\", "/").split("/"):
        raise LocalFileReadError("Só são permitidos caminhos relativos dentro do repositório.")

    root_path = root.resolve()
    try:
        target = (root_path / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise LocalFileReadError("Arquivo não encontrado no repositório.") from exc
    try:
        repo_relative = target.relative_to(root_path)
    except ValueError as exc:
        raise LocalFileReadError("O caminho aponta para fora do repositório.") from exc

    parts = tuple(part.casefold() for part in repo_relative.parts)
    filename = target.name.casefold()
    if any(part in BLOCKED_DIRECTORIES for part in parts):
        raise LocalFileReadError("Esse diretório não pode ser lido pela ferramenta.")
    if filename.startswith(".env.") and filename != ".env.example":
        raise LocalFileReadError("Arquivos de ambiente e credenciais não podem ser lidos.")
    if filename in BLOCKED_FILENAMES or target.suffix.casefold() in BLOCKED_SUFFIXES:
        raise LocalFileReadError("Arquivos de ambiente e credenciais não podem ser lidos.")
    if len(parts) >= 2 and parts[0] == "data" and "sessions" in parts:
        raise LocalFileReadError("Transcrições de sessão não podem ser lidas pela ferramenta.")
    if not target.is_file():
        raise LocalFileReadError("O caminho não aponta para um arquivo.")
    if target.stat().st_size > MAX_LOCAL_FILE_BYTES:
        raise LocalFileReadError(f"O arquivo excede o limite de {MAX_LOCAL_FILE_BYTES // 1024} KiB.")

    content = target.read_bytes()
    if len(content) > MAX_LOCAL_FILE_BYTES:
        raise LocalFileReadError(f"O arquivo excede o limite de {MAX_LOCAL_FILE_BYTES // 1024} KiB.")
    if b"\0" in content:
        raise LocalFileReadError("Arquivos binários não podem ser lidos.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalFileReadError("O arquivo não está codificado em UTF-8.") from exc
    return repo_relative.as_posix(), text


def execute_local_file_tool(name: str, arguments: dict[str, Any]) -> str:
    if name != "read_local_file":
        return json.dumps({"error": "Ferramenta desconhecida."}, ensure_ascii=False)
    try:
        path, content = read_local_file(arguments.get("path"))
    except LocalFileReadError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except OSError:
        return json.dumps({"error": "Não foi possível ler o arquivo informado."}, ensure_ascii=False)
    return json.dumps({"path": path, "content": content}, ensure_ascii=False)
