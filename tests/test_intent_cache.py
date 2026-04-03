"""Intent 缓存一致性测试。

验证 intent 缓存的写入、读取、空内容拒绝等行为。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Agent.core.api.intent import IntentAPI


class IntentCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.project_root = str(self.tmp_dir / "test-intent-project")
        self.project_root_resolved = str(Path(self.project_root).resolve())
        self.cache_dir = self.tmp_dir / "cache"
        self.cache_dir.mkdir()

    def _patch_cache_dir(self):
        return patch.object(IntentAPI, "_get_preferred_cache_dir", return_value=self.cache_dir)

    def test_save_and_read_intent_cache(self) -> None:
        """验证缓存写入后能正确读取。"""
        content = "# 项目意图\n这是一个测试项目"
        with self._patch_cache_dir():
            result = IntentAPI.save_intent_cache(
                project_root=self.project_root,
                content=content,
                source="agent",
            )
        self.assertTrue(result["success"], f"save failed: {result}")

        with self._patch_cache_dir():
            cache = IntentAPI.get_intent_cache(self.project_root)
        self.assertTrue(cache["found"])
        self.assertEqual(cache["content"], content)
        self.assertEqual(cache["source"], "agent")

    def test_empty_content_rejected(self) -> None:
        """验证空内容不会被写入缓存。"""
        with self._patch_cache_dir():
            result = IntentAPI.save_intent_cache(
                project_root=self.project_root,
                content="",
                source="agent",
            )
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_whitespace_only_content_rejected(self) -> None:
        """验证纯空白内容不会被写入缓存。"""
        with self._patch_cache_dir():
            result = IntentAPI.save_intent_cache(
                project_root=self.project_root,
                content="   \n\n  ",
                source="agent",
            )
        self.assertFalse(result["success"])

    def test_update_existing_cache(self) -> None:
        """验证更新已有缓存时保留 created_at。"""
        with self._patch_cache_dir():
            IntentAPI.save_intent_cache(
                project_root=self.project_root,
                content="原始内容",
                source="agent",
            )
            first = IntentAPI.get_intent_cache(self.project_root)
        self.assertTrue(first["found"])
        first_created = first["created_at"]

        with self._patch_cache_dir():
            result = IntentAPI.update_intent_cache(
                project_root=self.project_root,
                content="更新后的内容",
            )
        self.assertTrue(result["success"])

        with self._patch_cache_dir():
            updated = IntentAPI.get_intent_cache(self.project_root)
        self.assertEqual(updated["content"], "更新后的内容")
        self.assertEqual(updated["created_at"], first_created)
        self.assertEqual(updated["source"], "manual")

    def test_status_check(self) -> None:
        """验证状态检查 API。"""
        with self._patch_cache_dir():
            status = IntentAPI.check_intent_status(self.project_root)
        self.assertFalse(status["exists"])

        with self._patch_cache_dir():
            IntentAPI.save_intent_cache(
                project_root=self.project_root,
                content="测试内容",
                source="agent",
            )
            status = IntentAPI.check_intent_status(self.project_root)
        self.assertTrue(status["exists"])
        self.assertIsNotNone(status["created_at"])

    def test_nonexistent_project(self) -> None:
        """验证不存在项目的缓存读取。"""
        with self._patch_cache_dir():
            cache = IntentAPI.get_intent_cache("/nonexistent/path/project")
        self.assertFalse(cache["found"])


if __name__ == "__main__":
    unittest.main()
