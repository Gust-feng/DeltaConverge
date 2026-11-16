"""旧 UI 兼容层：diff/commits、diff/commit-range、git/check（G18/G19/G09）。"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import httpx

from adapters.web.app import create_app
from adapters.web.dependencies import get_facade
from adapters.web.routers.git import git_router
from kernel.application.services.project_service import ProjectService


class _FacadeStub:
    """只暴露 diff/git 兼容端点所需的最小门面。"""

    def __init__(self) -> None:
        self.project_service = ProjectService()

    def get_commit_range_diff(self, **kwargs):
        return self.project_service.get_commit_range_diff(**kwargs)


class WebCompatDiffGitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        self._git("init", "-q")
        self._git("config", "user.name", "Test Author")
        self._git("config", "user.email", "author@example.com")

        (self.repo / "a.txt").write_text("line1\n", encoding="utf-8")
        (self.repo / "deleted.txt").write_text("remove me\n", encoding="utf-8")
        (self.repo / "old_name.txt").write_text("rename me\n" * 30, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "initial commit")
        self.c1 = self._git("rev-parse", "HEAD")
        self._git("branch", "side", self.c1)

        (self.repo / "a.txt").write_text("line1\nline2\n", encoding="utf-8")
        (self.repo / "deleted.txt").unlink()
        self._git("mv", "old_name.txt", "new_name.txt")
        (self.repo / "added.txt").write_text("brand new\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "second commit")
        self.c2 = self._git("rev-parse", "HEAD")

        (self.repo / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
        self._git("commit", "-q", "-am", "third commit")
        self.c3 = self._git("rev-parse", "HEAD")
        self.branch = self._git("branch", "--show-current")

        self.facade = _FacadeStub()
        app = create_app()
        app.include_router(git_router)
        app.dependency_overrides[get_facade] = lambda: self.facade
        self.app = app
        self.client: httpx.AsyncClient | None = None

    async def asyncSetUp(self) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _git(self, *args: str) -> str:
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "Test Author",
                "GIT_AUTHOR_EMAIL": "author@example.com",
                "GIT_COMMITTER_NAME": "Test Author",
                "GIT_COMMITTER_EMAIL": "author@example.com",
                "GIT_AUTHOR_DATE": "2026-11-16T10:00:00+0800",
                "GIT_COMMITTER_DATE": "2026-11-16T10:00:00+0800",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return result.stdout.strip()

    async def test_commits_pagination_and_fields(self) -> None:
        response = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(self.repo), "limit": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data["success"])
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["skip"], 0)
        self.assertEqual(data["count"], 2)
        self.assertEqual([item["hash"] for item in data["commits"]], [self.c3, self.c2])

        newest = data["commits"][0]
        self.assertTrue(self.c3.startswith(newest["short_hash"]))
        self.assertEqual(newest["message"], "third commit")
        self.assertEqual(newest["author"], "Test Author")
        self.assertEqual(newest["email"], "author@example.com")
        self.assertTrue(newest["date"].startswith("2026-11-16T10:00:00"))
        self.assertTrue(newest["relative_date"])
        self.assertEqual(newest["time_ago"], newest["relative_date"])
        self.assertEqual(newest["parents"], [self.c2])
        self.assertTrue(newest["refs"])
        self.assertFalse(newest["is_merge"])

        second_page = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(self.repo), "limit": 2, "skip": 2},
        )
        page = second_page.json()
        self.assertTrue(page["success"])
        self.assertEqual(page["skip"], 2)
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["commits"][0]["hash"], self.c1)
        self.assertEqual(page["commits"][0]["parents"], [])

    async def test_commits_branch_filter(self) -> None:
        current = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(self.repo), "limit": 10, "branch": self.branch},
        )
        self.assertEqual(current.json()["count"], 3)

        side = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(self.repo), "limit": 10, "branch": "side"},
        )
        side_data = side.json()
        self.assertTrue(side_data["success"])
        self.assertEqual(side_data["count"], 1)
        self.assertEqual(side_data["commits"][0]["hash"], self.c1)

    async def test_commit_range_change_types(self) -> None:
        response = await self.client.get(
            "/api/v2/diff/commit-range",
            params={
                "project_root": str(self.repo),
                "commit_from": self.c1,
                "commit_to": self.c2,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["file_count"], 4)

        change_types = {item["path"]: item["change_type"] for item in data["files"]}
        self.assertEqual(change_types["a.txt"], "modify")
        self.assertEqual(change_types["added.txt"], "add")
        self.assertEqual(change_types["deleted.txt"], "delete")
        self.assertEqual(change_types["new_name.txt"], "rename")

    async def test_commit_range_empty_and_invalid_ref(self) -> None:
        empty = await self.client.get(
            "/api/v2/diff/commit-range",
            params={
                "project_root": str(self.repo),
                "commit_from": self.c1,
                "commit_to": self.c1,
            },
        )
        empty_data = empty.json()
        self.assertEqual(empty.status_code, 200)
        self.assertTrue(empty_data["success"])
        self.assertEqual(empty_data["files"], [])
        self.assertEqual(empty_data["message"], "No changes between commits")

        invalid = await self.client.get(
            "/api/v2/diff/commit-range",
            params={
                "project_root": str(self.repo),
                "commit_from": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                "commit_to": self.c2,
            },
        )
        invalid_data = invalid.json()
        # 旧 UI 读 data.success / data.error；保持 200 + success:false 语义
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(invalid_data["success"])
        self.assertIn("deadbeef", invalid_data["error"])
        self.assertEqual(invalid_data["files"], [])

    async def test_commit_history_error_semantics(self) -> None:
        plain = self.root / "plain-dir"
        plain.mkdir()
        response = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(plain)},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertTrue(data["error"])
        self.assertEqual(data["commits"], [])

        missing = await self.client.get(
            "/api/v2/diff/commits",
            params={"project_root": str(self.root / "missing-dir")},
        )
        self.assertEqual(missing.status_code, 400)

    async def test_git_check_repository_subdirectory_and_errors(self) -> None:
        repo_path = str(self.repo.resolve())
        response = await self.client.post("/api/v2/git/check", json={"path": repo_path})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["is_git"])
        self.assertIsNone(data["error"])
        self.assertEqual(os.path.normcase(data["git_root"]), os.path.normcase(repo_path))
        if os.name == "nt":
            self.assertNotIn("/", data["git_root"])
            self.assertIn(":\\", data["git_root"])

        subdir = self.repo / "sub" / "dir"
        subdir.mkdir(parents=True)
        nested = await self.client.post("/api/v2/git/check", json={"path": str(subdir)})
        nested_data = nested.json()
        self.assertTrue(nested_data["is_git"])
        self.assertEqual(
            os.path.normcase(nested_data["git_root"]),
            os.path.normcase(repo_path),
        )

        plain = self.root / "not-a-repo"
        plain.mkdir()
        not_repo = await self.client.post("/api/v2/git/check", json={"path": str(plain)})
        not_repo_data = not_repo.json()
        self.assertEqual(not_repo.status_code, 200)
        self.assertFalse(not_repo_data["is_git"])
        self.assertIsNone(not_repo_data["git_root"])
        self.assertIsNone(not_repo_data["error"])

        missing = await self.client.post(
            "/api/v2/git/check", json={"path": str(self.root / "does-not-exist")}
        )
        missing_data = missing.json()
        self.assertEqual(missing.status_code, 200)
        self.assertFalse(missing_data["is_git"])
        self.assertIsNone(missing_data["git_root"])
        self.assertEqual(missing_data["error"], "目录不存在")

        empty_path = await self.client.post("/api/v2/git/check", json={"path": ""})
        self.assertEqual(empty_path.status_code, 200)
        self.assertFalse(empty_path.json()["is_git"])
        self.assertEqual(empty_path.json()["error"], "未提供路径")

        missing_body = await self.client.post("/api/v2/git/check", json={})
        self.assertEqual(missing_body.status_code, 422)

    def test_normalize_git_root_windows_forms(self) -> None:
        self.assertEqual(ProjectService._normalize_git_root("C:/repo/sub"), "C:\\repo\\sub")
        self.assertEqual(ProjectService._normalize_git_root("/c/repo"), "C:\\repo")
        self.assertEqual(ProjectService._normalize_git_root("F:/"), "F:\\")


if __name__ == "__main__":
    unittest.main()
