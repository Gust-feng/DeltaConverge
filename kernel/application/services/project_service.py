"""项目、Diff、Git 和扫描器状态聚合服务。

通过 ProjectPort / ProjectDiffPort / GitPort 访问底层能力，
不直接依赖旧 Agent/ 代码。未注入端口时回退到 Legacy 适配器，
保证可独立运行与向后兼容。
"""

from __future__ import annotations

import time
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

    def get_commit_history(self, project_root: str, limit: int = 50) -> Dict[str, Any]:
        stdout, _, _ = self.git_port.run_git(
            ["log", f"-n{int(limit)}", "--pretty=format:%H|%h|%s|%an|%ar"],
            cwd=project_root,
        )
        commits = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue
            commits.append(
                {
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "message": parts[2],
                    "author": parts[3],
                    "time_ago": parts[4],
                }
            )
        return {"commits": commits, "count": len(commits)}

    def get_commit_range_diff(
        self,
        *,
        project_root: str,
        commit_from: str,
        commit_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = time.perf_counter()
        diff_text = self.git_port.get_diff_text(
            mode=PortDiffMode.COMMIT,
            cwd=project_root,
            base_ref=commit_from,
            head_ref=commit_to,
        )
        files: List[Dict[str, Any]] = []

        try:
            from unidiff import PatchSet

            patch = PatchSet(diff_text)
            for patched_file in patch:
                path = patched_file.path
                if path.startswith("a/"):
                    path = path[2:]
                elif path.startswith("b/"):
                    path = path[2:]
                files.append(
                    {
                        "path": path,
                        "source_file": (patched_file.source_file or "").lstrip("a/"),
                        "target_file": (patched_file.target_file or "").lstrip("b/"),
                        "added_lines": patched_file.added,
                        "removed_lines": patched_file.removed,
                        "is_binary": patched_file.is_binary_file,
                    }
                )
        except Exception as exc:
            return {
                "success": True,
                "diff_text": diff_text,
                "files": files,
                "file_count": len(files),
                "commit_from": commit_from,
                "commit_to": commit_to or "HEAD",
                "parse_error": str(exc),
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        return {
            "success": True,
            "diff_text": diff_text,
            "files": files,
            "file_count": len(files),
            "commit_from": commit_from,
            "commit_to": commit_to or "HEAD",
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }

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
