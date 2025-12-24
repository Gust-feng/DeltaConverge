"""工具注册中心与相关 schema 定义。"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from Agent.core.logging.fallback_tracker import (
    read_text_with_fallback,
    record_fallback,
)
from Agent.core.context.runtime_context import get_project_root
from Agent.core.api.project import ProjectAPI
from Agent.DIFF.git_operations import _decode_output, _run_git_quiet, run_git


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
    "list_directory",
    "read_file_hunk",
    "read_file_info",
    "search_in_project",
    "get_dependencies",
]


def register_tool(spec: ToolSpec) -> None:
    _TOOL_REGISTRY[spec.name] = spec


def unregister_tool(name: str) -> bool:
    """从注册表中移除工具。
    
    Args:
        name: 工具名称
        
    Returns:
        bool: 是否成功移除（工具不存在时返回 False）
    """
    if name in _TOOL_REGISTRY:
        del _TOOL_REGISTRY[name]
        return True
    return False


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
    # 自动注入当前上下文中的项目根目录
    cwd = get_project_root()

    if not args:
        return []
    output = run_git(args[0], *args[1:], cwd=cwd)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _list_project_files(args: Dict[str, Any]) -> str:
    """返回按目录分组的文件与文件夹 JSON。

    Parameters (via args):
      - mode: "all" | "dirs"，默认 "all"
      - dirs: 可选目录列表，仅在 mode="dirs" 时生效
    """

    mode = args.get("mode", "all")
    dirs_filter: List[str] = args.get("dirs") or []

    root_str = get_project_root()
    root_path = Path(root_str).resolve() if root_str else Path(".").resolve()

    # 获取 tracked 文件：优先从 .git/index 读取（限制 5000 条）
    tracked: set = set()
    try:
        index_path = ProjectAPI._get_git_index_path(root_path)
        if index_path is not None:
            tracked = set(ProjectAPI._read_git_index_paths(index_path, max_entries=5000))
        if not tracked:
            tracked = set(_run_git_ls(["ls-files"]))
    except Exception:
        pass

    # 获取 untracked 文件（限制数量，避免大仓库卡顿）
    untracked: set = set()
    try:
        # 使用 --exclude-standard 并限制输出行数
        raw_untracked = _run_git_ls(["ls-files", "--others", "--exclude-standard"])
        # 限制 untracked 最多 1000 条
        untracked = set(raw_untracked[:1000])
    except Exception:
        pass

    if not tracked and not untracked:
        # Fallback for non-git repo
        return _list_directory({"path": "."})

    included_files = sorted(tracked.union(untracked))

    # 读取 .gitignore 内容（仅供参考）
    gitignore_content = ""
    gitignore_path = root_path / ".gitignore"
    
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


def _list_directory(args: Dict[str, Any]) -> str:
    """列出指定目录下的文件"""
    path = args.get("path", ".")
    root_str = get_project_root()
    # 确保 root_path 是绝对路径，避免 relative_to 报错
    root_path = Path(root_str).resolve() if root_str else Path(".").resolve()
    target_path = (root_path / path).resolve()
    
    # 安全检查：防止路径穿越
    try:
        target_path.relative_to(root_path)
    except ValueError:
        return json.dumps({"error": f"Access denied: {path} is outside project root"}, ensure_ascii=False)

    if not target_path.exists():
         return json.dumps({"error": f"Path not found: {path}"}, ensure_ascii=False)
    if not target_path.is_dir():
         return json.dumps({"error": f"Not a directory: {path}"}, ensure_ascii=False)
    
    files = []
    dirs = []
    try:
        for entry in target_path.iterdir():
            if entry.name.startswith("."): continue  # Skip hidden
            if entry.is_dir():
                dirs.append(entry.name + "/")
            else:
                files.append(entry.name)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    
    return json.dumps(
        {"path": str(path), "directories": sorted(dirs), "files": sorted(files)},
        ensure_ascii=False,
        indent=2
    )


def _read_file_hunk(args: Dict[str, Any]) -> str:
    """读取文件片段，可按需附带上下文。"""

    path = args.get("path")
    if not path:
        raise ValueError("path is required")
    start_line = max(int(args.get("start_line", 1)), 1)
    end_line = max(int(args.get("end_line", start_line)), start_line)
    before = max(int(args.get("before", 5)), 0)
    after = max(int(args.get("after", 5)), 0)

    root_str = get_project_root()
    file_path = (Path(root_str) / path) if root_str else Path(path)
    
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
        
    root_str = get_project_root()
    file_path = (Path(root_str) / path) if root_str else Path(path)
    
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

    cwd = get_project_root()
    try:
        result = _run_git_quiet("grep", "-n", "--no-color", query, cwd=cwd)
        if result.returncode not in (0, 1):  # 返回码 1 表示没有匹配
            return json.dumps(
                {
                    "query": query,
                    "error": _decode_output(result.stderr).strip() or "git grep failed",
                },
                ensure_ascii=False,
                indent=2,
            )

        matches: List[Dict[str, Any]] = []
        stdout = _decode_output(result.stdout)
        for line in stdout.splitlines():
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
    except Exception as e:
        # Fallback: simple grep-like walk
        # TODO: Implement pure python grep if needed
        return json.dumps({"error": f"Search failed (git not available?): {e}"}, ensure_ascii=False)


def _get_dependencies(_: Dict[str, Any]) -> str:
    """收集常见依赖清单中的依赖信息。"""

    root_str = get_project_root()
    root = Path(root_str) if root_str else Path(".")
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


def _normalize_path_for_match(path: str) -> str:
    """标准化路径用于匹配比较。"""
    if not path:
        return ""
    return path.replace("\\", "/").lower().strip()


async def _get_scanner_results(args: Dict[str, Any]) -> str:
    """获取静态扫描器发现的严重代码问题（仅 error 级别）。
    
    返回与本次代码变更相关的严重问题，按优先级排序。
    不包含 warning 和 info 级别的建议信息。
    """
    from Agent.core.context.runtime_context import get_session_id, get_diff_units
    
    # 获取参数
    file_filter = args.get("file_filter", "")
    
    session_id = get_session_id()
    if not session_id:
        return json.dumps({
            "summary": "无法获取会话信息",
            "issues": []
        }, ensure_ascii=False, indent=2)
    
    # 尝试获取扫描结果
    try:
        from Agent.DIFF.static_scan_service import (
            _STATIC_SCAN_ISSUES_CACHE,
            _STATIC_SCAN_ISSUES_CACHE_LOCK,
            is_scan_complete,
            wait_scan_complete,
        )
        from Agent.DIFF.rule.context_decision import get_rule_event_callback
        
        with _STATIC_SCAN_ISSUES_CACHE_LOCK:
            cache_data = _STATIC_SCAN_ISSUES_CACHE.get(session_id)
        
        # 如果缓存为空，尝试等待扫描完成
        if not cache_data:
            # 检查是否有正在进行的扫描
            if not is_scan_complete(session_id):
                # 发送事件通知前端：工具正在等待扫描完成
                callback = get_rule_event_callback()
                if callback:
                    try:
                        callback({
                            "type": "tool_waiting",
                            "tool_name": "get_scanner_results",
                            "message": "扫描进行中，请稍后",
                        })
                    except Exception:
                        pass
                
                try:
                    # 等待扫描完成，最多60秒
                    ok = await wait_scan_complete(session_id, timeout=60.0)
                    if not ok:
                        raise asyncio.TimeoutError()
                    
                    # 重新获取缓存
                    with _STATIC_SCAN_ISSUES_CACHE_LOCK:
                        cache_data = _STATIC_SCAN_ISSUES_CACHE.get(session_id)
                except asyncio.CancelledError:
                    raise
                except asyncio.TimeoutError:
                    return json.dumps({
                        "summary": "扫描超时，请稍后重试",
                        "issues": []
                    }, ensure_ascii=False, indent=2)
        
        # 再次检查缓存
        if not cache_data:
            return json.dumps({
                "summary": "静态扫描未启用",
                "issues": []
            }, ensure_ascii=False, indent=2)
        
        # 只获取 error 级别的严重问题
        issues_by_sev = cache_data.get("issues_by_severity", {})
        all_issues: List[Dict[str, Any]] = issues_by_sev.get("error", [])
        
        if not all_issues:
            return json.dumps({
                "summary": "扫描完成，未发现严重问题",
                "issues": []
            }, ensure_ascii=False, indent=2)
        
        # 获取 diff_units 用于过滤
        diff_units = get_diff_units()
        
        # 构建变更文件和行范围集合
        changed_files: set = set()
        changed_ranges: Dict[str, List[tuple]] = {}  # file -> [(start, end), ...]
        
        for unit in diff_units:
            fp = _normalize_path_for_match(unit.get("file_path", ""))
            if fp:
                changed_files.add(fp)
                hr = unit.get("hunk_range", {})
                start = hr.get("new_start", 0) or hr.get("start", 0)
                lines = hr.get("new_lines", 0) or hr.get("lines", 0)
                if isinstance(start, int) and start > 0:
                    end = start + max(int(lines) if isinstance(lines, int) else 0, 1) - 1
                    changed_ranges.setdefault(fp, []).append((start, end))
        
        # 评分和过滤 - 分离 diff 相关和非 diff 相关问题
        diff_issues: List[Dict[str, Any]] = []  # 与本次变更相关的问题
        other_issues: List[Dict[str, Any]] = []  # 其他全局问题（仅高优先级）
        
        for issue in all_issues:
            severity = str(issue.get("severity", "")).lower()
            issue_file = _normalize_path_for_match(issue.get("file", ""))
            issue_line = issue.get("line", 0) or issue.get("start_line", 0)
            
            try:
                issue_line = int(issue_line)
            except (TypeError, ValueError):
                issue_line = 0
            
            # 文件过滤
            if file_filter:
                filter_norm = _normalize_path_for_match(file_filter)
                if filter_norm not in issue_file:
                    continue
            
            # 计算优先级分数
            score = 0
            
            # 严重性权重
            if severity == "error":
                score += 100
            elif severity == "warning":
                score += 50
            else:
                score += 10
            
            # 变更相关性
            in_diff = False
            in_diff_range = False
            
            if issue_file in changed_files:
                in_diff = True
                score += 200
                
                # 检查是否在变更行范围内
                ranges = changed_ranges.get(issue_file, [])
                for start, end in ranges:
                    if start <= issue_line <= end:
                        in_diff_range = True
                        score += 100
                        break
                    elif 0 < issue_line and (abs(issue_line - start) <= 10 or abs(issue_line - end) <= 10):
                        score += 30
            
            # 安全相关规则额外加分
            rule_id = str(issue.get("rule_id", "") or issue.get("rule", "") or "").lower()
            security_keywords = ["sql", "inject", "xss", "auth", "crypto", "password", "secret", "token"]
            if any(kw in rule_id for kw in security_keywords):
                score += 50
            
            # 构建输出格式
            output_issue = {
                "file": issue.get("file", ""),
                "line": issue_line,
                "severity": severity,
                "rule": issue.get("rule_id") or issue.get("rule") or issue.get("code") or "",
                "message": issue.get("message", ""),
                "in_diff": in_diff,
                "in_diff_range": in_diff_range,
            }
            
            # 压缩消息
            msg = output_issue.get("message", "")
            if len(msg) > 100:
                output_issue["message"] = msg[:97] + "..."
            
            output_issue["_score"] = score
            
            # 分类存储
            # 只收集变更文件中的问题，忽略非 diff 问题
            if in_diff:
                diff_issues.append(output_issue)
        
        # 按分数排序
        diff_issues.sort(key=lambda x: x.get("_score", 0), reverse=True)
        
        # 动态调整返回数量
        total_diff_issues = len(diff_issues)
        if total_diff_issues <= 50:
            # 总数少于50，全部返回
            actual_limit = total_diff_issues
        else:
            # 超过50，动态调整，上限500
            actual_limit = min(total_diff_issues, 500)
        
        result_issues = diff_issues[:actual_limit]
        
        # 移除内部字段，简化输出
        for issue in result_issues:
            issue.pop("_score", None)
            issue.pop("in_diff", None)  # 都是 diff 相关，无需标记
            issue.pop("in_diff_range", None)
        
        # 简洁的 summary
        summary = f"发现 {len(result_issues)} 条严重问题"
        if total_diff_issues > actual_limit:
            summary += f"（已截断，总计 {total_diff_issues} 条）"
        
        return json.dumps({
            "summary": summary,
            "issues": result_issues
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "summary": f"获取扫描结果时出错: {str(e)}",
            "issues": []
        }, ensure_ascii=False, indent=2)


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
            description="列出项目文件结构（基于 Git）；mode=all 时返回整个项目，mode=dirs 时仅返回指定目录下的文件。",
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
            name="list_directory",
            description="列出指定目录下的文件和子目录",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出的目录路径（相对于项目根目录），默认为 '.'",
                    },
                },
                "additionalProperties": False,
            },
            func=_list_directory,
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
    register_tool(
        ToolSpec(
            name="get_scanner_results",
            description="获取静态扫描器发现的严重代码问题（仅 error 级别）。返回与本次变更相关的问题，数量动态调整。",
            parameters={
                "type": "object",
                "properties": {
                    "file_filter": {
                        "type": "string",
                        "description": "按文件路径过滤（可选）",
                    },
                },
                "additionalProperties": False,
            },
            func=_get_scanner_results,
        )
    )


_register_default_tools()


def default_tool_names() -> List[str]:
    """返回默认启用的内置工具列表（排除调试类工具）。"""

    return [name for name in _BUILTIN_SAFE_TOOLS if name in _TOOL_REGISTRY]


def builtin_tool_names() -> List[str]:
    """与 default_tool_names 等价，向后兼容命名。"""

    return default_tool_names()
