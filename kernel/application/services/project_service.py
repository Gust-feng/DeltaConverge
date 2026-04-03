"""项目、Diff、Git 和扫描器状态聚合服务。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from kernel.domain.models import ProjectAnalysis


class ProjectService:
    def analyze_project(self, project_root: str) -> ProjectAnalysis:
        from Agent.core.api.project import ProjectAPI

        return ProjectAnalysis(
            info=ProjectAPI.get_project_info(project_root),
            tree=ProjectAPI.get_file_tree(project_root),
            readme=ProjectAPI.get_readme_content(project_root),
            dependencies=ProjectAPI.get_dependencies(project_root),
            git=ProjectAPI.get_git_info(project_root),
        )

    def get_diff_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_status(project_root)

    def get_diff_summary(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_summary(project_root, mode)

    def get_diff_files(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_files(project_root, mode)

    def get_file_diff(
        self,
        file_path: str,
        *,
        project_root: Optional[str] = None,
        mode: str = "auto",
        commit_from: Optional[str] = None,
        commit_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_file_diff(
            file_path=file_path,
            project_root=project_root,
            mode=mode,
            commit_from=commit_from,
            commit_to=commit_to,
        )

    def get_commit_history(self, project_root: str, limit: int = 50) -> Dict[str, Any]:
        from Agent.DIFF.git_operations import run_git

        output = run_git("log", f"-n{int(limit)}", "--pretty=format:%H|%h|%s|%an|%ar", cwd=project_root)
        commits = []
        for line in output.splitlines():
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
        from Agent.DIFF.git_operations import get_commit_diff

        start = time.perf_counter()
        diff_text = get_commit_diff(commit_from=commit_from, commit_to=commit_to, cwd=project_root)
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
        from Agent.core.api.project import ProjectAPI
        from Agent.DIFF.rule.scanner_registry import ScannerRegistry
        from Agent.DIFF.rule import (
            scanner_lang_go,
            scanner_lang_java,
            scanner_lang_python,
            scanner_lang_ruby,
            scanner_lang_typescript,
            scanner_performance,
            scanner_semgrep,
        )

        _ = (
            scanner_lang_go,
            scanner_lang_java,
            scanner_lang_python,
            scanner_lang_ruby,
            scanner_lang_typescript,
            scanner_performance,
            scanner_semgrep,
        )
        ScannerRegistry.load_config()

        detected = []
        if project_root:
            detected = self._normalize_detected_languages(ProjectAPI.get_project_info(project_root).get("detected_languages", []))

        languages = []
        for language in sorted(ScannerRegistry.get_registered_languages()):
            scanners = ScannerRegistry.get_scanner_info(language)
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
