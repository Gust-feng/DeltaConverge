from __future__ import annotations

import unittest

from Agent.agents.context_scheduler import clear_file_caches, get_cache_stats


class ContextCacheScopingTests(unittest.TestCase):
    def test_clear_file_caches_supports_scope(self) -> None:
        clear_file_caches()
        stats = get_cache_stats()
        self.assertIn("scope_count", stats)
        self.assertEqual(stats["scope_count"], 0)

        clear_file_caches(project_root="Z:\\repo-a")
        stats_after = get_cache_stats()
        self.assertIn("scope_count", stats_after)

    def test_get_cache_stats_scope_param(self) -> None:
        clear_file_caches()
        scoped = get_cache_stats(project_root="Z:\\repo-missing")
        self.assertIn("scope_count", scoped)
        self.assertEqual(scoped["scope_count"], 0)


if __name__ == "__main__":
    unittest.main()

