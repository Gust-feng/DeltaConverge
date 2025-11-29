"""代码分析模块：处理代码结构检测、符号提取、标签推断等。"""

from __future__ import annotations
from typing import Any
import ast
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set


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
        lineno = getattr(node, "lineno", None)
        if lineno is None:
            continue
        start = lineno
        end = getattr(node, "end_lineno", start)
        
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
    
    # 确保范围有效
    final_start = max(1, final_start)
    final_end = min(len(file_lines), final_end)
    
    return final_start, final_end, tags


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
        logging_tokenss = (
            "logging.",
            "logger.",
            "log.info",
            "log.warning",
            "log.error",
            "log.debug",
        )
        return any(tokens in stripped for tokens in logging_tokenss)
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
