"""Sources service: fetch public APIs and persist source snapshots as JSON only."""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ..config import DATA_ROOT, HTTP_TIMEOUT_SECONDS
from ..io import run_cli


CODEFORCES_URL = "https://codeforces.com/api/problemset.problems"
GITHUB_REPO_URL = "https://api.github.com/repos/cp-algorithms/cp-algorithms"
GITHUB_API_ROOT = "https://api.github.com/repos/cp-algorithms/cp-algorithms"
MAX_RESPONSE_BYTES = 45_000_000
CODEFORCES_MIN_INTERVAL_SECONDS = 2.0
CODEFORCES_RATE_STAMP = ".codeforces_last_request"
EXCLUDED_CATALOG_TAGS = {"*special"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wait_codeforces_slot() -> None:
    """Codeforces allows 1 request / 2 s; the stamp file spans service processes."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = DATA_ROOT / CODEFORCES_RATE_STAMP
    try:
        last = float(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0.0
    delay = last + CODEFORCES_MIN_INTERVAL_SECONDS - time.time()
    if delay > 0:
        time.sleep(min(delay, CODEFORCES_MIN_INTERVAL_SECONDS))
    stamp.write_text(repr(time.time()), encoding="utf-8")


def fetch_api(url: str, accept: str = "application/json") -> tuple[bytes, dict[str, str]]:
    host = urlparse(url).hostname or ""
    if host == "codeforces.com" or host.endswith(".codeforces.com"):
        wait_codeforces_slot()
    headers = {
        "Accept": accept,
        "User-Agent": "competitive-programming-learning-framework/0.1",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as exc:
        detail = exc.read(4000).decode("utf-8", errors="replace")
        exc.close()
        raise RuntimeError(f"HTTP {exc.code} em {url}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Falha ao consultar {url}: {exc}") from exc
    if len(content) > MAX_RESPONSE_BYTES:
        raise RuntimeError(f"Resposta acima do limite de {MAX_RESPONSE_BYTES} bytes: {url}")
    return content, response_headers


def fetch_json(url: str) -> dict[str, Any]:
    raw, _ = fetch_api(url)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError(f"Resposta inesperada da API: {url}")
    return value


def write_snapshot(name: str, value: dict[str, Any]) -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    target = DATA_ROOT / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def sync_codeforces() -> dict[str, Any]:
    payload = fetch_json(CODEFORCES_URL)
    if payload.get("status") != "OK":
        raise RuntimeError(f"Codeforces API não retornou status OK: {payload.get('comment', '')}")
    result = payload.get("result", {})
    problems = result.get("problems", [])
    statistics = result.get("problemStatistics", [])
    solved_counts = {
        (item.get("contestId"), item.get("index")): item.get("solvedCount")
        for item in statistics
    }
    records = []
    for problem in problems:
        contest_id = problem.get("contestId")
        index = problem.get("index")
        records.append(
            {
                "id": f"{contest_id}{index}",
                "contest_id": contest_id,
                "index": index,
                "title": problem.get("name", ""),
                "rating": problem.get("rating"),
                "tags": problem.get("tags", []),
                "solved_count": solved_counts.get((contest_id, index)),
                "url": f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
            }
        )
    return {
        "source": "Codeforces Problemset API",
        "source_url": CODEFORCES_URL,
        "fetched_at": utc_now(),
        "record_count": len(records),
        "problems": records,
    }


def build_codeforces_catalog(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Index problems by tag -> rating -> ids; problems are stored once by id."""
    problems: dict[str, dict[str, Any]] = {}
    index: dict[str, dict[str, list[str]]] = {}
    skipped = {"without_tags": 0, "without_rating": 0}
    for record in snapshot.get("problems", []):
        tags = sorted(
            {tag for tag in record.get("tags") or [] if tag not in EXCLUDED_CATALOG_TAGS}
        )
        rating = record.get("rating")
        if not tags:
            skipped["without_tags"] += 1
            continue
        if not isinstance(rating, int):
            skipped["without_rating"] += 1
            continue
        problem_id = record["id"]
        problems[problem_id] = {
            "contest_id": record.get("contest_id"),
            "index": record.get("index"),
            "title": record.get("title", ""),
            "rating": rating,
            "tags": tags,
            "solved_count": record.get("solved_count"),
            "url": record.get("url"),
        }
        for tag in tags:
            index.setdefault(tag, {}).setdefault(str(rating), []).append(problem_id)
    for by_rating in index.values():
        for ids in by_rating.values():
            ids.sort(key=lambda pid: problems[pid]["solved_count"] or 0, reverse=True)
    sorted_index = {
        tag: dict(sorted(by_rating.items(), key=lambda item: int(item[0])))
        for tag, by_rating in sorted(index.items())
    }
    return {
        "source": snapshot.get("source"),
        "source_url": snapshot.get("source_url"),
        "fetched_at": snapshot.get("fetched_at"),
        "built_at": utc_now(),
        "problem_count": len(problems),
        "skipped": skipped,
        "excluded_tags": sorted(EXCLUDED_CATALOG_TAGS),
        "tag_count": len(sorted_index),
        "bucket_count": sum(len(by_rating) for by_rating in sorted_index.values()),
        "index": sorted_index,
        "problems": problems,
    }


def sync_cp_algorithms_index() -> dict[str, Any]:
    repo = fetch_json(GITHUB_REPO_URL)
    branch = repo.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise RuntimeError("GitHub não informou o default branch do repositório.")
    tree = fetch_json(f"{GITHUB_API_ROOT}/git/trees/{quote(branch, safe='')}?recursive=1")
    entries = tree.get("tree", [])
    articles = []
    for entry in entries:
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.startswith("src/") or not path.endswith(".md"):
            continue
        if path.lower().endswith(("/readme.md", "/index.md")):
            continue
        slug = Path(path).stem.replace("_", " ").replace("-", " ")
        articles.append(
            {
                "id": path,
                "path": path,
                "title": slug,
                "sha": entry.get("sha"),
                "size": entry.get("size"),
                "url": f"https://github.com/cp-algorithms/cp-algorithms/blob/{branch}/{path}",
            }
        )
    return {
        "source": "GitHub API: cp-algorithms/cp-algorithms",
        "repository_url": GITHUB_REPO_URL,
        "branch": branch,
        "fetched_at": utc_now(),
        "record_count": len(articles),
        "articles": articles,
    }


def fetch_article_content(paths: list[str]) -> dict[str, Any]:
    if not paths:
        raise ValueError("Informe paths de artigos para baixar.")
    if len(paths) > 8:
        raise ValueError("Baixe no máximo 8 artigos por chamada.")
    index_path = DATA_ROOT / "cp_algorithms_index.json"
    if not index_path.is_file():
        raise FileNotFoundError("Execute a sincronização das fontes antes de buscar artigos.")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    known = {item["path"]: item for item in index.get("articles", [])}
    existing_snapshot_path = DATA_ROOT / "cp_algorithms_articles.json"
    existing_snapshot: dict[str, Any] = {}
    if existing_snapshot_path.is_file():
        try:
            existing_snapshot = json.loads(existing_snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_snapshot = {}
    articles_by_path = {
        item.get("path"): item
        for item in existing_snapshot.get("articles", [])
        if isinstance(item, dict) and item.get("path")
    }
    for path in dict.fromkeys(paths):
        if path not in known or not path.startswith("src/") or ".." in Path(path).parts:
            raise ValueError(f"Artigo fora do índice cp-algorithms: {path}")
        safe_path = quote(path, safe="/")
        url = f"{GITHUB_API_ROOT}/contents/{safe_path}?ref={quote(index['branch'], safe='')}"
        raw, headers = fetch_api(url, accept="application/vnd.github.raw+json")
        if "application/json" in headers.get("content-type", ""):
            content_payload = json.loads(raw)
            encoded = content_payload.get("content", "")
            markdown = base64.b64decode(encoded).decode("utf-8")
        else:
            markdown = raw.decode("utf-8")
        articles_by_path[path] = {
            **known[path],
            "fetched_at": utc_now(),
            "content_markdown": markdown,
        }
    articles = list(articles_by_path.values())
    snapshot = {
        "source": "GitHub Contents API: cp-algorithms/cp-algorithms",
        "repository_url": GITHUB_REPO_URL,
        "branch": index["branch"],
        "fetched_at": utc_now(),
        "record_count": len(articles),
        "articles": articles,
    }
    return snapshot


def handle(request: dict[str, Any]) -> dict[str, Any]:
    action = request.get("action")
    if action == "sync":
        codeforces = sync_codeforces()
        catalog = build_codeforces_catalog(codeforces)
        article_index = sync_cp_algorithms_index()
        cf_path = write_snapshot("codeforces_problems.json", codeforces)
        catalog_path = write_snapshot("codeforces_catalog.json", catalog)
        index_path = write_snapshot("cp_algorithms_index.json", article_index)
        return {
            "status": "ok",
            "snapshots": {
                "codeforces": str(cf_path),
                "codeforces_catalog": str(catalog_path),
                "cp_algorithms_index": str(index_path),
            },
            "counts": {
                "codeforces_problems": codeforces["record_count"],
                "codeforces_catalog_problems": catalog["problem_count"],
                "codeforces_catalog_buckets": catalog["bucket_count"],
                "cp_algorithms_articles": article_index["record_count"],
            },
        }
    if action == "fetch_articles":
        paths = request.get("paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ValueError("paths precisa ser uma lista de caminhos de artigo.")
        snapshot = fetch_article_content(paths)
        target = write_snapshot("cp_algorithms_articles.json", snapshot)
        return {"status": "ok", "snapshot": str(target), "count": snapshot["record_count"]}
    raise ValueError("action válida: sync ou fetch_articles.")


if __name__ == "__main__":
    run_cli(handle)

