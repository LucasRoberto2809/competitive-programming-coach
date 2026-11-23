from __future__ import annotations

from pathlib import Path

from .config import SKILLS_ROOT


SKILL_NAMES = {
    "manager": "competitive-programming-manager",
    "coach": "competitive-programming-coach",
    "solver": "competitive-programming-solver",
    "evaluator": "competitive-programming-evaluator",
    "originality": "competitive-programming-originality",
}


def load_skill(role: str) -> str:
    try:
        skill_name = SKILL_NAMES[role]
    except KeyError as exc:
        raise ValueError(f"Skill desconhecida: {role}") from exc
    path: Path = SKILLS_ROOT / skill_name / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"Skill ausente: {path}")
    return path.read_text(encoding="utf-8")

