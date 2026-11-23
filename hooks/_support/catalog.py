"""Local catalog lookups: topics -> Codeforces tags, problem selection, articles, similar problems."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from . import config


CATALOG_FILE = "codeforces_catalog.json"
ARTICLE_INDEX_FILE = "cp_algorithms_index.json"

BANDS: dict[str, tuple[int, int]] = {
    "easy": (800, 999),
    "medium": (1000, 1499),
    "hard": (1500, 2099),
    "veteran": (2100, 3500),
}
LEARNING_BANDS = ("easy", "medium", "hard")
SETTER_BANDS = ("easy", "medium", "hard", "veteran")
BAND_ORDER = SETTER_BANDS
LEARNING_MAX_RATING = BANDS["hard"][1]
MIN_RATING, MAX_RATING = 800, 3500
DEFAULT_PER_BAND = {"LEARNING": 2, "PROBLEM_SETTER": 1}
MAX_PER_BAND = 3
NEIGHBOR_STEPS = (100, 200)
MIN_TITLE_MATCH_CHARS = 12
SIMILAR_TITLE_THRESHOLD = 0.6
TAG_SYNONYMS: dict[str, tuple[str, ...]] = {
    "dp": ("programacao dinamica", "dynamic programming", "mochila", "knapsack"),
    "binary search": ("busca binaria", "pesquisa binaria"),
    "greedy": ("guloso", "gulosos", "gulosa", "algoritmos gulosos"),
    "math": ("matematica",),
    "implementation": ("implementacao", "simulacao", "simulation"),
    "constructive algorithms": ("construtivo", "construtivos", "algoritmos construtivos", "constructive"),
    "data structures": (
        "estruturas de dados", "estrutura de dados", "segment tree", "segment trees",
        "arvore de segmentos", "arvores de segmentos", "fenwick", "sparse table",
    ),
    "brute force": ("forca bruta",),
    "sortings": ("ordenacao", "sorting"),
    "graphs": ("grafo", "grafos", "graph"),
    "dfs and similar": ("dfs", "bfs", "busca em profundidade", "busca em largura"),
    "trees": ("arvore", "arvores", "tree"),
    "number theory": ("teoria dos numeros", "numeros primos", "primos", "mdc", "gcd"),
    "combinatorics": ("combinatoria", "analise combinatoria"),
    "strings": ("string", "cadeias de caracteres"),
    "bitmasks": ("bitmask", "mascara de bits", "mascaras de bits", "bitwise"),
    "two pointers": ("dois ponteiros", "two pointer"),
    "geometry": ("geometria", "geometria computacional"),
    "dsu": ("union find", "union-find", "conjuntos disjuntos", "disjoint set union"),
    "divide and conquer": ("divisao e conquista", "dividir e conquistar"),
    "interactive": ("interativo", "interativos", "problemas interativos"),
    "games": ("jogos", "teoria dos jogos", "game theory"),
    "shortest paths": (
        "caminho minimo", "caminhos minimos", "menor caminho", "shortest path", "dijkstra",
        "bellman ford", "floyd warshall",
    ),
    "probabilities": ("probabilidade", "probabilidades", "probability"),
    "hashing": ("hash", "string hashing"),
    "flows": ("fluxo maximo", "fluxo em redes", "max flow", "fluxos"),
    "matrices": ("matriz", "matrizes", "matrix", "exponenciacao de matrizes"),
    "fft": ("transformada de fourier", "fourier"),
    "graph matchings": ("emparelhamento", "emparelhamentos", "matching", "bipartite matching"),
    "string suffix structures": (
        "suffix array", "array de sufixos", "vetor de sufixos", "suffix automaton",
        "automato de sufixos", "arvore de sufixos",
    ),
    "ternary search": ("busca ternaria",),
    "meet-in-the-middle": ("meet in the middle",),
    "2-sat": ("2sat", "2 sat"),
    "expression parsing": ("parsing de expressoes", "avaliacao de expressoes"),
    "chinese remainder theorem": ("teorema chines do resto", "chinese remainder"),
    "schedules": ("escalonamento", "agendamento"),
    "communication": ("comunicacao",),
}

TAG_ARTICLES: dict[str, tuple[str, ...]] = {
    "dp": (
        "src/dynamic_programming/intro-to-dp.md",
        "src/dynamic_programming/knapsack.md",
        "src/dynamic_programming/longest_increasing_subsequence.md",
    ),
    "binary search": ("src/num_methods/binary_search.md",),
    "ternary search": ("src/num_methods/ternary_search.md",),
    "graphs": ("src/graph/breadth-first-search.md", "src/graph/depth-first-search.md"),
    "dfs and similar": ("src/graph/depth-first-search.md", "src/graph/breadth-first-search.md"),
    "shortest paths": ("src/graph/dijkstra.md", "src/graph/01_bfs.md", "src/graph/bellman_ford.md"),
    "trees": ("src/graph/lca_binary_lifting.md", "src/graph/depth-first-search.md"),
    "dsu": ("src/data_structures/disjoint_set_union.md",),
    "data structures": (
        "src/data_structures/segment_tree.md",
        "src/data_structures/fenwick.md",
        "src/data_structures/sparse-table.md",
    ),
    "number theory": (
        "src/algebra/sieve-of-eratosthenes.md",
        "src/algebra/euclid-algorithm.md",
        "src/algebra/module-inverse.md",
    ),
    "math": ("src/algebra/binary-exp.md", "src/algebra/euclid-algorithm.md"),
    "combinatorics": (
        "src/combinatorics/binomial-coefficients.md",
        "src/combinatorics/inclusion-exclusion.md",
    ),
    "strings": ("src/string/prefix-function.md", "src/string/z-function.md"),
    "hashing": ("src/string/string-hashing.md",),
    "string suffix structures": ("src/string/suffix-array.md", "src/string/suffix-automaton.md"),
    "bitmasks": ("src/algebra/bit-manipulation.md", "src/algebra/all-submasks.md"),
    "geometry": ("src/geometry/basic-geometry.md", "src/geometry/convex-hull.md"),
    "games": ("src/game_theory/sprague-grundy-nim.md", "src/game_theory/games_on_graphs.md"),
    "flows": ("src/graph/dinic.md", "src/graph/edmonds_karp.md"),
    "graph matchings": ("src/graph/kuhn_maximum_bipartite_matching.md",),
    "fft": ("src/algebra/fft.md",),
    "matrices": ("src/linear_algebra/linear-system-gauss.md", "src/graph/fixed_length_paths.md"),
    "2-sat": ("src/graph/2SAT.md",),
    "chinese remainder theorem": ("src/algebra/chinese-remainder-theorem.md",),
    "expression parsing": ("src/string/expression_parsing.md",),
    "schedules": ("src/schedules/schedule_one_machine.md",),
    "divide and conquer": ("src/dynamic_programming/divide-and-conquer-dp.md",),
    "two pointers": ("src/others/maximum_average_segment.md",),
}

NUMBER_WORDS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
}
VAGUE_WORDS = (
    "varios", "varias", "alguns", "algumas", "muitos", "muitas", "diversos", "diversas",
    "mais", "outros", "outras", "several", "some", "many", "more",
)
BAND_WORDS = {
    "easy": r"faceis|facil|easy",
    "medium": r"medios?|intermediarios?|medium",
    "hard": r"dificeis|dificil|hard",
    "veteran": r"veteranos?|veterans?",
}
PLURAL_BAND_WORDS = {"faceis", "medios", "intermediarios", "dificeis", "veteranos", "veterans"}
QUANTITY_RE = r"(\d{1,3}|" + "|".join(NUMBER_WORDS) + "|" + "|".join(VAGUE_WORDS) + r")"
PROBLEM_NOUN_RE = r"(?:problemas?|exercicios?|questoes|questao|problems?|exercises?)"
PLURAL_NOUN_RE = r"(?:problemas|exercicios|questoes|problems|exercises)"
GENERAL_COUNT_RE = re.compile(
    r"\b" + QUANTITY_RE + r"\s+(?:\w+\s+)?" + PLURAL_NOUN_RE + r"\b"
    r"|\bmais\s+(um|uma)\s+" + PROBLEM_NOUN_RE + r"\b"
)
REQUEST_VERB_RE = re.compile(
    r"\b(?:quero|queria|gostaria\s+de|preciso\s+de|me\s+(?:da|de|passa|passe|manda|mande|indica|indique|"
    r"recomenda|recomende|sugere|sugira|mostra|mostre)|indique|recomende|sugira|liste|give\s+me|"
    r"recommend)\b(?:\s+\w+){0,3}?\s+" + PLURAL_NOUN_RE + r"\b"
)
RANGE_RE = re.compile(r"(?<!\d)(\d{3,4})\s*(?:-|–|a|ate|to|e)\s*(\d{3,4})(?!\d)")
SINGLE_RATING_RE = re.compile(r"\b(?:rating|dificuldade|nivel)\s*(?:de\s*)?~?\s*(\d{3,4})\b")
VETERAN_RATING_RE = re.compile(r"\b2[1-9]00\s*\+")
CODEFORCES_PROBLEM_URL_RE = re.compile(
    r"codeforces\.com/(?:problemset/problem|contest|gym)/(\d+)/(?:problem/)?([A-Za-z]\d?)", re.I
)
PROBLEM_ID_RE = re.compile(r"(?<![\w/])(\d{1,4})([A-Z]\d?)(?![\w])")
NON_ARTICLE_PATHS = {
    "src/code_of_conduct.md", "src/contrib.md", "src/navigation.md", "src/preview.md", "src/tags.md",
}


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _phrase_re(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


_PHRASES: list[tuple[re.Pattern[str], str, int]] = sorted(
    (
        (_phrase_re(normalize(phrase)), tag, len(phrase))
        for tag, synonyms in TAG_SYNONYMS.items()
        for phrase in (tag, *synonyms)
    ),
    key=lambda item: -item[2],
)


def resolve_tags(text: str) -> list[str]:
    """Map free text (pt/en) to catalog tags; longer phrases win over their substrings."""
    remaining = " " + normalize(text) + " "
    found: set[str] = set()
    for pattern, tag, _ in _PHRASES:
        if pattern.search(remaining):
            found.add(tag)
            remaining = pattern.sub(" ", remaining)
    return sorted(found)


def strip_code(text: str) -> str:
    return re.sub(r"```.*?(?:```|$)", " ", text, flags=re.S)


def band_of(rating: int) -> str:
    for band in BAND_ORDER:
        low, high = BANDS[band]
        if low <= rating <= high:
            return band
    return "veteran" if rating > MAX_RATING else "easy"


def _quantity(token: str | None, vague_default: int) -> int | None:
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token in NUMBER_WORDS:
        return NUMBER_WORDS[token]
    return vague_default


def _rating_range(text: str) -> tuple[int, int] | None:
    match = RANGE_RE.search(text)
    if match:
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        if MIN_RATING <= low <= MAX_RATING and MIN_RATING <= high <= MAX_RATING:
            return low, high
    single = SINGLE_RATING_RE.search(text)
    if single and MIN_RATING <= int(single.group(1)) <= MAX_RATING:
        return int(single.group(1)), int(single.group(1))
    veteran_rating = VETERAN_RATING_RE.search(text)
    if veteran_rating:
        return int(veteran_rating.group(0).rstrip("+ ").strip()), MAX_RATING
    return None


def _spread(total: int, bands: tuple[str, ...]) -> list[dict[str, Any]]:
    per_band, extra = divmod(total, len(bands))
    return [
        {"band": band, "range": list(BANDS[band]), "count": per_band + (1 if position < extra else 0)}
        for position, band in enumerate(bands)
    ]


def parse_problem_request(text: str, default_range: str = "", mode: str = "LEARNING") -> dict[str, Any]:
    """Read requested bands, rating range, and counts from free text.

    Unspecified quantities default to DEFAULT_PER_BAND per band, every band is capped at
    MAX_PER_BAND, and the veteran band (2100+) is only available in Problem Setter.
    `explicit` is true only when the turn actually asks for problems.
    """
    learning = mode != "PROBLEM_SETTER"
    default_count = DEFAULT_PER_BAND["LEARNING" if learning else "PROBLEM_SETTER"]
    allowed_bands = LEARNING_BANDS if learning else SETTER_BANDS
    norm = normalize(strip_code(text))
    general = GENERAL_COUNT_RE.search(norm)
    general_token = (general.group(1) or general.group(2)) if general else None
    general_count = _quantity(general_token, default_count) if general else None
    general_is_vague = bool(general_token) and general_token in VAGUE_WORDS

    prompt_range = _rating_range(norm)
    rating_range = prompt_range or _rating_range(normalize(default_range or ""))

    found: list[tuple[int, str, int | None]] = []
    has_plural_noun = bool(re.search(r"\b" + PLURAL_NOUN_RE + r"\b", norm))
    for band, words in BAND_WORDS.items():
        pattern = (
            r"(?:\b" + QUANTITY_RE + r"\s+)?(?:" + PROBLEM_NOUN_RE + r"\s+)?(?:mais\s+)?\b(" + words + r")\b"
        )
        for match in re.finditer(pattern, norm):
            plural_band = match.group(2) in PLURAL_BAND_WORDS
            level_band = bool(re.search(r"\b(?:nivel|faixa)\s+$", norm[: match.start(2)]))
            if match.group(1) or (plural_band and has_plural_noun) or level_band:
                found.append((match.start(), band, _quantity(match.group(1), default_count)))
                break
    found.sort()

    veteran_blocked = False
    if found:
        bands = []
        previous = general_count
        for _, band, count in found:
            resolved = count or previous or default_count
            previous = resolved
            bands.append({"band": band, "range": list(BANDS[band]), "count": resolved})
        bands.sort(key=lambda item: BAND_ORDER.index(item["band"]))
    elif rating_range:
        low, high = rating_range
        bands = [{"band": "requested_range", "range": [low, high], "count": general_count or default_count}]
    elif general_count and not general_is_vague:
        bands = _spread(general_count, allowed_bands)
    else:
        bands = [{"band": band, "range": list(BANDS[band]), "count": default_count} for band in allowed_bands]

    if learning:
        kept = []
        for item in bands:
            low, high = item["range"]
            if item["band"] == "veteran" or low > LEARNING_MAX_RATING:
                veteran_blocked = True
                continue
            if high > LEARNING_MAX_RATING:
                veteran_blocked = True
                item["range"] = [low, LEARNING_MAX_RATING]
            kept.append(item)
        bands = kept

    requested_total = sum(item["count"] for item in bands)
    capped = any(item["count"] > MAX_PER_BAND for item in bands)
    for item in bands:
        item["requested"] = item["count"]
        item["count"] = min(item["count"], MAX_PER_BAND)
    return {
        "explicit": bool(found or general or prompt_range or REQUEST_VERB_RE.search(norm)),
        "bands": [item for item in bands if item["count"] > 0],
        "requested_total": requested_total,
        "capped": capped,
        "veteran_blocked": veteran_blocked,
        "mode": "LEARNING" if learning else "PROBLEM_SETTER",
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_catalog(data_root: Path | None = None) -> dict[str, Any] | None:
    return _read_json((data_root or config.DATA_ROOT) / CATALOG_FILE)


def load_article_index(data_root: Path | None = None) -> dict[str, Any] | None:
    return _read_json((data_root or config.DATA_ROOT) / ARTICLE_INDEX_FILE)


def _pool(catalog: dict[str, Any], tags: list[str], low: int, high: int, mode: str = "all") -> set[str]:
    pools = []
    for tag in tags:
        by_rating = catalog.get("index", {}).get(tag, {})
        pools.append({pid for rating, ids in by_rating.items() if low <= int(rating) <= high for pid in ids})
    if not pools:
        return set()
    return set.intersection(*pools) if mode == "all" else set.union(*pools)


def _most_solved(catalog: dict[str, Any], ids: set[str]) -> list[str]:
    problems = catalog.get("problems", {})
    return sorted(ids, key=lambda pid: (-(problems[pid].get("solved_count") or 0), pid))


def sample_problems(
    catalog: dict[str, Any],
    tags: list[str],
    request: dict[str, Any],
    exclude: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pick the most-solved unseen problems per band.

    A band is filled from problems with every tag in range, then from ratings widened by
    ±100/±200, then from problems with only some of the tags. Learning never goes above
    LEARNING_MAX_RATING (veteran problems are Problem Setter references only).
    """
    if not tags:
        return [], {"status": "needs_topic", "tags": [], "bands": [], "veteran_blocked": False}
    learning = request.get("mode", "LEARNING") != "PROBLEM_SETTER"
    ceiling = LEARNING_MAX_RATING if learning else MAX_RATING
    excluded = set(exclude or ())
    shown_before = set(exclude or ())
    problems = catalog.get("problems", {})
    chosen: list[dict[str, Any]] = []
    band_reports = []
    for item in request.get("bands", []):
        low, high = item["range"]
        count = item["count"]
        attempts = [("exact", "all", low, high)]
        attempts += [
            (f"widened_{step}", "all", max(MIN_RATING, low - step), min(ceiling, high + step))
            for step in NEIGHBOR_STEPS
        ]
        if len(tags) > 1:
            attempts.append(("partial_tags", "any", low, high))
        picked: list[tuple[str, str]] = []
        taken: set[str] = set()
        candidates_ever: set[str] = set()
        for strategy, mode, lo, hi in attempts:
            pool = _pool(catalog, tags, lo, hi, mode)
            candidates_ever |= pool
            for pid in _most_solved(catalog, pool - excluded - taken):
                if len(picked) >= count:
                    break
                picked.append((pid, strategy))
                taken.add(pid)
            if len(picked) >= count:
                break
        records = []
        for pid, strategy in picked:
            problem = problems[pid]
            records.append(
                {
                    **problem,
                    "id": pid,
                    "band": item["band"],
                    "rating_band": band_of(problem["rating"]),
                    "matched_tags": [tag for tag in tags if tag in problem.get("tags", [])],
                    "selection": strategy,
                    "outside_requested_range": not (low <= problem["rating"] <= high),
                    "catalog_match": True,
                }
            )
        excluded |= taken
        chosen.extend(records)
        strategies = list(dict.fromkeys(record["selection"] for record in records))
        band_reports.append(
            {
                "band": item["band"],
                "range": [low, high],
                "requested": item.get("requested", count),
                "delivered": len(records),
                "strategy": strategies[-1] if strategies else "empty",
                "strategies": strategies,
                "exhausted": len(records) < count and bool(candidates_ever & shown_before),
            }
        )
    delivered = sum(report["delivered"] for report in band_reports)
    target = sum(item["count"] for item in request.get("bands", []))
    exhausted = any(report["exhausted"] for report in band_reports)
    if delivered == target and target:
        status = "ok"
    elif delivered:
        status = "partial"
    elif exhausted:
        status = "exhausted"
    elif request.get("veteran_blocked") and not request.get("bands"):
        status = "veteran_blocked"
    else:
        status = "empty"
    return chosen, {
        "status": status,
        "tags": tags,
        "bands": band_reports,
        "requested_total": request.get("requested_total", target),
        "capped": bool(request.get("capped")),
        "max_per_band": MAX_PER_BAND,
        "veteran_blocked": bool(request.get("veteran_blocked")),
        "exhausted": exhausted,
    }


def select_article_paths(index: dict[str, Any], tags: list[str], limit: int = 3) -> list[str]:
    known = {
        article.get("path")
        for article in index.get("articles", [])
        if article.get("path") not in NON_ARTICLE_PATHS
    }
    per_tag: list[list[str]] = []
    for tag in tags:
        preferred = [path for path in TAG_ARTICLES.get(tag, ()) if path in known]
        if not preferred:
            words = set(normalize(tag).split())
            preferred = sorted(
                path for path in known if words and words <= set(normalize(Path(path).stem).replace("_", "-").split("-"))
            )
        per_tag.append(preferred)
    selected: list[str] = []
    depth = 0
    while len(selected) < limit and any(len(paths) > depth for paths in per_tag):
        for paths in per_tag:
            if len(paths) > depth and paths[depth] not in selected and len(selected) < limit:
                selected.append(paths[depth])
        depth += 1
    return selected


def find_problem_refs(text: str, catalog: dict[str, Any] | None) -> list[str]:
    """Codeforces problem ids (e.g. 1950D) or links mentioned in text that exist in the catalog."""
    if catalog is None:
        return []
    problems = catalog.get("problems", {})
    found = [f"{c}{i.upper()}" for c, i in CODEFORCES_PROBLEM_URL_RE.findall(text)]
    found += [f"{c}{i}" for c, i in PROBLEM_ID_RE.findall(strip_code(text))]
    return [pid for pid in dict.fromkeys(found) if pid in problems]


def _title_key(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", normalize(text)).strip() + " "


def _title_line(text: str) -> str:
    match = re.search(r"(?:t[ií]tulo|title)\s*:\s*([^\n]+)", text, re.I)
    if match:
        return match.group(1)
    body = re.split(r"(?:problem\s*statement|statement|enunciado)\s*:\s*", text, maxsplit=1, flags=re.I)[-1]
    return re.split(r"[.\n:]", body.strip(), maxsplit=1)[0]


def find_similar_problems(text: str, catalog: dict[str, Any] | None) -> dict[str, Any]:
    """Published problems matching a statement: identical (exact title or link) or similar title.

    These are signals for a neutral notice, not a plagiarism verdict.
    """
    report: dict[str, Any] = {"catalog_available": catalog is not None, "matches": []}
    if catalog is None:
        return report
    problems = catalog.get("problems", {})
    seen: set[str] = set()
    for contest_id, index in CODEFORCES_PROBLEM_URL_RE.findall(text):
        pid = f"{contest_id}{index.upper()}"
        if pid in problems and pid not in seen:
            seen.add(pid)
            report["matches"].append({"relation": "identical", "evidence": "codeforces_url", "problem_id": pid, **match_fields(problems[pid])})
    haystack = _title_key(text)
    title_tokens = set(_title_key(_title_line(text)).split())
    for pid, problem in problems.items():
        if pid in seen:
            continue
        key = _title_key(str(problem.get("title", "")))
        tokens = key.split()
        if len(key.strip()) >= MIN_TITLE_MATCH_CHARS and len(tokens) >= 2 and key in haystack:
            seen.add(pid)
            report["matches"].append({"relation": "identical", "evidence": "title", "problem_id": pid, **match_fields(problem)})
            continue
        if len(tokens) >= 2 and len(title_tokens) >= 2:
            overlap = len(set(tokens) & title_tokens) / len(set(tokens) | title_tokens)
            if overlap >= SIMILAR_TITLE_THRESHOLD:
                seen.add(pid)
                report["matches"].append({"relation": "similar", "evidence": "title", "problem_id": pid, **match_fields(problem)})
    report["matches"].sort(key=lambda match: (match["relation"] != "identical", match["problem_id"]))
    return report


def match_fields(problem: dict[str, Any]) -> dict[str, Any]:
    return {"title": problem.get("title"), "rating": problem.get("rating"), "url": problem.get("url")}