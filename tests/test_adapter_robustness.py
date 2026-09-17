"""适配器健壮性测试。

覆盖两类曾导致线上 500 的问题：

1. 无效工作目录：项目被移动/重命名后，前端仍持旧路径时，
   ``git`` 子进程会抛 Windows 特有的 NotADirectoryError（未捕获 → 500）。
   适配器应改为抛 ValueError，交由应用层回应 4xx。
2. 并发导入死锁：适配器在请求线程内惰性导入旧模块，并发时 CPython
   模块锁可能形成等待环（_DeadlockError）。启动期预热应消除该风险。
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path

from kernel.infrastructure.git_adapter import LegacyGitAdapter


class InvalidWorkingDirectoryTests(unittest.TestCase):
    def test_run_git_rejects_missing_directory(self) -> None:
        adapter = LegacyGitAdapter()
        missing = str(Path(__file__).resolve().parent / "definitely-not-a-dir")
        with self.assertRaises(ValueError) as ctx:
            adapter.run_git(["log"], cwd=missing)
        self.assertIn("工作目录不存在或不可访问", str(ctx.exception))

    def test_run_git_rejects_file_as_directory(self) -> None:
        adapter = LegacyGitAdapter()
        # 用一个文件路径充当工作目录，同样应被拒绝
        a_file = str(Path(__file__).resolve())
        with self.assertRaises(ValueError):
            adapter.run_git(["log"], cwd=a_file)

    def test_run_git_allows_existing_directory(self) -> None:
        adapter = LegacyGitAdapter()
        repo_root = str(Path(__file__).resolve().parents[1])
        # 真实仓库目录应通过校验并返回 git 输出
        stdout, _stderr, code = adapter.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
        self.assertEqual(code, 0)
        self.assertTrue(stdout.strip())

    def test_run_git_without_cwd_is_unaffected(self) -> None:
        adapter = LegacyGitAdapter()
        # 未指定 cwd 时不做目录校验（沿用进程当前目录）
        stdout, _stderr, code = adapter.run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        self.assertEqual(code, 0)
        self.assertTrue(stdout.strip())


class PrewarmTests(unittest.TestCase):
    def test_prewarm_imports_key_legacy_modules(self) -> None:
        import sys

        from kernel.bootstrap import prewarm_legacy_imports

        prewarm_legacy_imports()

        for module in ("Agent.core.api.tools", "Agent.tool.registry", "Agent.core.api.config"):
            with self.subTest(module=module):
                self.assertIn(module, sys.modules)

    def test_concurrent_import_after_prewarm_does_not_deadlock(self) -> None:
        """预热后并发导入不得出现 _DeadlockError。"""
        import importlib

        from kernel.bootstrap import prewarm_legacy_imports

        prewarm_legacy_imports()

        errors: list[str] = []

        def load(name: str) -> None:
            try:
                importlib.import_module(name)
            except Exception as exc:  # noqa: BLE001 - 记录任意失败类型用于断言
                errors.append(type(exc).__name__)

        modules = [
            "Agent.core.api.tools",
            "Agent.tool.registry",
            "Agent.core.api.project",
            "Agent.core.api.config",
        ] * 5
        threads = [threading.Thread(target=load, args=(m,)) for m in modules]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
