from __future__ import annotations

import unittest

from cp_framework import catalog as c
from tests import fixtures

REAL_CATALOG = c.load_catalog()


class ResolveTagsTest(unittest.TestCase):
    def test_portuguese_english_and_accent_variants(self) -> None:
        cases = {
            "quero aprender programação dinâmica": ["dp"],
            "programacao dinamica": ["dp"],
            "Dynamic Programming": ["dp"],
            "DP": ["dp"],
            "busca binária": ["binary search"],
            "binary search": ["binary search"],
            "grafos": ["graphs"],
            "BFS e DFS": ["dfs and similar"],
            "árvore de segmentos": ["data structures"],
            "segment tree": ["data structures"],
            "teoria dos números": ["number theory"],
            "Dijkstra": ["shortest paths"],
            "caminho mínimo": ["shortest paths"],
            "guloso": ["greedy"],
            "força bruta": ["brute force"],
            "union-find": ["dsu"],
            "string hashing": ["hashing"],
            "suffix array": ["string suffix structures"],
            "2-SAT": ["2-sat"],
            "meet in the middle": ["meet-in-the-middle"],
            "teorema chinês do resto": ["chinese remainder theorem"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(c.resolve_tags(text), expected)

    def test_topic_combinations(self) -> None:
        cases = {
            "dp e busca binária": ["binary search", "dp"],
            "quero misturar grafos, árvores e programação dinâmica": ["dp", "graphs", "trees"],
            "binary search + greedy": ["binary search", "greedy"],
            "hashing com strings": ["hashing", "strings"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(c.resolve_tags(text), expected)

    def test_longer_phrase_wins_over_substring(self) -> None:
        self.assertEqual(c.resolve_tags("árvore de segmentos"), ["data structures"])
        self.assertEqual(c.resolve_tags("string hashing"), ["hashing"])
        self.assertEqual(c.resolve_tags("teoria dos jogos"), ["games"])

    def test_no_false_positives_inside_words_or_unrelated_text(self) -> None:
        for text in [
            "quero aprender redes neurais",
            "deu overflow no meu código",
            "o fluxo do programa está estranho",
            "uso hashmap no código",
            "minha estrutura do código está confusa",
            "tenho um problema",
            "",
        ]:
            with self.subTest(text=text):
                self.assertEqual(c.resolve_tags(text), [])

    @unittest.skipIf(REAL_CATALOG is None, "catálogo real ausente; rode o sync")
    def test_synonyms_cover_exactly_the_real_catalog_tags(self) -> None:
        self.assertEqual(set(c.TAG_SYNONYMS), set(REAL_CATALOG["index"]))


class ParseProblemRequestTest(unittest.TestCase):
    def bands(self, text: str, default: str = "", mode: str = "LEARNING") -> list[tuple[str, int]]:
        return [(b["band"], b["count"]) for b in c.parse_problem_request(text, default, mode)["bands"]]

    def test_default_is_two_per_learning_band(self) -> None:
        request = c.parse_problem_request("quero aprender dp")
        self.assertFalse(request["explicit"])
        self.assertEqual(self.bands("quero aprender dp"), [("easy", 2), ("medium", 2), ("hard", 2)])

    def test_setter_default_includes_veteran_references(self) -> None:
        self.assertEqual(
            self.bands("quero criar meu problema", mode="PROBLEM_SETTER"),
            [("easy", 1), ("medium", 1), ("hard", 1), ("veteran", 1)],
        )

    def test_counts_per_band(self) -> None:
        cases = {
            "me dá 2 problemas fáceis e 3 médios de grafos": [("easy", 2), ("medium", 3)],
            "2 problemas fáceis, 2 médios e 2 difíceis": [("easy", 2), ("medium", 2), ("hard", 2)],
            "quero dois problemas fáceis": [("easy", 2)],
            "um problema difícil": [("hard", 1)],
            "problemas de nível médio": [("medium", 2)],
            "3 médios e 1 fácil": [("easy", 1), ("medium", 3)],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.bands(text), expected)
                self.assertTrue(c.parse_problem_request(text)["explicit"])

    def test_vague_quantities_default_to_two_and_propagate(self) -> None:
        self.assertEqual(self.bands("quero vários problemas fáceis e médios"), [("easy", 2), ("medium", 2)])
        self.assertEqual(self.bands("diversos problemas difíceis"), [("hard", 2)])
        self.assertEqual(self.bands("3 problemas fáceis e médios"), [("easy", 3), ("medium", 3)])

    def test_more_than_three_per_band_is_refused_down_to_three(self) -> None:
        request = c.parse_problem_request("quero 50 problemas fáceis")
        self.assertTrue(request["capped"])
        self.assertEqual(request["requested_total"], 50)
        self.assertEqual(request["bands"][0]["requested"], 50)
        self.assertEqual(self.bands("quero 50 problemas fáceis"), [("easy", c.MAX_PER_BAND)])
        self.assertEqual(self.bands("5 problemas fáceis e 3 médios"), [("easy", 3), ("medium", 3)])
        self.assertTrue(c.parse_problem_request("5 problemas fáceis e 3 médios")["capped"])
        self.assertFalse(c.parse_problem_request("3 problemas fáceis")["capped"])

    def test_total_without_band_is_spread_and_capped(self) -> None:
        self.assertEqual(self.bands("me dá 5 problemas de dp"), [("easy", 2), ("medium", 2), ("hard", 1)])
        self.assertEqual(self.bands("me dá 12 problemas de dp"), [("easy", 3), ("medium", 3), ("hard", 3)])
        self.assertTrue(c.parse_problem_request("me dá 12 problemas de dp")["capped"])
        self.assertEqual(self.bands("mais problemas"), [("easy", 2), ("medium", 2), ("hard", 2)])
        self.assertTrue(c.parse_problem_request("mais problemas")["explicit"])

    def test_rating_ranges(self) -> None:
        request = c.parse_problem_request("2 problemas entre 1200 e 1400")
        self.assertEqual(request["bands"][0]["range"], [1200, 1400])
        self.assertEqual(request["bands"][0]["count"], 2)
        self.assertEqual(c.parse_problem_request("problemas 1600-1400")["bands"][0]["range"], [1400, 1600])
        self.assertEqual(c.parse_problem_request("rating 1500")["bands"][0]["range"], [1500, 1500])
        session_range = c.parse_problem_request("quero aprender dp", default_range="1000-1300")
        self.assertEqual(session_range["bands"][0]["range"], [1000, 1300])
        self.assertFalse(session_range["explicit"])

    def test_veteran_is_blocked_in_learning_and_allowed_in_setter(self) -> None:
        for text in ["quero problemas veteranos de dp", "problemas 2200-2600", "problemas 2100+"]:
            with self.subTest(text=text):
                request = c.parse_problem_request(text)
                self.assertTrue(request["veteran_blocked"])
                self.assertEqual(request["bands"], [])
        clipped = c.parse_problem_request("problemas 1800-2400")
        self.assertTrue(clipped["veteran_blocked"])
        self.assertEqual(clipped["bands"][0]["range"], [1800, c.LEARNING_MAX_RATING])
        setter = c.parse_problem_request("quero problemas veteranos de dp", mode="PROBLEM_SETTER")
        self.assertFalse(setter["veteran_blocked"])
        self.assertEqual([(b["band"], b["range"]) for b in setter["bands"]], [("veteran", [2100, 3500])])

    def test_hard_band_ends_at_2099(self) -> None:
        self.assertEqual(c.BANDS["hard"], (1500, 2099))
        self.assertEqual(c.BANDS["veteran"], (2100, 3500))
        self.assertEqual([c.band_of(r) for r in (800, 999, 1000, 1499, 1500, 2099, 2100, 3500)],
                         ["easy", "easy", "medium", "medium", "hard", "hard", "veteran", "veteran"])

    def test_out_of_scale_numbers_are_not_ranges(self) -> None:
        for text in ["n até 100 a 200", "valores 5000 a 9000", "1 <= n <= 200000"]:
            with self.subTest(text=text):
                self.assertNotEqual(c.parse_problem_request(text)["bands"][0]["band"], "requested_range")

    def test_ordinary_messages_are_not_problem_requests(self) -> None:
        for text in [
            "tenho um problema no código",
            "achei esse problema difícil",
            "não entendi o problema",
            "existe outro jeito de pensar?",
            "a média dos valores estoura",
            "sou iniciante em dp",
            "```cpp\n// 5 problemas fáceis\nint main(){}\n```",
        ]:
            with self.subTest(text=text):
                self.assertFalse(c.parse_problem_request(text)["explicit"])

    def test_request_verbs_make_it_explicit(self) -> None:
        for text in ["me recomenda exercícios de dp", "quero problemas de grafos", "liste problemas de dp"]:
            with self.subTest(text=text):
                self.assertTrue(c.parse_problem_request(text)["explicit"])


class SampleProblemsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = fixtures.build_catalog()

    def sample(self, tags, text, exclude=None, mode="LEARNING"):
        return c.sample_problems(self.catalog, tags, c.parse_problem_request(text, mode=mode), exclude)

    def solved(self, pid: str) -> int:
        return self.catalog["problems"][pid]["solved_count"] or 0

    def test_default_ladder_two_per_band_most_solved_first(self) -> None:
        problems, plan = self.sample(["dp"], "quero aprender dp")
        self.assertEqual(plan["status"], "ok")
        self.assertEqual([p["band"] for p in problems], ["easy", "easy", "medium", "medium", "hard", "hard"])
        for band in c.LEARNING_BANDS:
            low, high = c.BANDS[band]
            ids = [p["id"] for p in problems if p["band"] == band]
            pool = [pid for pid in c._pool(self.catalog, ["dp"], low, high)]
            expected = sorted(pool, key=lambda pid: (-self.solved(pid), pid))[:2]
            self.assertEqual(ids, expected)
        self.assertTrue(all(p["rating"] <= c.LEARNING_MAX_RATING for p in problems))
        self.assertTrue(all(p["catalog_match"] and p["selection"] == "exact" for p in problems))

    def test_learning_never_returns_veteran_problems(self) -> None:
        problems, _ = self.sample(["dp"], "3 problemas difíceis")
        self.assertTrue(problems)
        self.assertTrue(all(p["rating"] <= 2099 for p in problems))
        problems, _ = self.sample(["dp", "trees"], "3 problemas difíceis")
        self.assertTrue(all(p["rating"] <= 2099 for p in problems))

    def test_setter_can_reference_veteran_problems(self) -> None:
        problems, plan = self.sample(["dp"], "quero criar meu problema", mode="PROBLEM_SETTER")
        veteran = [p for p in problems if p["band"] == "veteran"]
        self.assertEqual(len(veteran), 1)
        self.assertGreaterEqual(veteran[0]["rating"], 2100)
        self.assertEqual(veteran[0]["rating_band"], "veteran")

    def test_combination_requires_all_tags_when_available(self) -> None:
        problems, plan = self.sample(["binary search", "dp"], "1 problema médio e 1 difícil")
        self.assertEqual([b["strategy"] for b in plan["bands"]], ["exact", "exact"])
        for problem in problems:
            self.assertEqual(problem["matched_tags"], ["binary search", "dp"])

    def test_short_band_is_filled_by_widening_then_partial_tags(self) -> None:
        problems, plan = self.sample(["binary search", "dp"], "2 problemas fáceis")
        self.assertEqual(len(problems), 2)
        self.assertEqual(plan["bands"][0]["strategies"], ["partial_tags"])
        problems, plan = self.sample(["greedy"], "3 problemas fáceis")
        self.assertEqual(len(problems), 3)
        self.assertEqual([p["selection"] for p in problems], ["exact", "exact", "exact"])

    def test_widened_problems_are_marked_outside_range(self) -> None:
        medium = sorted(c._pool(self.catalog, ["greedy"], 1000, 1499))
        problems, plan = self.sample(["greedy"], "3 problemas médios", exclude=set(medium[1:]))
        self.assertEqual([p["selection"] for p in problems], ["exact", "widened_200", "widened_200"])
        self.assertEqual(plan["bands"][0]["strategies"], ["exact", "widened_200"])
        widened = [p for p in problems if p["selection"] != "exact"]
        self.assertTrue(all(p["outside_requested_range"] and p["rating"] == 800 for p in widened))

    def test_exhausted_bank_is_reported(self) -> None:
        shown: set[str] = set()
        statuses = []
        for _ in range(6):
            problems, plan = self.sample(["games"], "mais problemas", exclude=shown)
            shown |= {p["id"] for p in problems}
            statuses.append(plan["status"])
        self.assertEqual(statuses[-1], "exhausted")
        self.assertTrue(plan["exhausted"])

    def test_impossible_request_is_empty_not_exhausted(self) -> None:
        problems, plan = self.sample(["fft"], "2 problemas fáceis")
        self.assertEqual((problems, plan["status"], plan["exhausted"]), ([], "empty", False))

    def test_veteran_only_request_in_learning(self) -> None:
        problems, plan = self.sample(["dp"], "problemas veteranos")
        self.assertEqual((problems, plan["status"]), ([], "veteran_blocked"))
        self.assertTrue(plan["veteran_blocked"])

    def test_exclusion_avoids_repeats_and_is_deterministic(self) -> None:
        first, _ = self.sample(["dp"], "3 problemas fáceis")
        again, _ = self.sample(["dp"], "3 problemas fáceis")
        self.assertEqual([p["id"] for p in first], [p["id"] for p in again])
        second, _ = self.sample(["dp"], "2 problemas fáceis", exclude={p["id"] for p in first})
        self.assertFalse({p["id"] for p in first} & {p["id"] for p in second})

    def test_no_tags_needs_topic(self) -> None:
        problems, plan = self.sample([], "quero problemas")
        self.assertEqual((problems, plan["status"]), ([], "needs_topic"))

    def test_capped_flag_is_carried(self) -> None:
        problems, plan = self.sample(["graphs"], "30 problemas fáceis")
        self.assertTrue(plan["capped"])
        self.assertEqual(plan["requested_total"], 30)
        self.assertEqual(len(problems), c.MAX_PER_BAND)


class SelectArticlesTest(unittest.TestCase):
    def test_interleaves_tags_and_skips_meta_pages(self) -> None:
        index = fixtures.article_index()
        self.assertEqual(
            c.select_article_paths(index, ["binary search", "dp"]),
            [
                "src/num_methods/binary_search.md",
                "src/dynamic_programming/intro-to-dp.md",
                "src/dynamic_programming/knapsack.md",
            ],
        )
        self.assertEqual(c.select_article_paths(index, []), [])
        self.assertEqual(c.select_article_paths(index, ["greedy"]), [])
        index["articles"].append({"path": "src/tags.md"})
        self.assertNotIn("src/tags.md", c.select_article_paths(index, ["strings"], limit=10))

    def test_every_mapped_article_exists_in_real_index(self) -> None:
        real = c.load_article_index()
        if real is None:
            self.skipTest("índice real ausente; rode o sync")
        known = {article["path"] for article in real["articles"]}
        missing = [path for paths in c.TAG_ARTICLES.values() for path in paths if path not in known]
        self.assertEqual(missing, [])


class SimilarProblemsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = fixtures.build_catalog()

    def test_identical_title(self) -> None:
        report = c.find_similar_problems(
            "Criei este problema! Enunciado: Vanya and Lanterns. Vanya walks late at night along a street...",
            self.catalog,
        )
        self.assertEqual([(m["problem_id"], m["relation"]) for m in report["matches"]], [("492B", "identical")])
        self.assertEqual(report["matches"][0]["url"], "https://codeforces.com/problemset/problem/492/B")

    def test_similar_title(self) -> None:
        report = c.find_similar_problems("Título: Vanya and the Lanterns\nEnunciado: postes numa rua...", self.catalog)
        self.assertEqual([(m["problem_id"], m["relation"]) for m in report["matches"]], [("492B", "similar")])

    def test_codeforces_link_is_identical_reference(self) -> None:
        report = c.find_similar_problems(
            "Adaptei de https://codeforces.com/contest/1950/problem/D com limites maiores.", self.catalog
        )
        self.assertEqual(report["matches"][0]["evidence"], "codeforces_url")
        self.assertEqual(report["matches"][0]["problem_id"], "1950D")

    def test_short_or_single_word_titles_are_ignored(self) -> None:
        report = c.find_similar_problems("Meu problema sobre watermelon e divisão em partes pares.", self.catalog)
        self.assertEqual(report["matches"], [])

    def test_original_statement_has_no_matches(self) -> None:
        report = c.find_similar_problems("Enunciado: dado um vetor de n inteiros, conte pares com soma par.", self.catalog)
        self.assertEqual(report["matches"], [])

    def test_without_catalog(self) -> None:
        report = c.find_similar_problems("Vanya and Lanterns", None)
        self.assertFalse(report["catalog_available"])
        self.assertEqual(report["matches"], [])


class FindProblemRefsTest(unittest.TestCase):
    def test_ids_and_links_must_exist_in_catalog(self) -> None:
        catalog = fixtures.build_catalog()
        self.assertEqual(c.find_problem_refs("quero a solução do 1950D", catalog), ["1950D"])
        self.assertEqual(c.find_problem_refs("https://codeforces.com/problemset/problem/492/B", catalog), ["492B"])
        self.assertEqual(c.find_problem_refs("o 9999Z existe?", catalog), [])
        self.assertEqual(c.find_problem_refs("dp de 2D e O(1D)", catalog), [])
        self.assertEqual(c.find_problem_refs("```cpp\n// 1950D\n```", catalog), [])
        self.assertEqual(c.find_problem_refs("1950D", None), [])


if __name__ == "__main__":
    unittest.main()
