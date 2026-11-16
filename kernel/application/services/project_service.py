"""项目、Diff、Git 和扫描器状态聚合服务。

通过 ProjectPort / ProjectDiffPort / GitPort 访问底层能力，
不直接依赖旧 Agent/ 代码。未注入端口时回退到 Legacy 适配器，
保证可独立运行与向后兼容。
"""

from __future__ import annotations

import ntpath
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kernel.domain.models import ProjectAnalysis
from kernel.ports.git import DiffMode as PortDiffMode, GitPort
from kernel.ports.project import ProjectDiffPort, ProjectPort


class ProjectService:
    def __init__(
        self,
        *,
        project_port: ProjectPort | None = None,
        project_diff_port: ProjectDiffPort | None = None,
        git_port: GitPort | None = None,
    ) -> None:
        if project_port is None:
            from kernel.infrastructure import LegacyProjectAdapter

            project_port = LegacyProjectAdapter()
        if project_diff_port is None:
            from kernel.infrastructure import LegacyProjectDiffAdapter

            project_diff_port = LegacyProjectDiffAdapter()
        if git_port is None:
            from kernel.infrastructure import LegacyGitAdapter

            git_port = LegacyGitAdapter()
        self.project_port = project_port
        self.project_diff_port = project_diff_port
        self.git_port = git_port

    def analyze_project(self, project_root: str) -> ProjectAnalysis:
        return ProjectAnalysis(
            info=self.project_port.get_project_info(project_root),
            tree=self.project_port.get_file_tree(project_root),
            readme=self.project_port.get_readme_content(project_root),
            dependencies=self.project_port.get_dependencies(project_root),
            git=self.project_port.get_git_info(project_root),
        )

    def get_diff_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        return self.project_diff_port.get_diff_status(project_root)

    def get_diff_summary(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        return self.project_diff_port.get_diff_summary(project_root, mode)

    def get_diff_files(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        return self.project_diff_port.get_diff_files(project_root, mode)

    def get_file_diff(
        self,
        file_path: str,
        *,
        project_root: Optional[str] = None,
        mode: str = "auto",
        commit_from: Optional[str] = None,
        commit_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.project_diff_port.get_file_diff(
            file_path=file_path,
            project_root=project_root,
            mode=mode,
            commit_from=commit_from,
            commit_to=commit_to,
        )

    def get_diff_quick_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        """轻量 Diff 检测：单次 ``git status --porcelain``。

        与旧 UI 的 ``/api/diff/quick-status`` 保持一致：
        未跟踪目录按 git 的折叠形式返回，且 staged 优先于 working。
        """
        start = time.perf_counter()
        root = (project_root or "").strip() or None
        empty = {
            "mode": "working",
            "files": [],
            "file_count": 0,
            "has_staged": False,
            "has_working": False,
            "staged_count": 0,
            "working_count": 0,
            "elapsed_ms": 0,
            "error": None,
        }
        if not root:
            empty["error"] = "project_root is required"
            empty["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            return empty

        try:
            stdout, _stderr, _code = self.git_port.run_git(["status", "--porcelain"], cwd=root)
        except Exception as exc:  # noqa: BLE001 - 旧接口同样把失败降级为 error 字段
            empty["error"] = str(exc)
            empty["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            return empty

        staged_files: List[Dict[str, str]] = []
        working_files: List[Dict[str, str]] = []
        change_types = {"A": "add", "M": "modify", "D": "delete", "R": "rename", "C": "copy"}

        for line in (stdout or "").splitlines():
            if len(line) < 3:
                continue
            x = line[0]
            y = line[1]
            path = line[3:] if len(line) > 3 else ""
            if x == "?" and y == "?":
                working_files.append({"path": path, "display_path": path, "change_type": "add"})
                continue
            if x != " " and x != "?":
                staged_files.append(
                    {
                        "path": path,
                        "display_path": path,
                        "change_type": change_types.get(x, "modify"),
                    }
                )
            if y != " ":
                if not any(item["path"] == path for item in working_files):
                    working_files.append(
                        {
                            "path": path,
                            "display_path": path,
                            "change_type": {"M": "modify", "D": "delete", "A": "add"}.get(y, "modify"),
                        }
                    )

        has_staged = len(staged_files) > 0
        has_working = len(working_files) > 0
        if has_staged:
            mode = "staged"
            files = staged_files
        else:
            mode = "working"
            files = working_files
        return {
            "mode": mode,
            "files": files,
            "file_count": len(files),
            "has_staged": has_staged,
            "has_working": has_working,
            "staged_count": len(staged_files),
            "working_count": len(working_files),
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
            "error": None,
        }

    def get_commit_history(
        self,
        project_root: str,
        limit: int = 50,
        skip: int = 0,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取 Git 提交历史（兼容旧 UI 的 success/分页/日期字段）。

        - 路径为空或不存在：``ValueError`` → Web 层回 400。
        - Git 执行失败（非仓库、无 git 可执行文件等）：200 + ``success:false``，
          旧 UI ``git-history.js`` 依赖 ``success`` 分支显示错误。
        """
        start = time.perf_counter()
        root = (project_root or "").strip()
        if not root:
            raise ValueError("project_root is required")
        if not Path(root).is_dir():
            raise ValueError(f"工作目录不存在或不可访问: {root}")

        limit = max(1, int(limit))
        skip = max(0, int(skip))

        args = [
            "log",
            f"--max-count={limit}",
            f"--skip={skip}",
            "--pretty=format:%H%x00%h%x00%an%x00%ae%x00%aI%x00%ar%x00%B%x00%P%x00%D%x01",
        ]
        if branch:
            args.append(branch)

        try:
            stdout, _stderr, _code = self.git_port.run_git(args, cwd=root)
        except ValueError:
            # 路径类错误交给 Web 层转换成 400
            raise
        except Exception as exc:  # noqa: BLE001 - 统一降级为 success:false
            return {
                "success": False,
                "error": str(exc),
                "commits": [],
                "project_root": root,
                "limit": limit,
                "skip": skip,
                "count": 0,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        commits = self._parse_git_log(stdout)
        return {
            "success": True,
            "commits": commits,
            "project_root": root,
            "limit": limit,
            "skip": skip,
            "count": len(commits),
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

    @staticmethod
    def _parse_git_log(stdout: str) -> List[Dict[str, Any]]:
        """解析 ``git log --pretty=format:...%x01`` 输出。

        字段顺序：hash、short_hash、author、email、date(ISO)、relative_date、
        完整 message、parents、refs。
        """
        commits: List[Dict[str, Any]] = []
        for entry in (stdout or "").split("\x01"):
            # git 会在记录之间插入换行，去掉记录首尾空白（message 末尾换行也在此处理）
            entry = entry.strip()
            if not entry:
                continue
            fields = entry.split("\x00")
            if len(fields) < 7:
                continue
            parents = fields[7].split() if len(fields) > 7 and fields[7].strip() else []
            relative_date = fields[5]
            commits.append(
                {
                    "hash": fields[0],
                    "short_hash": fields[1],
                    "author": fields[2],
                    "email": fields[3],
                    "date": fields[4],
                    "relative_date": relative_date,
                    "time_ago": relative_date,
                    "message": fields[6].strip(),
                    "refs": fields[8].strip() if len(fields) > 8 else "",
                    "parents": parents,
                    "is_merge": len(parents) > 1,
                }
            )
        return commits

    def get_commit_range_diff(
        self,
        *,
        project_root: str,
        commit_from: str,
        commit_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        root = (project_root or "").strip()
        if not root:
            raise ValueError("project_root is required")
        if not Path(root).is_dir():
            raise ValueError(f"工作目录不存在或不可访问: {root}")

        try:
            diff_text = self.git_port.get_diff_text(
                mode=PortDiffMode.COMMIT,
                cwd=root,
                base_ref=commit_from,
                head_ref=commit_to,
            )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - 非法 commit ref / git 失败
            # 旧 /api/diff/commit 对非法 ref 返回 200 + success:false；
            # 旧 UI（diff.js:1268-1274）正是读 data.success / data.error。
            return {
                "success": False,
                "error": str(exc),
                "diff_text": "",
                "files": [],
                "file_count": 0,
                "commit_from": commit_from,
                "commit_to": commit_to or "HEAD",
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        base_payload: Dict[str, Any] = {
            "success": True,
            "diff_text": diff_text,
            "files": [],
            "file_count": 0,
            "commit_from": commit_from,
            "commit_to": commit_to or "HEAD",
        }

        if not (diff_text or "").strip():
            return {
                **base_payload,
                "message": "No changes between commits",
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        files: List[Dict[str, Any]] = []

        try:
            from unidiff import PatchSet

            patch = PatchSet(diff_text)
            for patched_file in patch:
                path = self._strip_diff_prefix(patched_file.path or "")
                source_file = patched_file.source_file or ""
                target_file = patched_file.target_file or ""
                files.append(
                    {
                        "path": path,
                        "source_file": self._strip_diff_prefix(source_file),
                        "target_file": self._strip_diff_prefix(target_file),
                        "added_lines": patched_file.added,
                        "removed_lines": patched_file.removed,
                        "is_binary": patched_file.is_binary_file,
                        "change_type": self._change_type(source_file, target_file),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - 解析失败时仍返回原始 diff
            return {
                **base_payload,
                "files": files,
                "file_count": len(files),
                "parse_error": str(exc),
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        return {
            **base_payload,
            "files": files,
            "file_count": len(files),
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

    @staticmethod
    def _strip_diff_prefix(path: str) -> str:
        """移除 diff 的 ``a/`` / ``b/`` 前缀（只移除一次，不用 lstrip 的字符集语义）。"""
        if path.startswith("a/") or path.startswith("b/"):
            return path[2:]
        return path

    @staticmethod
    def _change_type(source_file: str, target_file: str) -> str:
        """按旧 /api/diff/commit 语义推导 change_type。"""
        source = source_file or ""
        target = target_file or ""
        if source == "/dev/null" or source.endswith("/dev/null"):
            return "add"
        if target == "/dev/null" or target.endswith("/dev/null"):
            return "delete"
        source_clean = ProjectService._strip_diff_prefix(source)
        target_clean = ProjectService._strip_diff_prefix(target)
        if source_clean and target_clean and source_clean != target_clean:
            return "rename"
        return "modify"

    def check_git_repository(self, path: str) -> Dict[str, Any]:
        """轻量级 Git 仓库检测（G09）。

        返回 ``{"is_git": bool, "git_root": str|None, "error": str|None}``；
        目录不存在等用户可修复的问题一律 200 + error，不抛 500。
        """
        raw_path = (path or "").strip()
        if not raw_path:
            return {"is_git": False, "git_root": None, "error": "未提供路径"}

        try:
            target = Path(raw_path).expanduser().resolve()
        except OSError as exc:
            return {"is_git": False, "git_root": None, "error": str(exc)}

        if not target.exists() or not target.is_dir():
            return {"is_git": False, "git_root": None, "error": "目录不存在"}

        try:
            stdout, _stderr, code = self.git_port.run_git(
                ["rev-parse", "--is-inside-work-tree"],
                cwd=str(target),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"is_git": False, "git_root": None, "error": "Git 检测超时"}
        except FileNotFoundError:
            return {"is_git": False, "git_root": None, "error": "Git 未安装或不在 PATH 中"}
        except Exception as exc:  # noqa: BLE001 - 检测失败不阻断旧 UI
            return {"is_git": False, "git_root": None, "error": str(exc)}

        if code != 0 or stdout.strip().lower() != "true":
            return {"is_git": False, "git_root": None, "error": None}

        try:
            root_stdout, _root_stderr, root_code = self.git_port.run_git(
                ["rev-parse", "--show-toplevel"],
                cwd=str(target),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"is_git": False, "git_root": None, "error": "Git 检测超时"}
        except Exception:  # noqa: BLE001 - 在仓库内但取根目录失败（罕见）
            return {"is_git": True, "git_root": None, "error": None}

        git_root = root_stdout.strip()
        if root_code != 0 or not git_root:
            return {"is_git": True, "git_root": None, "error": None}

        return {
            "is_git": True,
            "git_root": self._normalize_git_root(git_root),
            "error": None,
        }

    @staticmethod
    def _normalize_git_root(path: str) -> str:
        """Windows 下把 Git 输出的 ``C:/repo`` 或 MSYS 的 ``/c/repo`` 归一化为 ``C:\\repo``。"""
        raw = (path or "").strip()
        if not raw:
            return raw

        windows_like = (
            os.name == "nt"
            or bool(re.match(r"^[A-Za-z]:[\\/]", raw))
            or bool(re.match(r"^/[A-Za-z]/", raw))
        )
        if not windows_like:
            return raw

        normalized = raw.replace("/", "\\")
        drive_match = re.match(r"^\\([A-Za-z])(?:\\(.*))?$", normalized)
        if drive_match:
            drive = drive_match.group(1).upper()
            rest = drive_match.group(2)
            normalized = f"{drive}:\\{rest}" if rest else f"{drive}:\\"
        return ntpath.normpath(normalized)

    def get_scanner_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        detected: List[str] = []
        if project_root:
            detected = self._normalize_detected_languages(
                self.project_port.get_project_info(project_root).get("detected_languages", [])
            )

        languages = []
        for entry in self.project_port.get_scanner_languages():
            language = entry.get("language")
            scanners = entry.get("scanners") or []
            available_count = sum(1 for item in scanners if item.get("available") and item.get("enabled"))
            enabled_count = sum(1 for item in scanners if item.get("enabled"))
            languages.append(
                {
                    "language": language,
                    "available_count": available_count,
                    "enabled_count": enabled_count,
                    "total_count": len(scanners),
                    "detected": language in detected,
                    "scanners": scanners,
                }
            )

        return {
            "detected_languages": detected,
            "languages": languages,
        }

    def _normalize_detected_languages(self, detected_languages: List[str]) -> List[str]:
        mapping = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "react": "javascript",
            "react/typescript": "typescript",
            "java": "java",
            "go": "go",
            "ruby": "ruby",
            "c": "c",
            "c++": "cpp",
            "rust": "rust",
            "php": "php",
        }
        normalized = []
        for item in detected_languages:
            key = str(item).strip().lower()
            if key in mapping:
                normalized.append(mapping[key])
        return sorted(set(normalized))
