"""Live smoke tests for cp_framework.services.sources (hit Codeforces and GitHub).

Run with:  CP_LIVE_TESTS=1 python -m unittest tests.test_sources_live -v
Set GITHUB_TOKEN to avoid GitHub's unauthenticated rate limit (60 req/h).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cp_framework.services import sources

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIVE = os.environ.get("CP_LIVE_TESTS", "").strip().lower() in {"1", "true", "yes"}


@unittest.skipUnless(LIVE, "defina CP_LIVE_TESTS=1 para rodar testes contra as APIs reais")
class SourcesLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.data_root = Path(cls._tmp.name)
        cls._patch = mock.patch.object(sources, "DATA_ROOT", cls.data_root)
        cls._patch.start()
        cls.sync_result = sources.handle({"action": "sync"})
        cls.codeforces = json.loads(
            (cls.data_root / "codeforces_problems.json").read_text(encoding="utf-8")
        )
        cls.index = json.loads(
            (cls.data_root / "cp_algorithms_index.json").read_text(encoding="utf-8")
        )
        cls.catalog = json.loads(
            (cls.data_root / "codeforces_catalog.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._patch.stop()
        cls._tmp.cleanup()

    def test_sync_reports_snapshots_and_counts(self) -> None:
        result = self.sync_result
        self.assertEqual(result["status"], "ok")
        for path in result["snapshots"].values():
            self.assertTrue(Path(path).is_file(), path)
            self.assertEqual(Path(path).parent, self.data_root)
        self.assertEqual(result["counts"]["codeforces_problems"], self.codeforces["record_count"])
        self.assertEqual(result["counts"]["cp_algorithms_articles"], self.index["record_count"])
        self.assertEqual(
            result["counts"]["codeforces_catalog_problems"], self.catalog["problem_count"]
        )
        self.assertEqual(list(self.data_root.glob("*.tmp")), [])

    def test_codeforces_catalog_index(self) -> None:
        catalog, problems = self.catalog, self.catalog["problems"]
        self.assertGreater(catalog["problem_count"], 10000)
        self.assertGreater(catalog["skipped"]["without_tags"], 0)
        self.assertNotIn("*special", catalog["index"])
        self.assertGreater(len(catalog["index"]["dp"]["1500"]), 10)
        entries = 0
        for tag, by_rating in catalog["index"].items():
            for rating, ids in by_rating.items():
                entries += len(ids)
                for pid in ids:
                    self.assertIn(tag, problems[pid]["tags"])
                    self.assertEqual(problems[pid]["rating"], int(rating))
        self.assertEqual(entries, sum(len(p["tags"]) for p in problems.values()))

    def test_codeforces_snapshot_shape(self) -> None:
        problems = self.codeforces["problems"]
        self.assertEqual(self.codeforces["source_url"], sources.CODEFORCES_URL)
        self.assertEqual(self.codeforces["record_count"], len(problems))
        self.assertGreater(len(problems), 5000)
        for problem in problems:
            self.assertEqual(problem["id"], f"{problem['contest_id']}{problem['index']}")
            self.assertTrue(problem["title"])
            self.assertIsInstance(problem["tags"], list)
            self.assertTrue(
                problem["url"].startswith("https://codeforces.com/problemset/problem/")
            )
        self.assertGreater(sum(p["rating"] is not None for p in problems), len(problems) // 2)
        self.assertGreater(sum(p["solved_count"] is not None for p in problems), len(problems) // 2)

    def test_cp_algorithms_index_shape(self) -> None:
        articles = self.index["articles"]
        self.assertTrue(self.index["branch"])
        self.assertEqual(self.index["record_count"], len(articles))
        self.assertGreater(len(articles), 100)
        paths = [a["path"] for a in articles]
        self.assertEqual(len(paths), len(set(paths)))
        for article in articles:
            path = article["path"]
            self.assertTrue(path.startswith("src/") and path.endswith(".md"), path)
            self.assertFalse(path.lower().endswith(("/readme.md", "/index.md")), path)
            self.assertRegex(article["sha"], re.compile(r"^[0-9a-f]{40}$"))
            self.assertIn(f"/blob/{self.index['branch']}/{path}", article["url"])

    def test_fetch_articles_downloads_markdown_and_merges(self) -> None:
        paths = [a["path"] for a in self.index["articles"]]
        preferred = [p for p in paths if "binary_search" in p] or paths
        first, second = preferred[0], next(p for p in paths if p != preferred[0])

        result = sources.handle({"action": "fetch_articles", "paths": [first, first]})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 1)

        result = sources.handle({"action": "fetch_articles", "paths": [second]})
        self.assertEqual(result["count"], 2)
        snapshot = json.loads(Path(result["snapshot"]).read_text(encoding="utf-8"))
        by_path = {a["path"]: a for a in snapshot["articles"]}
        self.assertEqual(set(by_path), {first, second})
        for article in by_path.values():
            markdown = article["content_markdown"]
            self.assertGreater(len(markdown), 200)
            self.assertIn("#", markdown)

    def test_fetch_articles_rejects_unknown_or_too_many_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "fora do índice"):
            sources.fetch_article_content(["src/../README.md"])
        with self.assertRaisesRegex(ValueError, "no máximo 8"):
            sources.fetch_article_content([f"src/{i}.md" for i in range(9)])
        with self.assertRaises(ValueError):
            sources.handle({"action": "fetch_articles", "paths": "src/x.md"})

    def test_fetch_api_surfaces_http_errors(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"HTTP 404"):
            sources.fetch_json(f"{sources.GITHUB_API_ROOT}/contents/does-not-exist-cp-test.md")

    def test_cli_returns_json_error_for_invalid_action(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "cp_framework.services.sources"],
            input='{"action": "nope"}',
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "CP_DATA_DIR": str(self.data_root)},
            timeout=60,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        response = json.loads(completed.stdout.splitlines()[0])
        self.assertEqual(response["status"], "error")
        self.assertIn("sync ou fetch_articles", response["error"])


if __name__ == "__main__":
    unittest.main()
