"""Diff分析API模块。

提供Git Diff相关的查询功能，无需启动完整审查流程。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from Agent.DIFF.git_operations import (
    DiffMode,
    auto_detect_mode,
    has_working_changes,
    has_staged_changes,
    detect_base_branch,
    get_diff_text,
)
from Agent.DIFF.diff_collector import build_review_units_from_patch, build_review_index
from Agent.core.context.diff_provider import collect_diff_context, DiffContext

try:
    from unidiff import PatchSet
except ImportError:
    PatchSet = None


@dataclass
class DiffStatus:
    """Diff状态信息。"""
    has_working_changes: bool
    has_staged_changes: bool
    detected_mode: Optional[str]
    base_branch: Optional[str]
    error: Optional[str] = None


class DiffAPI:
    """Diff分析API（静态方法接口）。"""
    
    @staticmethod
    def get_diff_status(project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取项目的Diff状态（不解析具体内容）。
        
        Args:
            project_root: 项目根目录，None则使用当前目录
            
        Returns:
            Dict: {
                "has_working_changes": bool,
                "has_staged_changes": bool,
                "detected_mode": str | None,
                "base_branch": str | None,
                "error": str | None
            }
        """
        try:
            working = has_working_changes(cwd=project_root)
            staged = has_staged_changes(cwd=project_root)
            
            detected_mode = None
            base_branch = None
            
            try:
                mode = auto_detect_mode(cwd=project_root)
                detected_mode = mode.value
            except RuntimeError:
                pass
            
            try:
                base_branch = detect_base_branch(cwd=project_root)
            except RuntimeError:
                pass
            
            return {
                "has_working_changes": working,
                "has_staged_changes": staged,
                "detected_mode": detected_mode,
                "base_branch": base_branch,
                "error": None,
            }
        except Exception as e:
            return {
                "has_working_changes": False,
                "has_staged_changes": False,
                "detected_mode": None,
                "base_branch": None,
                "error": str(e),
            }
    
    @staticmethod
    def get_diff_summary(
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取Diff摘要信息（解析但不执行审查）。
        
        Args:
            project_root: 项目根目录
            mode: Diff模式 ("auto", "working", "staged", "pr")
            
        Returns:
            Dict: {
                "summary": str,
                "mode": str,
                "base_branch": str | None,
                "files": List[str],
                "file_count": int,
                "unit_count": int,
                "lines_added": int,
                "lines_removed": int,
                "error": str | None
            }
        """
        try:
            diff_mode = DiffMode(mode) if mode != "auto" else DiffMode.AUTO
            diff_ctx = collect_diff_context(mode=diff_mode, cwd=project_root)
            
            # 从 review_index 提取统计
            meta = diff_ctx.review_index.get("review_metadata", {})
            summary = diff_ctx.review_index.get("summary", {})
            total_lines = summary.get("total_lines", {})
            
            return {
                "summary": diff_ctx.summary,
                "mode": diff_ctx.mode.value,
                "base_branch": diff_ctx.base_branch,
                "files": diff_ctx.files,
                "file_count": len(diff_ctx.files),
                "unit_count": len(diff_ctx.units),
                "lines_added": total_lines.get("added", 0),
                "lines_removed": total_lines.get("removed", 0),
                "error": None,
            }
        except Exception as e:
            return {
                "summary": "",
                "mode": mode,
                "base_branch": None,
                "files": [],
                "file_count": 0,
                "unit_count": 0,
                "lines_added": 0,
                "lines_removed": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_diff_files(
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取变更文件列表及其详细信息。
        
        Args:
            project_root: 项目根目录
            mode: Diff模式
            
        Returns:
            Dict: {
                "files": List[{
                    "path": str,
                    "language": str,
                    "change_type": str,
                    "lines_added": int,
                    "lines_removed": int,
                    "tags": List[str]
                }],
                "error": str | None
            }
        """
        try:
            diff_mode = DiffMode(mode) if mode != "auto" else DiffMode.AUTO
            diff_ctx = collect_diff_context(mode=diff_mode, cwd=project_root)
            
            files_info = []
            review_index = diff_ctx.review_index
            
            for file_entry in review_index.get("files", []):
                metrics = file_entry.get("metrics", {})
                path = file_entry.get("path")
                # 移除 git diff 输出中可能存在的 a/ 或 b/ 前缀（防御性处理）
                #早期设计设计失误
                if path:
                    if path.startswith("a/"): path = path[2:]
                    elif path.startswith("b/"): path = path[2:]
                
                files_info.append({
                    "path": path,
                    "language": file_entry.get("language", "unknown"),
                    "change_type": file_entry.get("change_type", "modify"),
                    "lines_added": metrics.get("added_lines", 0),
                    "lines_removed": metrics.get("removed_lines", 0),
                    "tags": file_entry.get("tags", []),
                })
            
            return {
                "files": files_info,
                "detected_mode": diff_ctx.mode.value,
                "error": None,
            }
        except Exception as e:
            return {
                "files": [],
                "detected_mode": mode,
                "error": str(e),
            }
    
    @staticmethod
    def get_review_units(
        project_root: Optional[str] = None,
        mode: str = "auto",
        file_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取审查单元列表。
        
        Args:
            project_root: 项目根目录
            mode: Diff模式
            file_filter: 可选的文件路径过滤（仅返回匹配的单元）
            
        Returns:
            Dict: {
                "units": List[{
                    "unit_id": str,
                    "file_path": str,
                    "location": str,
                    "lines_added": int,
                    "lines_removed": int,
                    "tags": List[str],
                    "rule_context_level": str,
                    "rule_confidence": float
                }],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            diff_mode = DiffMode(mode) if mode != "auto" else DiffMode.AUTO
            diff_ctx = collect_diff_context(mode=diff_mode, cwd=project_root)
            
            units_info = []
            for unit in diff_ctx.review_index.get("units", []):
                file_path = unit.get("file_path", "")
                
                # 应用文件过滤
                if file_filter and file_filter not in file_path:
                    continue
                
                line_numbers = unit.get("line_numbers", {})
                location = line_numbers.get("new_compact") or line_numbers.get("old_compact") or ""
                
                metrics = unit.get("metrics", {})
                
                units_info.append({
                    "unit_id": unit.get("unit_id"),
                    "file_path": file_path,
                    "location": location,
                    "lines_added": metrics.get("added_lines", 0),
                    "lines_removed": metrics.get("removed_lines", 0),
                    "tags": unit.get("tags", []),
                    "rule_context_level": unit.get("rule_context_level", "diff_only"),
                    "rule_confidence": unit.get("rule_confidence", 0.0),
                })
            
            return {
                "units": units_info,
                "total_count": len(units_info),
                "error": None,
            }
        except Exception as e:
            return {
                "units": [],
                "total_count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_file_diff(
        file_path: str,
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取单个文件的Diff详情。
        
        Args:
            file_path: 文件路径
            project_root: 项目根目录
            mode: Diff模式
            
        Returns:
            Dict: {
                "file_path": str,
                "diff_text": str,
                "hunks": List[{...}],
                "error": str | None
            }
        """
        try:
            diff_mode = DiffMode(mode) if mode != "auto" else DiffMode.AUTO
            diff_text, actual_mode, base_branch = get_diff_text(diff_mode, cwd=project_root)
            
            if not PatchSet:
                return {
                    "file_path": file_path,
                    "diff_text": "",
                    "hunks": [],
                    "error": "unidiff package not installed",
                }
            
            patch = PatchSet(diff_text)
            
            # 查找目标文件
            target_file = None
            
            def normalize_path(p: str) -> str:
                """规范化路径，移除各种前缀"""
                if not p:
                    return ""
                p = p.replace("\\", "/")
                # 移除 git diff 标准前缀 a/ 和 b/
                if p.startswith("a/"):
                    p = p[2:]
                elif p.startswith("b/"):
                    p = p[2:]
                # 移除 ./ 或 / 前缀
                if p.startswith("./"):
                    p = p[2:]
                elif p.startswith("/"):
                    p = p[1:]
                return p
            
            normalized_file_path = normalize_path(file_path)
            
            for patched_file in patch:
                source_path = normalize_path(patched_file.source_file)
                target_path = normalize_path(patched_file.target_file)
                patched_path = normalize_path(patched_file.path) if patched_file.path else ""
                
                # 尝试多种匹配策略
                # 1. 精确匹配 target_file
                if target_path == normalized_file_path:
                    target_file = patched_file
                    break
                # 2. 精确匹配 source_file (对于删除或重命名)
                if source_path == normalized_file_path:
                    target_file = patched_file
                    break
                # 3. 精确匹配 patched_file.path
                if patched_path == normalized_file_path:
                    target_file = patched_file
                    break
                # 4. 路径后缀匹配 (应对路径可能有额外前缀的情况)
                if target_path.endswith("/" + normalized_file_path) or target_path.endswith(normalized_file_path):
                    target_file = patched_file
                    break
                if source_path.endswith("/" + normalized_file_path) or source_path.endswith(normalized_file_path):
                    target_file = patched_file
                    break
                # 5. 反向后缀匹配 (file_path 可能比 diff 中的路径更长)
                if normalized_file_path.endswith("/" + target_path) or normalized_file_path.endswith(target_path):
                    target_file = patched_file
                    break
            
            if not target_file:
                available_files = []
                for p in patch:
                    tgt = normalize_path(p.target_file)
                    available_files.append(tgt)
                
                debug_info = f"Available files: {', '.join(available_files[:10])}" if available_files else "No files in patch"
                
                return {
                    "file_path": file_path,
                    "diff_text": "",
                    "hunks": [],
                    "error": f"File '{normalized_file_path}' not found in diff. {debug_info}",
                }
            
            hunks = []
            for hunk in target_file:
                hunks.append({
                    "source_start": hunk.source_start,
                    "source_length": hunk.source_length,
                    "target_start": hunk.target_start,
                    "target_length": hunk.target_length,
                    "content": str(hunk),
                })
            
            return {
                "file_path": file_path,
                "diff_text": str(target_file),
                "hunks": hunks,
                "error": None,
            }
        except Exception as e:
            return {
                "file_path": file_path,
                "diff_text": "",
                "hunks": [],
                "error": str(e),
            }


__all__ = [
    "DiffAPI",
    "DiffStatus",
]
