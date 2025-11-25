"""Diff 感知层：收集 git diff、解析 PatchSet 并构建审查单元供后续规划/审查使用。"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import json
from datetime import datetime
from collections import defaultdict
import uuid
import textwrap
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from unidiff import PatchSet

import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 导入规则层（DIFF/rule 包）
try:
    from DIFF.rule.context_decision import (
        build_rule_suggestion,
        decide_context,
        build_decision_from_rules,
    )
    RULES_AVAILABLE = True
except ImportError as exc:
    RULES_AVAILABLE = False
    print(f"[警告] 规则层模块未找到，将跳过规则决策: {exc}")


class DiffMode(str, Enum):
    """支持的 diff 模式。"""

    WORKING = "working"
    STAGED = "staged"
    PR = "pr"
    AUTO = "auto"


_GIT_REPO_VERIFIED = False


def ensure_git_repository() -> None:
    """确保当前目录在 git 仓库内，否则拒绝继续。"""

    global _GIT_REPO_VERIFIED
    if _GIT_REPO_VERIFIED:
        return

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or "Current directory is not a git repository."
        raise RuntimeError(f"Git repository check failed: {error}")

    _GIT_REPO_VERIFIED = True


def run_git(*args: str) -> str:
    """运行 git 命令并返回标准输出。"""

    ensure_git_repository()
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        cmd = " ".join(["git", *args])
        raise RuntimeError(f"Git command failed ({cmd}): {stderr}")
    return result.stdout


def _run_git_quiet(*args: str) -> subprocess.CompletedProcess[str]:
    """运行 git 命令并通过返回码传递状态。"""

    ensure_git_repository()
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )


def has_working_changes() -> bool:
    """如果工作区有未暂存变更则返回 True。"""

    result = _run_git_quiet("diff", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --quiet failed."
    raise RuntimeError(error)


def has_staged_changes() -> bool:
    """如果暂存区存在未提交变更则返回 True。"""

    result = _run_git_quiet("diff", "--cached", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --cached --quiet failed."
    raise RuntimeError(error)


def detect_base_branch() -> str:
    """在常见默认分支中检测基线分支名称。"""

    output = run_git("branch", "--list")
    branches = {
        line.replace("*", "").strip()
        for line in output.splitlines()
        if line.strip()
    }
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    raise RuntimeError("Unable to detect base branch (main/master not found).")


def branch_has_pr_changes(base_branch: str) -> bool:
    """检查当前 HEAD 是否领先于 origin/<base_branch>。"""

    try:
        run_git("fetch", "origin", base_branch)
    except RuntimeError:
        return False

    output = run_git(
        "rev-list",
        "--left-right",
        "--count",
        f"origin/{base_branch}...HEAD",
    ).strip()
    if not output:
        return False

    parts = output.split()
    if len(parts) < 2:
        return False

    try:
        ahead = int(parts[1])
    except ValueError:
        return False

    return ahead > 0


def auto_detect_mode() -> DiffMode:
    """根据仓库状态决定最佳 diff 模式。"""

    if has_staged_changes():
        return DiffMode.STAGED
    if has_working_changes():
        return DiffMode.WORKING

    base_branch = detect_base_branch()
    if branch_has_pr_changes(base_branch):
        return DiffMode.PR

    raise RuntimeError("No changes detected for working, staged, or PR diff modes.")


def get_diff_text(
    mode: DiffMode,
    base_branch: Optional[str] = None,
) -> Tuple[str, DiffMode, Optional[str]]:
    """按模式获取 diff 文本，返回实际模式与基线分支。"""

    if mode == DiffMode.AUTO:
        detected = auto_detect_mode()
        return get_diff_text(detected, base_branch)

    if mode == DiffMode.WORKING:
        return run_git("diff"), DiffMode.WORKING, None

    if mode == DiffMode.STAGED:
        return run_git("diff", "--cached"), DiffMode.STAGED, None

    if mode == DiffMode.PR:
        actual_base = base_branch or detect_base_branch()
        try:
            run_git("fetch", "origin", actual_base)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to fetch base branch '{actual_base}': {exc}"
            ) from exc
        diff_text = run_git("diff", f"origin/{actual_base}...HEAD")
        return diff_text, DiffMode.PR, actual_base

    raise ValueError(f"Unsupported diff mode: {mode}")


def read_file_lines(path: str) -> List[str]:
    """Read file contents into a list of lines without newline characters.

    设计目标：
    - 对非文本 / 非 UTF-8 文件保持健壮，不让整个审查流程崩溃。
    - 尽量优先按 UTF-8 读取，失败时降级为“忽略错误”的宽松模式。
    """

    file_path = Path(path)
    if not file_path.exists():
        return []

    try:
        # 先判断是否可能是二进制文件：简单检查前 4KB 是否包含 NUL 字节
        head = file_path.read_bytes()[:4096]
        if b"\x00" in head:
            # 对于明显的二进制文件，直接跳过，避免无意义的解码尝试
            print(f"[diff] 跳过二进制文件: {path}")
            return []
    except OSError as exc:
        print(f"[diff] 读取文件失败（跳过）: {path}: {exc}")
        return []

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 对于非 UTF-8 文本，使用宽松模式读取，防止抛错
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            print(f"[diff] 非 UTF-8 文本，已使用 errors='ignore' 读取: {path}")
        except Exception as exc:  # pragma: no cover - 极端情况
            print(f"[diff] 文本读取失败（跳过）: {path}: {exc}")
            return []

    return text.splitlines()


def parse_python_ast(file_lines: List[str]) -> Optional[ast.AST]:
    """预先解析 Python 源码供后续辅助函数复用。"""

    if not file_lines:
        return None
    try:
        return ast.parse("\n".join(file_lines))
    except SyntaxError:
        return None


def extract_unified_diff_view(hunk) -> str:
    """生成类似 git diff 的统一视图，更易于理解变更。"""
    lines = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type == "+":
            lines.append(f"+{content}") #优化空格，减少token消耗
        elif line.line_type == "-":
            lines.append(f"-{content}")
        elif line.line_type == " ":
            lines.append(f" {content}")
    return "\n".join(lines)


def detect_code_structure(
    file_lines: List[str],
    line_num: int,
    language: str,
    ast_tree: Optional[ast.AST],
) -> Optional[Dict[str, Any]]:
    """检测代码所在的结构（函数、类、if-else等）。
    
    Args:
        file_lines: 文件所有行
        line_num: 目标行号（1-based）
        language: 编程语言
    
    Returns:
        包含结构信息的字典，如 {"type": "function", "start": 10, "end": 20, "name": "process"}
    """
    if language != "python" or ast_tree is None:
        return None
    
    # 遍历 AST 查找包含目标行的节点
    for node in ast.walk(ast_tree):
        if not hasattr(node, 'lineno'):
            continue
        
        start = node.lineno # 报错不用管，适配 Python 3.8+
        end = getattr(node, 'end_lineno', start)
        
        if start <= line_num <= end:
            # 检测函数定义
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return {
                    "type": "function",
                    "name": node.name,
                    "start": start,
                    "end": end,
                    "importance": "high"
                }
            # 检测类定义
            elif isinstance(node, ast.ClassDef):
                return {
                    "type": "class",
                    "name": node.name,
                    "start": start,
                    "end": end,
                    "importance": "high"
                }
            # 检测条件语句
            elif isinstance(node, ast.If):
                return {
                    "type": "if_statement",
                    "start": start,
                    "end": end,
                    "importance": "medium"
                }
            # 检测循环
            elif isinstance(node, (ast.For, ast.While)):
                return {
                    "type": "loop",
                    "start": start,
                    "end": end,
                    "importance": "medium"
                }
            # 检测 try-except
            elif isinstance(node, ast.Try):
                return {
                    "type": "try_except",
                    "start": start,
                    "end": end,
                    "importance": "high"
                }
    
    return None


def extract_changed_symbols(hunk) -> Set[str]:
    """提取变更中涉及的符号（函数名、变量名等）。"""
    symbols = set()
    
    for line in hunk:
        if line.line_type not in ("+", "-"):
            continue
        
        content = line.value.strip()
        # 提取函数调用: func_name(
        func_calls = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', content)
        symbols.update(func_calls)
        
        # 提取赋值: var_name =
        assignments = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=', content)
        symbols.update(assignments)
        
        # 提取属性访问: obj.attr
        attributes = re.findall(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', content)
        symbols.update(attributes)
    
    return symbols


def _is_import_line(content: str, language: str) -> bool:
    """若该行仅包含导入语句则返回 True。"""

    stripped = content.strip()
    if not stripped:
        return False
    if language == "python":
        return stripped.startswith("import ") or stripped.startswith("from ")
    if language in {"javascript", "typescript"}:
        return stripped.startswith("import ") or stripped.startswith("require(")
    return False


def _is_comment_line(content: str, language: str) -> bool:
    """若该行仅包含注释则返回 True。"""

    stripped = content.strip()
    if not stripped:
        return False
    if language == "python":
        return stripped.startswith("#")
    if language in {"javascript", "typescript"}:
        return stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*")
    return False


def _is_logging_line(content: str, language: str) -> bool:
    """若该行主要是日志语句则返回 True。"""

    stripped = content.strip()
    if not stripped:
        return False
    if language == "python":
        logging_tokens = (
            "logging.",
            "logger.",
            "log.info",
            "log.warning",
            "log.error",
            "log.debug",
        )
        return any(token in stripped for token in logging_tokens)
    return False


def infer_simple_change_tags(hunk, language: str) -> List[str]:
    """从变更行推断 only_imports/only_comments/only_logging 等标签。"""

    changed_lines: List[str] = []
    for line in hunk:
        if line.line_type not in ("+", "-"):
            continue
        changed_lines.append(line.value.rstrip("\n"))

    if not changed_lines:
        return []

    has_code_like = False
    has_import = False
    has_comment = False
    has_logging = False

    for content in changed_lines:
        stripped = content.strip()
        if not stripped:
            continue

        is_import = _is_import_line(content, language)
        is_comment = _is_comment_line(content, language)
        is_logging = _is_logging_line(content, language)

        has_import = has_import or is_import
        has_comment = has_comment or is_comment
        has_logging = has_logging or is_logging

        if not (is_import or is_comment or is_logging):
            has_code_like = True

    tags: List[str] = []
    if has_import and not has_code_like:
        tags.append("only_imports")
    if has_comment and not has_code_like and not has_import:
        tags.append("only_comments")
    if has_logging and not has_code_like and not has_import:
        tags.append("only_logging")
    return tags


def infer_file_level_tags(file_path: str, language: str) -> List[str]:
    """从文件路径推断 config_file/routing_file/security_sensitive 等标签。"""

    tags: List[str] = []
    lower_path = file_path.lower()
    filename = Path(file_path).name.lower()

    # 配置类文件。
    if any(key in filename for key in ("config", "settings", "conf")) or filename in {
        "pyproject.toml",
        "setup.cfg",
        "requirements.txt",
        "package.json",
        "tsconfig.json",
    }:
        tags.append("config_file")

    # 路由/URL/路由定义。
    if any(key in filename for key in ("router", "routes", "routing")) or filename in {
        "urls.py",
    }:
        tags.append("routing_file")

    # 基于路径启发式判断安全敏感。
    if any(key in lower_path for key in ("auth", "login", "permission", "acl", "security", "oauth", "sso")):
        tags.append("security_sensitive")

    return tags


def infer_symbol_and_scope_tag(
    language: str,
    file_ast: Optional[ast.AST],
    file_lines: List[str],
    new_start: int,
    new_end: int,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """推断符号信息以及 in_single_function 等作用域标签。"""

    if language != "python" or file_ast is None or not file_lines:
        return None, []

    mid_line = max(new_start, 1)
    structure = detect_code_structure(file_lines, mid_line, language, file_ast)
    if not structure:
        return None, []

    struct_type = structure.get("type")
    struct_start = structure.get("start", new_start)
    struct_end = structure.get("end", new_end)

    symbol: Optional[Dict[str, Any]] = None
    tags: List[str] = []

    if struct_type == "function":
        symbol = {
            "kind": "function",
            "name": structure.get("name", ""),
            "start_line": struct_start,
            "end_line": struct_end,
        }
        if struct_start <= new_start and new_end <= struct_end:
            tags.append("in_single_function")
    elif struct_type == "class":
        symbol = {
            "kind": "class",
            "name": structure.get("name", ""),
            "start_line": struct_start,
            "end_line": struct_end,
        }

    return symbol, tags


def find_symbol_definitions(
    file_lines: List[str],
    symbols: Set[str],
    language: str,
    ast_tree: Optional[ast.AST],
) -> List[Dict[str, Any]]:
    """在文件中查找符号的定义位置。"""
    if language != "python" or not symbols or ast_tree is None:
        return []
    
    definitions = []
    
    for node in ast.walk(ast_tree):
        # 函数定义
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in symbols:
                definitions.append({
                    "type": "function",
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, 'end_lineno', node.lineno)
                })
        # 类定义
        elif isinstance(node, ast.ClassDef):
            if node.name in symbols:
                definitions.append({
                    "type": "class",
                    "name": node.name,
                    "start": node.lineno,
                    "end": getattr(node, 'end_lineno', node.lineno)
                })
    
    return definitions


def smart_expand_context(
    file_lines: List[str],
    hunk,
    initial_start: int,
    initial_end: int,
    language: str,
    ast_tree: Optional[ast.AST],
) -> Tuple[int, int, List[str]]:
    """智能扩展上下文：根据代码结构、逻辑和定义进行扩展。
    
    Returns:
        (扩展后起始行, 扩展后结束行, 扩展标签列表)
    """
    tags = []
    final_start = initial_start
    final_end = initial_end
    
    # 策略1: 递归检查相邻行是否也有修改
    changed_lines = set()
    for line in hunk:
        if line.line_type in ("+", "-") and hasattr(line, 'target_line_no'):
            if line.target_line_no:
                changed_lines.add(line.target_line_no)
    
    if changed_lines:
        min_changed = min(changed_lines)
        max_changed = max(changed_lines)
        # 如果多个改动在 10 行内，扩展到覆盖所有改动
        if max_changed - min_changed <= 10:
            final_start = min(final_start, min_changed)
            final_end = max(final_end, max_changed)
            tags.append("clustered_changes")
    
    # 策略2: 检测代码结构，扩展到完整的逻辑单元
    mid_line = (final_start + final_end) // 2
    structure = detect_code_structure(file_lines, mid_line, language, ast_tree)
    
    if structure:
        struct_start = structure["start"]
        struct_end = structure["end"]
        
        # 如果修改在结构内，考虑扩展到整个结构
        if structure["importance"] == "high":
            # 高重要性：函数、类、异常处理 - 扩展到完整结构
            final_start = min(final_start, struct_start)
            final_end = max(final_end, struct_end)
            tags.append(f"complete_{structure['type']}")
        elif structure["importance"] == "medium" and (struct_end - struct_start) < 15:
            # 中等重要性且不太长：条件、循环 - 扩展到完整结构
            final_start = min(final_start, struct_start)
            final_end = max(final_end, struct_end)
            tags.append(f"complete_{structure['type']}")
    
    # 策略3: 查找引用的符号定义
    symbols = extract_changed_symbols(hunk)
    if symbols:
        definitions = find_symbol_definitions(file_lines, symbols, language, ast_tree)
        tags.append(f"references:{','.join(list(symbols)[:3])}")
        
        # 如果定义在附近（50行内），包含它们
        for defn in definitions:
            if abs(defn["start"] - final_start) <= 50:
                final_start = min(final_start, defn["start"])
                final_end = max(final_end, defn["end"])
                tags.append(f"includes_{defn['type']}_{defn['name']}")
    
    # 确保范围有效
    final_start = max(1, final_start)
    final_end = min(len(file_lines), final_end)
    
    return final_start, final_end, tags


def merge_nearby_hunks(
    units: List[Dict[str, Any]],
    file_lines: Optional[List[str]] = None,
    max_gap: int = 20,
) -> List[Dict[str, Any]]:
    """合并距离很近的 hunk，避免碎片化。
    
    Args:
        units: 同一文件的审查单元列表
        file_lines: 用于重新提取上下文的完整文件内容
        max_gap: 最大行间隔，小于此值的 hunk 会被合并
    
    Returns:
        合并后的审查单元列表
    """
    if len(units) <= 1:
        return units
    
    # 按行号排序
    sorted_units = sorted(units, key=lambda u: u["hunk_range"]["new_start"])
    
    merged: List[Dict[str, Any]] = []
    current_group = [sorted_units[0]]
    
    for unit in sorted_units[1:]:
        prev_unit = current_group[-1]
        prev_end = prev_unit["hunk_range"]["new_start"] + prev_unit["hunk_range"]["new_lines"]
        curr_start = unit["hunk_range"]["new_start"]
        
        # 如果间隔小于阈值，加入当前组
        if curr_start - prev_end <= max_gap:
            current_group.append(unit)
        else:
            # 否则合并当前组，开始新组
            if len(current_group) > 1:
                merged.append(merge_unit_group(current_group, file_lines))
            else:
                merged.append(current_group[0])
            current_group = [unit]
    
    # 处理最后一组
    if len(current_group) > 1:
        merged.append(merge_unit_group(current_group, file_lines))
    else:
        merged.append(current_group[0])
    
    return merged


def merge_unit_group(
    group: List[Dict[str, Any]],
    file_lines: Optional[List[str]],
) -> Dict[str, Any]:
    """合并一组 hunk 为单个审查单元。"""
    first = group[0]
    last = group[-1]
    
    # 合并 unified_diff
    all_diffs = [u["unified_diff"] for u in group]
    merged_diff = "\n...\n".join(all_diffs)
    
    # 计算总的行变更
    total_added = sum(u["metrics"]["added_lines"] for u in group)
    total_removed = sum(u["metrics"]["removed_lines"] for u in group)
    
    # 计算新的范围
    def _range_end(unit: Dict[str, Any], key: str) -> int:
        start = unit["hunk_range"][f"{key}_start"]
        length = unit["hunk_range"][f"{key}_lines"]
        if start <= 0:
            return start
        return start + max(length - 1, 0)

    new_starts = []
    for unit in group:
        start_val = unit["hunk_range"]["new_start"]
        if start_val > 0:
            new_starts.append(start_val)
    new_start = min(new_starts) if new_starts else 1
    new_end_candidates = []
    for unit in group:
        candidate = _range_end(unit, "new")
        if candidate > 0:
            new_end_candidates.append(candidate)
    new_end = max(new_end_candidates) if new_end_candidates else new_start

    old_starts = []
    for unit in group:
        start_val = unit["hunk_range"]["old_start"]
        if start_val > 0:
            old_starts.append(start_val)
    old_start = min(old_starts) if old_starts else first["hunk_range"]["old_start"]
    old_end_candidates = []
    for unit in group:
        candidate = _range_end(unit, "old")
        if candidate > 0:
            old_end_candidates.append(candidate)
    old_end = max(old_end_candidates) if old_end_candidates else old_start

    # 重新提取上下文以覆盖合并后的范围
    if file_lines:
        context_snippet, ctx_start, ctx_end = extract_context(
            file_lines, new_start, new_end
        )
    else:
        context_snippet = "\n...\n".join(u["code_snippets"]["context"] for u in group if u["code_snippets"]["context"])
        ctx_start = first["code_snippets"]["context_start"]
        ctx_end = last["code_snippets"]["context_end"]

    combined_tags = sorted({tag for unit in group for tag in unit.get("tags", [])})
    if any(unit.get("is_merged") for unit in group):
        combined_tags.append("merged_block")
        combined_tags = sorted(set(combined_tags))
    
    return {
        "id": first["id"],
        "file_path": first["file_path"],
        "language": first["language"],
        "change_type": first["change_type"],
        "unified_diff": merged_diff,
        "hunk_range": {
            "new_start": new_start,
            "new_lines": max(new_end - new_start + 1, first["hunk_range"]["new_lines"]),
            "old_start": old_start,
            "old_lines": max(old_end - old_start + 1, first["hunk_range"]["old_lines"]),
        },
        "code_snippets": {
            "before": "\n...\n".join(u["code_snippets"]["before"] for u in group),
            "after": "\n...\n".join(u["code_snippets"]["after"] for u in group),
            "context": context_snippet,
            "context_start": ctx_start,
            "context_end": ctx_end,
        },
        "tags": combined_tags,
        "metrics": {
            "added_lines": total_added,
            "removed_lines": total_removed,
            "hunk_count": len(group),
        },
        "is_merged": True,
        "merged_count": len(group)
    }


def extract_before_after_from_hunk(hunk) -> Tuple[str, str]:
    """从 hunk 中提取变更前后的片段。"""

    before_lines: List[str] = []
    after_lines: List[str] = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type in ("-", " "):
            before_lines.append(content)
        if line.line_type in ("+", " "):
            after_lines.append(content)
    return "\n".join(before_lines), "\n".join(after_lines)


def extract_context(
    full_lines: List[str],
    new_start: int,
    new_end: int,
    before: int = 20,
    after: int = 20,
) -> Tuple[str, int, int]:
    """从新文件行中提取周围上下文。"""

    if not full_lines:
        ctx_start = new_start if new_start > 0 else 0
        ctx_end = new_end if new_end > 0 else ctx_start
        return "", ctx_start, ctx_end

    start_idx = max(1, new_start if new_start > 0 else 1)
    end_idx = max(start_idx, new_end if new_end > 0 else start_idx)
    ctx_start = max(1, start_idx - before)
    ctx_end = min(len(full_lines), end_idx + after)
    context_lines = full_lines[ctx_start - 1 : ctx_end]
    return "\n".join(context_lines), ctx_start, ctx_end


DOC_EXTENSIONS = {".md", ".rst", ".txt"}


def guess_language(path: str) -> str:
    """基于文件扩展名猜测编程语言。"""

    ext = Path(path).suffix.lower()
    if ext in DOC_EXTENSIONS:
        return "text"
    if ext == ".py":
        return "python"
    if ext in {".js", ".ts", ".jsx", ".tsx"}:
        return "javascript"
    if ext == ".java":
        return "java"
    if ext == ".go":
        return "go"
    return "unknown"


def _truncate_doc_block(text: str, max_lines: int = 40) -> str:
    """最多返回 max_lines 行，并在末尾放置清晰的占位标记。"""

    lines = text.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    # 保留 max_lines-1 行，再加一个截断标记，不修改原始列表
    truncated_lines = lines[: max_lines - 1] + ["...(truncated)"]
    return "\n".join(truncated_lines)


def _apply_rules_to_units(units: List[Dict[str, Any]]) -> None:
    """为审查单元附加规则建议/决策；规则缺失时填充占位值。"""

    if not units:
        return
    if not RULES_AVAILABLE:
        for unit in units:
            unit["rule_suggestion"] = {
                "context_level": "unknown",
                "confidence": 0.0,
                "notes": "rule_unavailable",
            }
            unit["rule_context_level"] = "unknown"
            unit["rule_confidence"] = 0.0
            unit["rule_notes"] = "rule_unavailable"
        return

    def _normalize_context_level(level: str) -> str:
        """将规则层的上下文级别映射到统一的 review_index 语义。"""
        if level == "local":
            return "diff_only"
        if level == "function":
            return "function"
        if level == "file":
            return "file_context"
        return "unknown"

    for unit in units:
        rule_unit = {
            "file_path": unit.get("file_path", ""),
            "language": unit.get("language", "unknown"),
            "change_type": unit.get("change_type", "modify"),
            "metrics": unit.get("metrics", {}),
            "tags": unit.get("tags", []),
            "symbol": unit.get("symbol"),
        }
        try:
            suggestion = build_rule_suggestion(rule_unit)
            unit["rule_suggestion"] = suggestion
            unit["rule_context_level"] = _normalize_context_level(
                str(suggestion.get("context_level", "unknown"))
            )
            unit["rule_confidence"] = float(suggestion.get("confidence", 0.0))
            unit["rule_notes"] = suggestion.get("notes")
        except Exception as exc:
            unit["rule_suggestion"] = {
                "context_level": "unknown",
                "confidence": 0.0,
                "notes": f"rule_error:{exc}",
            }
            unit["rule_context_level"] = "unknown"
            unit["rule_confidence"] = 0.0
            unit["rule_notes"] = f"rule_error:{exc}"
            continue

        try:
            decision = decide_context(rule_unit)
            unit["agent_decision"] = decision
        except NotImplementedError:
            decision = build_decision_from_rules(rule_unit, suggestion)
            unit["agent_decision"] = decision
        except Exception as exc:  # pragma: no cover - 防御性兜底
            unit["agent_decision"] = {
                "context_level": "function",
                "before_lines": 8,
                "after_lines": 8,
                "focus": ["logic", "security"],
                "priority": "medium",
                "reason": f"rule_error:{exc}",
            }


def build_review_units_from_patch(
    patch: PatchSet, use_smart_context: bool = True, apply_rules: bool = True
) -> List[Dict[str, Any]]:
    """从 PatchSet 构建审查单元，可选智能上下文与规则层处理。"""

    units: List[Dict[str, Any]] = []
    for patched_file in patch:
        if patched_file.is_removed_file:
            continue

        file_path = patched_file.path
        # 处理 Git 转义的文件路径（如 "\346\226\207\344\273\266.md"）
        if file_path.startswith('"') and file_path.endswith('"'):
            try:
                file_path = file_path[1:-1].encode('latin1').decode('unicode_escape').encode('latin1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                file_path = file_path.strip('"')
        full_lines = read_file_lines(file_path)
        change_type = "add" if patched_file.is_added_file else "modify"
        language = guess_language(file_path)
        is_doc_file = language == "text"
        file_ast: Optional[ast.AST] = None
        if language == "python" and full_lines:
            file_ast = parse_python_ast(full_lines)

        base_tags = infer_file_level_tags(file_path, language)

        for hunk in patched_file:
            before_snippet, after_snippet = extract_before_after_from_hunk(hunk)
            unified_diff = extract_unified_diff_view(hunk)

            new_start = hunk.target_start if hunk.target_start > 0 else 1
            if hunk.target_length > 0:
                new_end = new_start + hunk.target_length - 1
            else:
                new_end = new_start

            # 使用智能上下文扩展
            tags: List[str] = list(base_tags)

            symbol_info, scope_tags = infer_symbol_and_scope_tag(
                language, file_ast, full_lines, new_start, new_end
            )
            tags.extend(scope_tags)
            if use_smart_context and language == "python" and full_lines:
                expanded_start, expanded_end, smart_tags = smart_expand_context(
                    full_lines, hunk, new_start, new_end, language, file_ast
                )
                tags.extend(smart_tags)
                
                # 使用扩展后的范围
                context_snippet = "\n".join(full_lines[expanded_start - 1 : expanded_end])
                ctx_start = expanded_start
                ctx_end = expanded_end
            else:
                # 降级到固定上下文
                context_snippet, ctx_start, ctx_end = extract_context(
                    full_lines, new_start, new_end
                )

            # 简单模式标签：only_imports/only_comments/only_logging
            tags.extend(infer_simple_change_tags(hunk, language))

            # 文本文档的上下文做截断，避免全文膨胀
            if is_doc_file:
                unified_diff = _truncate_doc_block(unified_diff, max_lines=60)
                before_snippet = _truncate_doc_block(before_snippet, max_lines=40)
                after_snippet = _truncate_doc_block(after_snippet, max_lines=40)
                context_snippet = _truncate_doc_block(context_snippet, max_lines=50)
                tags.append("doc_file")

            # 去重保持稳定顺序
            if tags:
                # 保留首次出现的顺序。
                seen: Set[str] = set()
                deduped: List[str] = []
                for t in tags:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                tags = deduped

            added_lines = sum(1 for line in hunk if line.line_type == "+")
            removed_lines = sum(1 for line in hunk if line.line_type == "-")

            unit_id = str(uuid.uuid4())
            in_single_function = "in_single_function" in tags

            units.append(
                {
                    "id": unit_id,
                    "unit_id": unit_id,
                    "file_path": file_path,
                    "language": language,
                    "change_type": change_type,
                    "patch_type": change_type,
                    "context_mode": "doc_light" if is_doc_file else None,
                    "unified_diff": unified_diff,
                    "hunk_range": {
                        "old_start": hunk.source_start,
                        "old_lines": hunk.source_length,
                        "new_start": hunk.target_start,
                        "new_lines": hunk.target_length,
                    },
                    "code_snippets": {
                        "before": before_snippet,
                        "after": after_snippet,
                        "context": context_snippet,
                        "context_start": ctx_start,
                        "context_end": ctx_end,
                    },
                    "tags": tags,
                    "symbol": symbol_info,
                    "metrics": {
                        "added_lines": added_lines,
                        "removed_lines": removed_lines,
                        "hunk_count": 1,
                        "in_single_function": in_single_function,
                    },
                }
            )

    if apply_rules:
        _apply_rules_to_units(units)

    return units


def main() -> None:
    """CLI 入口。"""

    parser = argparse.ArgumentParser(
        description="AI Code Review - Diff Collector"
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in DiffMode],
        default=DiffMode.AUTO.value,
        help="diff 模式：working / staged / pr / auto（默认 auto）",
    )
    args = parser.parse_args()

    mode = DiffMode(args.mode)

    try:
        diff_text, actual_mode, base = get_diff_text(mode)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print(f"[感知层] 使用模式: {actual_mode.value}")
    if actual_mode == DiffMode.PR and base is not None:
        print(f"[感知层] 基线分支: {base} (origin/{base}...HEAD)")

    if not diff_text.strip():
        print("没有检测到任何变更。")
        raise SystemExit(0)

    patch = PatchSet(diff_text)
    units = build_review_units_from_patch(patch)
    print(f"[感知层] 构建审查单元数量: {len(units)}")
    if RULES_AVAILABLE and units:
        high_confidence = sum(
            1
            for u in units
            if u.get("rule_suggestion", {}).get("confidence", 0) >= 0.8
        )
        print(
            f"[规则层] 已附加规则决策，高置信度: {high_confidence}/{len(units)} "
            f"({high_confidence*100//len(units)}%)"
        )
    
    if units:
        llm_friendly_output = build_llm_friendly_output(units, actual_mode, base)

        log_dir = Path("log") / "diff_log"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        llm_output_file = log_dir / f"review_for_llm_{timestamp}.json"
        raw_output_file = log_dir / f"review_raw_{timestamp}.json"

        with open(llm_output_file, "w", encoding="utf-8") as f:
            json.dump(llm_friendly_output, f, ensure_ascii=False, indent=2)

        with open(raw_output_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mode": actual_mode.value,
                    "base_branch": base,
                    "total_units": len(units),
                    "units": units,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n[感知层] 已保存 LLM 友好格式: {llm_output_file}")
        print(f"[感知层] 已保存原始格式: {raw_output_file}")
        
        # 打印摘要
        print(f"\n[摘要] 变更概览：")
        print(f"  - 修改文件数: {llm_friendly_output['summary']['changes_by_type']['modify']}")
        print(f"  - 新增文件数: {llm_friendly_output['summary']['changes_by_type']['add']}")
        print(f"  - 总新增行: +{llm_friendly_output['summary']['total_lines']['added']}")
        print(f"  - 总删除行: -{llm_friendly_output['summary']['total_lines']['removed']}")
if __name__ == "__main__":
    main()


def build_review_index(
    units: List[Dict[str, Any]],
    actual_mode: DiffMode,
    base: Optional[str],
) -> Dict[str, Any]:
    """构建轻量的“审查单元索引”（无上下文/大段 diff）。"""

    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in units:
        files_dict[unit["file_path"]].append(unit)

    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in units),
        "removed": sum(u["metrics"]["removed_lines"] for u in units),
    }
    changes_by_type = {"add": 0, "modify": 0, "delete": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0].get("change_type", "modify")
        if change_kind in changes_by_type:
            changes_by_type[change_kind] += 1

    file_entries: List[Dict[str, Any]] = []
    units_index: List[Dict[str, Any]] = []
    for file_path in sorted(files_dict.keys()):
        file_units = files_dict[file_path]
        file_tags = sorted({tag for u in file_units for tag in u.get("tags", [])})
        file_added = sum(u["metrics"]["added_lines"] for u in file_units)
        file_removed = sum(u["metrics"]["removed_lines"] for u in file_units)

        changes: List[Dict[str, Any]] = []
        for unit in file_units:
            hunk_range = unit.get("hunk_range", {})
            changes.append(
                {
                    "id": unit.get("id"),
                    "unit_id": unit.get("unit_id") or unit.get("id"),
                    "rule_context_level": unit.get("rule_context_level"),
                    "rule_confidence": unit.get("rule_confidence"),
                    "rule_notes": unit.get("rule_notes"),
                    "hunk_range": hunk_range,
                    "metrics": unit.get("metrics", {}),
                    "tags": unit.get("tags", []),
                    "context_mode": unit.get("context_mode"),
                    "symbol": unit.get("symbol"),
                    "rule_suggestion": unit.get("rule_suggestion"),
                    "agent_decision": unit.get("agent_decision"),
                }
            )
            units_index.append(
                {
                    "unit_id": unit.get("unit_id") or unit.get("id"),
                    "file_path": file_path,
                    "patch_type": unit.get("patch_type") or unit.get("change_type"),
                    "tags": unit.get("tags", []),
                    "metrics": unit.get("metrics", {}),
                    "rule_context_level": unit.get("rule_context_level"),
                    "rule_confidence": unit.get("rule_confidence"),
                }
            )

        file_entries.append(
            {
                "path": file_path,
                "language": file_units[0].get("language", "unknown"),
                "change_type": file_units[0].get("change_type", "modify"),
                "metrics": {
                    "added_lines": file_added,
                    "removed_lines": file_removed,
                    "changes": len(changes),
                },
                "tags": file_tags,
                "changes": changes,
            }
        )

    return {
        "review_metadata": {
            "mode": actual_mode.value,
            "base_branch": base,
            "total_files": len(files_dict),
            "total_changes": len(units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "changes_by_type": changes_by_type,
            "total_lines": total_lines_summary,
            "files_changed": sorted(files_dict.keys()),
        },
        "units": units_index,
        "files": file_entries,
    }


def build_llm_friendly_output(
    units: List[Dict[str, Any]],
    actual_mode: DiffMode,
    base: Optional[str],
) -> Dict[str, Any]:
    """构建供 LLM 使用的结构化 diff 视图（JSON 结构）。

    该函数在 CLI 模式和 Agent 上下文构建中复用，避免两套格式不一致。
    """

    # 按文件分组
    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in units:
        files_dict[unit["file_path"]].append(unit)

    file_type_counts = {"add": 0, "modify": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0]["change_type"]
        if change_kind in file_type_counts:
            file_type_counts[change_kind] += 1

    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in units),
        "removed": sum(u["metrics"]["removed_lines"] for u in units),
    }

    output: Dict[str, Any] = {
        "review_metadata": {
            "mode": actual_mode.value,
            "base_branch": base,
            "total_files": len(files_dict),
            "total_changes": len(units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "files_changed": list(files_dict.keys()),
            "changes_by_type": file_type_counts,
            "total_lines": total_lines_summary,
        },
        "files": [],
    }

    # 为每个文件构建清晰的变更描述
    for file_path, file_units in files_dict.items():
        file_info: Dict[str, Any] = {
            "path": file_path,
            "language": file_units[0]["language"],
            "change_type": file_units[0]["change_type"],
            "changes": [],
        }

        # 智能合并：如果多个 hunk 距离很近（<20 行），考虑合并
        file_lines_for_merge = read_file_lines(file_path)
        merged_units = merge_nearby_hunks(file_units, file_lines=file_lines_for_merge)

        for unit in merged_units:
            context_mode = unit.get("context_mode")
            # 获取完整上下文（不过度裁剪，LLM 需要足够信息）
            context = unit["code_snippets"]["context"]
            context_lines = context.split("\n") if context else []

            # 如果上下文超过 50 行，才进行裁剪
            if len(context_lines) > 50 and context_mode != "doc_light":
                hunk_range = unit["hunk_range"]
                start = hunk_range["new_start"]
                length = hunk_range["new_lines"]
                ctx_start = unit["code_snippets"]["context_start"]

                # 计算相对位置
                rel_start = start - ctx_start
                rel_end = rel_start + length

                # 保留前后 10 行（给 LLM 更多上下文）
                keep_start = max(0, rel_start - 10)
                keep_end = min(len(context_lines), rel_end + 10)

                trimmed = context_lines[keep_start:keep_end]
                if keep_start > 0:
                    trimmed.insert(0, "...")
                if keep_end < len(context_lines):
                    trimmed.append("...")
                context = "\n".join(trimmed)

            change = {
                "location": (
                    f"L{unit['hunk_range']['new_start']}-"
                    f"L{unit['hunk_range']['new_start'] + unit['hunk_range']['new_lines'] - 1}"
                ),
                "change_size": (
                    f"+{unit['metrics']['added_lines']}/"
                    f"-{unit['metrics']['removed_lines']}"
                ),
                "metrics": {
                    "added_lines": unit["metrics"]["added_lines"],
                    "removed_lines": unit["metrics"]["removed_lines"],
                },
                "unified_diff": unit.get("unified_diff", ""),
                "surrounding_context": (
                    context if context else "(no context available)"
                ),
                "tags": unit.get("tags", []),
                "structure_info": {
                    "before": unit["code_snippets"]["before"],
                    "after": unit["code_snippets"]["after"],
                },
                "rule_suggestion": unit.get("rule_suggestion"),
                "agent_decision": unit.get("agent_decision"),
            }

            if context_mode == "doc_light":
                change["surrounding_context"] = "(doc snippet)"
                change["structure_info"] = {
                    "before": "",
                    "after": unit["code_snippets"]["after"],
                }

            file_info["changes"].append(change)

        output["files"].append(file_info)

    return output
