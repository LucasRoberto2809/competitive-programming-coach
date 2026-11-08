from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cp_framework.services import sources


def _record(contest_id, index, rating, tags, solved=0):
    return {
        "id": f"{contest_id}{index}",
        "contest_id": contest_id,
        "index": index,
        "title": f"P{contest_id}{index}",
        "rating": rating,
        "tags": tags,
        "solved_count": solved,
        "url": f"https://codeforces.com/problemset/problem/{contest_id}/{index}",
    }


class BuildCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = sources.build_codeforces_catalog(
            {
                "source": "test",
                "problems": [
                    _record(1, "A", 800, ["math", "greedy"], solved=10),
                    _record(2, "B", 800, ["math"], solved=99),
                    _record(3, "C", 1500, ["dp"], solved=5),
                    _record(4, "D", 1200, [], solved=1),
                    _record(5, "E", None, ["dp"], solved=1),
                    _record(6, "F", 1000, ["*special"], solved=1),
                    _record(7, "G", 1000, ["*special", "math"], solved=1),
                ],
            }
        )

    def test_index_maps_tag_and_rating_to_ids_sorted_by_solved(self) -> None:
        index = self.catalog["index"]
        self.assertEqual(index["math"]["800"], ["2B", "1A"])
        self.assertEqual(index["greedy"]["800"], ["1A"])
        self.assertEqual(index["dp"], {"1500": ["3C"]})
        self.assertEqual(list(index["math"]), ["800", "1000"])
        self.assertEqual(list(index), sorted(index))

    def test_problems_stored_once_and_every_index_id_resolves(self) -> None:
        problems = self.catalog["problems"]
        self.assertEqual(set(problems), {"1A", "2B", "3C", "7G"})
        self.assertEqual(problems["7G"]["tags"], ["math"])
        for by_rating in self.catalog["index"].values():
            for rating, ids in by_rating.items():
                for pid in ids:
                    self.assertEqual(problems[pid]["rating"], int(rating))

    def test_skips_untagged_unrated_and_special_only(self) -> None:
        self.assertEqual(self.catalog["skipped"], {"without_tags": 2, "without_rating": 1})
        self.assertNotIn("*special", self.catalog["index"])
        self.assertEqual(self.catalog["problem_count"], 4)
        self.assertEqual(self.catalog["tag_count"], 3)
        self.assertEqual(self.catalog["bucket_count"], 4)


class CodeforcesRateLimitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(sources, "DATA_ROOT", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_waits_remaining_interval_after_recent_request(self) -> None:
        with mock.patch.object(sources.time, "time", return_value=1000.0), mock.patch.object(
            sources.time, "sleep"
        ) as sleep:
            sources.wait_codeforces_slot()
            sleep.assert_not_called()
        with mock.patch.object(sources.time, "time", return_value=1000.5), mock.patch.object(
            sources.time, "sleep"
        ) as sleep:
            sources.wait_codeforces_slot()
            sleep.assert_called_once()
            self.assertAlmostEqual(sleep.call_args.args[0], 1.5)

    def test_no_wait_after_interval_elapsed(self) -> None:
        with mock.patch.object(sources.time, "time", return_value=1000.0):
            sources.wait_codeforces_slot()
        with mock.patch.object(sources.time, "time", return_value=1002.0), mock.patch.object(
            sources.time, "sleep"
        ) as sleep:
            sources.wait_codeforces_slot()
            sleep.assert_not_called()

    def test_only_codeforces_hosts_are_throttled(self) -> None:
        class _Response:
            headers: dict[str, str] = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, _size):
                return b"{}"

        with mock.patch.object(sources, "urlopen", return_value=_Response()), mock.patch.object(
            sources, "wait_codeforces_slot"
        ) as wait:
            sources.fetch_api("https://api.github.com/repos/x/y")
            wait.assert_not_called()
            sources.fetch_api(sources.CODEFORCES_URL)
            wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
