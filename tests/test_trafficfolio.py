from __future__ import annotations

import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "trafficfolio.py"
SPEC = importlib.util.spec_from_file_location("trafficfolio", MODULE_PATH)
assert SPEC and SPEC.loader
trafficfolio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trafficfolio)


def repository(name: str = "octocat/hello-world") -> dict:
    return {
        "name": name.split("/")[-1],
        "full_name": name,
        "html_url": f"https://github.com/{name}",
        "description": "A useful repository",
        "language": "Python",
        "private": False,
        "fork": False,
        "archived": False,
        "stargazers_count": 12,
        "forks_count": 3,
        "subscribers_count": 2,
        "open_issues_count": 1,
    }


def snapshot() -> dict:
    return {
        "metadata": {
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "url": "https://github.com/octocat/hello-world",
            "description": "A useful repository",
            "language": "Python",
            "private": False,
            "fork": False,
            "archived": False,
            "stars": 12,
            "forks": 3,
            "subscribers": 2,
            "open_issues": 1,
            "release_downloads": 40,
        },
        "views": {
            "2026-09-04": {"count": 20, "uniques": 7},
            "2026-09-05": {"count": 30, "uniques": 10},
        },
        "clones": {"2026-09-05": {"count": 4, "uniques": 3}},
        "referrers": [{"referrer": "google.com", "count": 8, "uniques": 5}],
        "popular_paths": [
            {"path": "/octocat/hello-world", "title": "hello-world", "count": 12, "uniques": 7}
        ],
    }


class TrafficfolioTests(unittest.TestCase):
    def test_collect_repository_aggregates_release_downloads(self) -> None:
        class FakeClient:
            def get(self, path: str):
                responses = {
                    "/repos/octocat/hello-world": repository(),
                    "/repos/octocat/hello-world/traffic/views?per=day": {
                        "views": [{"timestamp": "2026-09-05T00:00:00Z", "count": 9, "uniques": 4}]
                    },
                    "/repos/octocat/hello-world/traffic/clones?per=day": {
                        "clones": [{"timestamp": "2026-09-05T00:00:00Z", "count": 3, "uniques": 2}]
                    },
                    "/repos/octocat/hello-world/traffic/popular/referrers": [],
                    "/repos/octocat/hello-world/traffic/popular/paths": [],
                }
                return responses[path]

            def get_paginated(self, path: str):
                self.release_path = path
                return [{"assets": [{"download_count": 4}, {"download_count": 6}]}]

        client = FakeClient()
        result = trafficfolio.collect_repository(client, repository())
        self.assertEqual(result["metadata"]["release_downloads"], 10)
        self.assertEqual(result["views"]["2026-09-05"]["count"], 9)
        self.assertEqual(
            client.release_path, "/repos/octocat/hello-world/releases"
        )

    def test_merge_snapshot_is_idempotent_for_daily_traffic(self) -> None:
        now = datetime(2026, 9, 5, 12, tzinfo=UTC)
        data = trafficfolio.empty_data("octocat")
        first = trafficfolio.merge_snapshot(
            data, [repository()], {"octocat/hello-world": snapshot()}, now
        )
        second_snapshot = snapshot()
        second_snapshot["views"]["2026-09-05"]["count"] = 35
        merged = trafficfolio.merge_snapshot(
            first, [repository()], {"octocat/hello-world": second_snapshot}, now
        )

        repo = merged["repositories"]["octocat/hello-world"]
        self.assertEqual(repo["traffic"]["2026-09-05"]["views"], 35)
        self.assertEqual(repo["traffic"]["2026-09-05"]["clones"], 4)
        self.assertEqual(len(repo["traffic"]), 2)
        self.assertEqual(repo["counters"]["2026-09-05"]["stars"], 12)

    def test_replace_dashboard_preserves_human_content(self) -> None:
        original = (
            "# Intro\n\nBefore\n"
            f"{trafficfolio.START_MARKER}\nold\n{trafficfolio.END_MARKER}\n"
            "After"
        )
        updated = trafficfolio.replace_dashboard(original, "new")
        self.assertIn("Before", updated)
        self.assertIn("After", updated)
        self.assertIn("new", updated)
        self.assertNotIn("\nold\n", updated)

    def test_repeated_writes_do_not_append_trailing_blank_lines(self) -> None:
        now = datetime(2026, 9, 5, 12, tzinfo=UTC)
        data = trafficfolio.merge_snapshot(
            trafficfolio.empty_data("octocat"),
            [repository()],
            {"octocat/hello-world": snapshot()},
            now,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text(
                f"# Test\n{trafficfolio.START_MARKER}\npending\n"
                f"{trafficfolio.END_MARKER}\n",
                encoding="utf-8",
            )
            for _ in range(2):
                trafficfolio.write_outputs(
                    data, root / "data.json", readme, root / "assets"
                )
            output = readme.read_text(encoding="utf-8")
        self.assertTrue(output.endswith("\n"))
        self.assertFalse(output.endswith("\n\n"))

    def test_renderer_produces_readme_and_valid_svg(self) -> None:
        now = datetime(2026, 9, 5, 12, tzinfo=UTC)
        data = trafficfolio.merge_snapshot(
            trafficfolio.empty_data("octocat"),
            [repository()],
            {"octocat/hello-world": snapshot()},
            now,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            readme = root / "README.md"
            readme.write_text(
                f"# Test\n{trafficfolio.START_MARKER}\npending\n{trafficfolio.END_MARKER}\n",
                encoding="utf-8",
            )
            trafficfolio.write_outputs(data, root / "data.json", readme, root / "assets")
            output = readme.read_text(encoding="utf-8")
            svg = (root / "assets" / "dashboard.svg").read_text(encoding="utf-8")

        self.assertIn("octocat/hello-world", output)
        self.assertIn("Trending repositories", output)
        self.assertIn("dashboard.svg?v=2026-09-05T12%3A00%3A00Z", output)
        self.assertTrue(svg.startswith("<svg "))
        self.assertIn("Trafficfolio", svg)
        ET.fromstring(svg)

    def test_owner_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.json"
            path.write_text(
                '{"version": 1, "owner": "someone-else", "repositories": {}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "not 'octocat'"):
                trafficfolio.load_data(path, "octocat")

    def test_seed_data_adopts_fork_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.json"
            path.write_text(
                '{"version": 1, "owner": "OWNER", "repositories": {}}',
                encoding="utf-8",
            )
            data = trafficfolio.load_data(path, "octocat")
        self.assertEqual(data["owner"], "octocat")

    def test_truthy_configuration_values(self) -> None:
        for value in ("true", "TRUE", "1", "yes", "on"):
            self.assertTrue(trafficfolio.enabled(value))
        for value in (None, "", "false", "0", "no"):
            self.assertFalse(trafficfolio.enabled(value))

    def test_private_repositories_are_opt_in(self) -> None:
        public = repository("octocat/public")
        public["owner"] = {"login": "octocat"}
        private = repository("octocat/private")
        private["owner"] = {"login": "octocat"}
        private["private"] = True
        other = repository("someone-else/project")
        other["owner"] = {"login": "someone-else"}

        visible = trafficfolio.owned_repositories(
            [public, private, other], "OctoCat", include_private=False
        )
        all_owned = trafficfolio.owned_repositories(
            [public, private, other], "octocat", include_private=True
        )

        self.assertEqual([item["name"] for item in visible], ["public"])
        self.assertEqual(
            [item["name"] for item in all_owned], ["public", "private"]
        )

    def test_untrusted_markdown_is_escaped(self) -> None:
        escaped = trafficfolio.markdown_escape(
            r"[click](https://attacker.example) <img src=x> | `code`"
        )
        self.assertEqual(
            escaped,
            r"\[click\]\(https://attacker\.example\) &lt;img src=x&gt; \| \`code\`",
        )

    def test_popular_paths_are_limited_to_the_expected_repository(self) -> None:
        repository_url = "https://github.com/octocat/hello-world"
        self.assertEqual(
            trafficfolio.popular_path_url(
                "octocat/hello-world",
                "/octocat/hello-world/issues/1_(test)",
                repository_url,
            ),
            "https://github.com/octocat/hello-world/issues/1_%28test%29",
        )
        self.assertEqual(
            trafficfolio.popular_path_url(
                "octocat/hello-world",
                "/attacker/project/issues/1",
                repository_url,
            ),
            repository_url,
        )


if __name__ == "__main__":
    unittest.main()
