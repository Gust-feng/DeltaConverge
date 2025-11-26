"""工具注册中心与相关 schema 定义。"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Agent.core.logging.fallback_tracker import (
    read_text_with_fallback,
    record_fallback,
)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[[Dict[str, Any]], Any]


_TOOL_REGISTRY: Dict[str, ToolSpec] = {}
# 认为“无害且应默认启用”的内置工具清单（不包含 echo 等调试类工具）
_BUILTIN_SAFE_TOOLS = [
    "list_project_files",
    "read_file_hunk",
    "read_file_info",
    "search_in_project",
    "get_dependencies",
]


def register_tool(spec: ToolSpec) -> None:
    _TOOL_REGISTRY[spec.name] = spec


def list_tool_names() -> List[str]:
    return sorted(_TOOL_REGISTRY.keys())


def get_tool_spec(name: str) -> ToolSpec:
    return _TOOL_REGISTRY[name]


def get_tool_schemas(names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    selected = names or list_tool_names()
    schemas: List[Dict[str, Any]] = []
    for name in selected:
        spec = _TOOL_REGISTRY.get(name)
        if not spec:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
        )
    return schemas


def get_tool_functions(names: Optional[List[str]] = None) -> Dict[str, Callable[[Dict[str, Any]], Any]]:
    selected = names or list_tool_names()
    mapping: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
    for name in selected:
        spec = _TOOL_REGISTRY.get(name)
        if not spec:
            continue
        mapping[name] = spec.func
    return mapping


# ---------------------------------------------------------------------------
# 内置工具
# ---------------------------------------------------------------------------

def _echo_tool(args: Dict[str, Any]) -> str:
    text = args.get("text", "")
    return f"TOOL ECHO: {text}"


def _run_git_ls(args: List[str]) -> List[str]:
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or 'unknown error'}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _list_project_files(args: Dict[str, Any]) -> str:
    """返回按目录分组的文件与文件夹 JSON。

    Parameters (via args):
      - mode: \"all\" | \"dirs\"，默认 \"all\"
      - dirs: 可选目录列表，仅在 mode=\"dirs\" 时生效
    """

    mode = args.get("mode", "all")
    dirs_filter: List[str] = args.get("dirs") or []

    # 获取未被忽略的文件（tracked + untracked）
    tracked = set(_run_git_ls(["ls-files"]))
    untracked = set(_run_git_ls(["ls-files", "--others", "--exclude-standard"]))
    included_files = sorted(tracked.union(untracked))

    # 读取 .gitignore 内容（仅供参考）
    gitignore_content = ""
    gitignore_path = Path(".gitignore")
    if gitignore_path.exists():
        try:
            gitignore_content = read_text_with_fallback(
                gitignore_path, reason=".gitignore read"
            )
        except Exception as exc:  # pragma: no cover - 尽力而为
            gitignore_content = f"(无法读取 .gitignore: {exc})"
            record_fallback(
                "gitignore_read_failed",
                "无法读取 .gitignore，返回占位信息",
                meta={"error": str(exc)},
            )

    included_structure: Dict[str, List[str]] = {}
    for rel_path in included_files:
        path = Path(rel_path)
        folder = str(path.parent) if path.parent != Path("") else "."
        if mode == "dirs" and dirs_filter:
            if not any(str(folder).startswith(d) for d in dirs_filter):
                continue
        included_structure.setdefault(folder, []).append(path.name)

    result = {
        "gitignore_content": gitignore_content,
        "included_files": included_structure,
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


def _read_file_hunk(args: Dict[str, Any]) -> str:
    """读取文件片段，可按需附带上下文。"""

    path = args.get("path")
    if not path:
        raise ValueError("path is required")
    start_line = max(int(args.get("start_line", 1)), 1)
    end_line = max(int(args.get("end_line", start_line)), start_line)
    before = max(int(args.get("before", 5)), 0)
    after = max(int(args.get("after", 5)), 0)

    file_path = Path(path)
    if not file_path.exists():
        return json.dumps(
            {"path": path, "error": "file_not_found"},
            ensure_ascii=False,
            indent=2,
        )

    try:
        text = read_text_with_fallback(file_path, reason="read_file_hunk")
    except Exception as exc:
        record_fallback(
            "read_file_hunk_failed",
            "读取文件片段失败",
            meta={"path": path, "error": str(exc)},
        )
        return json.dumps(
            {"path": path, "error": f"read_failed:{exc}"},
            ensure_ascii=False,
            indent=2,
        )
    lines = text.splitlines()
    total = len(lines)

    ctx_start = max(1, start_line - before)
    ctx_end = min(total, end_line + after)

    snippet_lines = lines[ctx_start - 1 : ctx_end]
    snippet = "\n".join(snippet_lines)

    # 便于 LLM 精确定位，附带行号标注版
    numbered_lines = [f"{lineno}: {content}" for lineno, content in enumerate(snippet_lines, start=ctx_start)]
    snippet_with_line_numbers = "\n".join(numbered_lines)

    return json.dumps(
        {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "context_start": ctx_start,
            "context_end": ctx_end,
            "total_lines": total,
            "snippet": snippet,
            "snippet_with_line_numbers": snippet_with_line_numbers,
        },
        ensure_ascii=False,
        indent=2,
    )


def _read_file_info(args: Dict[str, Any]) -> str:
    """返回文件的轻量信息（大小、语言、行数、标签）。"""

    path = args.get("path")
    if not path:
        raise ValueError("path is required")
    file_path = Path(path)
    if not file_path.exists():
        return json.dumps(
            {"path": path, "error": "file_not_found"},
            ensure_ascii=False,
            indent=2,
        )

    try:
        size = file_path.stat().st_size
    except OSError:
        size = None

    try:
        text = read_text_with_fallback(file_path, reason="read_file_info")
    except Exception as exc:
        record_fallback(
            "read_file_info_failed",
            "读取文件信息失败",
            meta={"path": path, "error": str(exc)},
        )
        return json.dumps(
            {"path": path, "error": f"read_failed:{exc}"},
            ensure_ascii=False,
            indent=2,
        )
    lines = text.splitlines()
    line_count = len(lines)

    ext = file_path.suffix.lower()
    if ext == ".py":
        language = "python"
    elif ext in {".js", ".jsx", ".ts", ".tsx"}:
        language = "javascript"
    elif ext in {".json"}:
        language = "json"
    elif ext in {".yml", ".yaml"}:
        language = "yaml"
    else:
        language = "unknown"

    lower_path = str(file_path).lower()
    is_test = any(part in lower_path for part in ("test", "tests", "_spec"))
    is_config = any(
        key in lower_path
        for key in ("config", "setting", ".ini", ".yml", ".yaml", ".toml", "pyproject")
    )

    return json.dumps(
        {
            "path": path,
            "size_bytes": size,
            "language": language,
            "line_count": line_count,
            "is_test_file": is_test,
            "is_config_file": is_config,
        },
        ensure_ascii=False,
        indent=2,
    )


def _search_in_project(args: Dict[str, Any]) -> str:
    """使用 git grep 在项目中搜索关键字。"""

    query = args.get("query")
    if not query:
        raise ValueError("query is required")
    max_results = int(args.get("max_results", 50))

    result = subprocess.run(
        ["git", "grep", "-n", "--no-color", query],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode not in (0, 1):  # 返回码 1 表示没有匹配
        return json.dumps(
            {"query": query, "error": result.stderr.strip() or "git grep failed"},
            ensure_ascii=False,
            indent=2,
        )

    matches: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        path, rest = line.split(":", 1)
        if ":" in rest:
            line_no_str, snippet = rest.split(":", 1)
        else:
            line_no_str, snippet = "0", rest
        try:
            line_no = int(line_no_str)
        except ValueError:
            line_no = 0
        matches.append({"path": path, "line": line_no, "snippet": snippet.strip()})
        if len(matches) >= max_results:
            break

    return json.dumps(
        {"query": query, "matches": matches}, ensure_ascii=False, indent=2
    )


def _get_dependencies(_: Dict[str, Any]) -> str:
    """收集常见依赖清单中的依赖信息。"""

    root = Path(".")
    result: Dict[str, Any] = {}

    # Python 依赖
    req = root / "requirements.txt"
    if req.exists():
        entries: List[str] = []
        try:
            content = read_text_with_fallback(req, reason="requirements.txt")
        except Exception as exc:
            record_fallback(
                "dependencies_read_failed",
                "无法读取 requirements.txt",
                meta={"error": str(exc)},
            )
            content = ""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(line)
        result["requirements.txt"] = {"kind": "python_requirements", "entries": entries}

    # package.json 清单
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(
                read_text_with_fallback(pkg, reason="package.json")
            )
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            result["package.json"] = {
                "kind": "npm_package",
                "dependencies": deps,
                "devDependencies": dev_deps,
            }
        except json.JSONDecodeError:
            result["package.json"] = {
                "kind": "npm_package",
                "error": "invalid_json",
            }
            record_fallback(
                "package_json_invalid",
                "package.json 无法解析 JSON",
                meta={"path": str(pkg)},
            )

    # pyproject.toml 等其他清单：直接返回原始文本
    for name in ("pyproject.toml", "Pipfile", "poetry.lock", "go.mod"):
        path = root / name
        if path.exists():
            result[name] = {
                "kind": "manifest",
                "content": read_text_with_fallback(path, reason=name),
            }

    return json.dumps(result, ensure_ascii=False, indent=2)


def _register_default_tools() -> None:
    register_tool(
        ToolSpec(
            name="echo_tool",
            description="Echo helper，用于输出调试或摘要文本。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要回显的内容",
                    }
                },
                "required": ["text"],
            },
            func=_echo_tool,
        )
    )
    register_tool(
        ToolSpec(
            name="list_project_files",
            description="列出项目文件结构；mode=all 时返回整个项目，mode=dirs 时仅返回指定目录下的文件。",
            parameters={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["all", "dirs"],
                        "description": "all: 全项目；dirs: 仅 dirs 中的目录",
                    },
                    "dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "当 mode=dirs 时使用的目录前缀列表",
                    },
                },
                "additionalProperties": False,
            },
            func=_list_project_files,
        )
    )
    register_tool(
        ToolSpec(
            name="read_file_hunk",
            description="读取指定文件的片段，并包含上下文。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                    "start_line": {"type": "integer", "description": "起始行号(1-based)"},
                    "end_line": {"type": "integer", "description": "结束行号(1-based)"},
                    "before": {
                        "type": "integer",
                        "description": "向上扩展的上下文行数",
                    },
                    "after": {
                        "type": "integer",
                        "description": "向下扩展的上下文行数",
                    },
                },
                "required": ["path", "start_line", "end_line"],
            },
            func=_read_file_hunk,
        )
    )
    register_tool(
        ToolSpec(
            name="read_file_info",
            description="获取文件基础信息（大小、语言、行数以及是否为测试/配置文件）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件相对路径"},
                },
                "required": ["path"],
            },
            func=_read_file_info,
        )
    )
    register_tool(
        ToolSpec(
            name="search_in_project",
            description="在项目中搜索关键字（基于 git grep）。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键字"},
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回条数，默认 50",
                    },
                },
                "required": ["query"],
            },
            func=_search_in_project,
        )
    )
    register_tool(
        ToolSpec(
            name="get_dependencies",
            description="扫描常见依赖清单文件，返回依赖信息。",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            func=_get_dependencies,
        )
    )


_register_default_tools()


def default_tool_names() -> List[str]:
    """返回默认启用的内置工具列表（排除调试类工具）。"""

    return [name for name in _BUILTIN_SAFE_TOOLS if name in _TOOL_REGISTRY]


def builtin_tool_names() -> List[str]:
    """与 default_tool_names 等价，向后兼容命名。"""

    return default_tool_names()
