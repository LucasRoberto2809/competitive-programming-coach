"""Deterministic user-facing messages in the two supported languages (pt-BR and en)."""

from __future__ import annotations

import re
from typing import Any

from .catalog import normalize

LANGUAGES = ("pt-BR", "en")

EN_WORDS = {
    "the", "i", "want", "to", "learn", "study", "give", "me", "please", "how", "what", "is", "my",
    "can", "you", "and", "of", "for", "with", "problem", "problems", "solution", "code", "this",
    "do", "does", "it", "a", "an", "some", "easy", "hard", "more", "help", "now", "about", "should",
}
PT_WORDS = {
    "o", "a", "os", "as", "eu", "quero", "aprender", "estudar", "me", "da", "de", "do", "por", "favor",
    "como", "que", "e", "meu", "minha", "voce", "pode", "para", "pra", "com", "um", "uma", "problema",
    "problemas", "solucao", "codigo", "isso", "esse", "este", "esta", "essa", "faceis", "dificeis", "mais",
    "ajuda", "agora", "sobre", "nao", "sim", "tema", "estou", "tenho", "criei", "fiz", "quero", "vamos",
}

FLOW = {
    "pt-BR": (
        "Fluxo da ferramenta:\n"
        "- Aprendizado: tema → leitura (CP-Algorithms) e problemas do Codeforces por faixa → sua "
        "observação ou pseudocódigo → dicas progressivas → solução completa (depois do pseudocódigo).\n"
        "- Problem Setter: seu enunciado → revisão dos exemplos de entrada/saída → hipótese de falha → "
        "testes de estresse para o seu código."
    ),
    "en": (
        "How this tool works:\n"
        "- Learning: topic → reading (CP-Algorithms) and Codeforces problems by band → your "
        "observation or pseudocode → progressive hints → full solution (after the pseudocode).\n"
        "- Problem Setter: your statement → review of the sample input/output → failure hypothesis → "
        "stress tests for your code."
    ),
}

TEXT: dict[str, dict[str, str]] = {
    "out_of_scope": {
        "pt-BR": (
            "Esta ferramenta se limita a explorar, resolver e criar problemas de programação competitiva "
            "usando os temas do catálogo do Codeforces (ex.: {examples}). Esse pedido está fora desse escopo. "
            "Para esse objetivo, recomendo abrir outro chat, sem a ferramenta."
        ),
        "en": (
            "This tool is limited to exploring, solving, and creating competitive programming problems "
            "using the Codeforces catalog topics (e.g. {examples}). This request is outside that scope. "
            "For that goal, I recommend opening another chat without this tool."
        ),
    },
    "statement_in_learning": {
        "pt-BR": (
            "No modo Aprendizado não ajudamos a elaborar ou interpretar textos de enunciado. Para estudar um "
            "problema do Codeforces, envie o ID (ex.: 1950D) ou o link. Se o enunciado é seu, use /setter: lá "
            "explicamos os exemplos e os casos de teste do problema que você está criando."
        ),
        "en": (
            "In Learning mode we don't help write or interpret statement texts. To study a Codeforces "
            "problem, send its ID (e.g. 1950D) or link. If the statement is yours, use /setter: there we "
            "explain the samples and test cases of the problem you are creating."
        ),
    },
    "needs_focus_problem": {
        "pt-BR": (
            "Para a solução completa, diga qual problema: envie o ID (ex.: 1950D) ou o link do Codeforces "
            "de um dos problemas indicados."
        ),
        "en": (
            "For the full solution, tell me which problem: send the Codeforces ID (e.g. 1950D) or the link "
            "of one of the suggested problems."
        ),
    },
    "needs_stress_input": {
        "pt-BR": (
            "Ainda não vou gerar os casos de estresse. Para seguir, envie: {missing}. Se quiser começar pelo "
            "método, diga que quer entender como estressar o problema."
        ),
        "en": (
            "I won't generate stress cases yet. To continue, send: {missing}. If you want to start with the "
            "method, say you want to understand how to stress the problem."
        ),
    },
    "missing_statement": {"pt-BR": "enunciado completo", "en": "full statement"},
    "missing_constraints": {"pt-BR": "limites/restrições", "en": "limits/constraints"},
    "missing_code": {"pt-BR": "sua solução em código", "en": "your solution code"},
    "transition": {
        "pt-BR": (
            "Você estava no modo {from_label} (tema: {topic}; etapa: {stage}). Mudando para o modo "
            "{to_label}. Use /retomar para voltar exatamente a esse ponto."
        ),
        "en": (
            "You were in {from_label} mode (topic: {topic}; stage: {stage}). Switching to {to_label} mode. "
            "Use /resume to return exactly to that point."
        ),
    },
    "topic_change": {
        "pt-BR": "Perfeito, vamos explorar mais sobre {topic}.",
        "en": "Great, let's explore more about {topic}.",
    },
    "similar_problem": {
        "pt-BR": "Aviso: há um problema publicado muito semelhante: {listed}.",
        "en": "Note: there is a very similar published problem: {listed}.",
    },
    "identical_problem": {
        "pt-BR": "Aviso: o enunciado é idêntico a um problema publicado: {listed}.",
        "en": "Note: the statement is identical to a published problem: {listed}.",
    },
    "guardrail_fallback": {
        "pt-BR": "Não consegui preparar uma resposta que passasse pelos Guardrails. Tente reformular o pedido ou enviar mais contexto.",
        "en": "I couldn't prepare an answer that passed the Guardrails. Try rephrasing or sending more context.",
    },
    "context_low": {
        "pt-BR": (
            "Estamos com pouco espaço na janela de contexto ({used}% usado). Recomendo consolidar o que "
            "fizemos até aqui."
        ),
        "en": "We are running low on context window ({used}% used). I recommend consolidating what we did so far.",
    },
    "consolidation_options": {
        "pt-BR": (
            "Escolha uma opção:\n"
            "1. /recomecar — limpa este chat e usa o resumo acima como contexto inicial.\n"
            "2. Mantenha este chat como histórico e inicie um novo chat com este resumo: "
            "python -m cp_framework.app --contexto \"{path}\""
        ),
        "en": (
            "Choose an option:\n"
            "1. /restart — clears this chat and uses the summary above as the initial context.\n"
            "2. Keep this chat as history and start a new chat with this summary: "
            "python -m cp_framework.app --contexto \"{path}\""
        ),
    },
    "resumed": {
        "pt-BR": "Retomando o modo {label} (tema: {topic}; etapa: {stage}).",
        "en": "Resuming {label} mode (topic: {topic}; stage: {stage}).",
    },
    "nothing_to_resume": {
        "pt-BR": "Não há etapa anterior salva para retomar.",
        "en": "There is no saved previous stage to resume.",
    },
}

MODE_LABELS = {
    "pt-BR": {"LEARNING": "Aprendizado", "PROBLEM_SETTER": "Problem Setter"},
    "en": {"LEARNING": "Learning", "PROBLEM_SETTER": "Problem Setter"},
}


def detect_language(text: str, previous: str = "pt-BR") -> str:
    """Pick pt-BR or en from common words; keep the previous language when unclear.

    Statements and code are data, not the user's language, so they are ignored.
    """
    text = re.sub(r"```.*?(?:```|$)", " ", text, flags=re.S)
    text = re.split(r"(?:problem\s*statement|statement|enunciado)\s*:", text, maxsplit=1, flags=re.I)[0]
    words = [word for word in re.findall(r"[a-z]+", normalize(text)) if len(word) > 1]
    en = sum(word in EN_WORDS for word in words)
    pt = sum(word in PT_WORDS for word in words)
    if en >= 3 and en > pt * 1.5:
        return "en"
    if pt >= 1 and pt >= en:
        return "pt-BR"
    return previous if previous in LANGUAGES else "pt-BR"


def text(key: str, language: str = "pt-BR", **values: Any) -> str:
    template = TEXT[key].get(language) or TEXT[key]["pt-BR"]
    return template.format(**values)


def mode_label(mode: str, language: str = "pt-BR") -> str:
    return MODE_LABELS.get(language, MODE_LABELS["pt-BR"]).get(mode, mode)
