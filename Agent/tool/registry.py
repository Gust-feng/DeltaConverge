"""Central tool registry and schemas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable[[Dict[str, Any]], Any]


_TOOL_REGISTRY: Dict[str, ToolSpec] = {}


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
# Built-in tools
# ---------------------------------------------------------------------------

def _echo_tool(args: Dict[str, Any]) -> str:
    text = args.get("text", "")
    return f"TOOL ECHO: {text}"


def _list_project_files(_: Dict[str, Any]) -> str:
    """Return JSON containing folders and files, including those ignored by git and .gitignore content."""

    def _run_git(args: List[str]) -> List[str]:
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

    # 获取未被忽略的文件（tracked + untracked）
    tracked = set(_run_git(["ls-files"]))
    untracked = set(_run_git(["ls-files", "--others", "--exclude-standard"]))
    included_files = sorted(tracked.union(untracked))

    # 获取被 .gitignore 忽略的文件
    try:
        ignored_raw = _run_git(["ls-files", "--others", "--ignored", "--exclude-standard"])
        ignored_files = sorted(set(ignored_raw))
    except RuntimeError:
        ignored_files = []

    # 读取 .gitignore 内容
    gitignore_content = ""
    gitignore_path = Path(".gitignore")
    if gitignore_path.exists():
        try:
            gitignore_content = gitignore_path.read_text(encoding="utf-8")
        except Exception as e:
            gitignore_content = f"(无法读取 .gitignore: {e})"

    # 构建未被忽略的文件结构
    included_structure: Dict[str, List[str]] = {}
    for rel_path in included_files:
        path = Path(rel_path)
        folder = str(path.parent) if path.parent != Path("") else "."
        included_structure.setdefault(folder, []).append(path.name)

    # 构建被忽略的文件结构
    ignored_structure: Dict[str, List[str]] = {}
    for rel_path in ignored_files:
        path = Path(rel_path)
        folder = str(path.parent) if path.parent != Path("") else "."
        ignored_structure.setdefault(folder, []).append(path.name)

    result = {
        "gitignore_content": gitignore_content,
        "included_files": included_structure,
        "ignored_files": ignored_structure
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
            description="列出项目文件结构。鉴于安全和性能考虑，被.gitignore 排除的内容只会列出名称，而不会显示具体内容。",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            func=_list_project_files,
        )
    )


_register_default_tools()

DEFAULT_TOOL_NAMES = list_tool_names()
