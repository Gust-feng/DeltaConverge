"""核心审查内核：封装从 Diff 解析到最终审查的业务流转。"""

from __future__ import annotations

import json
import os
import subprocess
import hashlib
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast, Tuple

from Agent.agents.code_reviewer import CodeReviewAgent
from Agent.agents.planning_agent import PlanningAgent
from Agent.agents.intent_agent import IntentAgent
from Agent.agents.fusion import fuse_plan
from Agent.agents.context_scheduler import build_context_bundle
from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import (
    collect_diff_context,
    build_markdown_and_json_context,
    DiffContext,
)
from Agent.core.context.runtime_context import get_project_root
from Agent.core.api.project import ProjectAPI
from Agent.DIFF.git_operations import run_git
from Agent.DIFF.output_formatting import build_planner_index
from Agent.core.logging import get_logger
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.core.logging.fallback_tracker import fallback_tracker
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import NormalizedToolCall
from Agent.core.tools.runtime import ToolRuntime
from Agent.tool.registry import get_tool_functions
from Agent.core.services.prompt_builder import build_review_prompt
from Agent.core.services.tool_policy import resolve_tools
from Agent.core.services.usage_service import UsageService
from Agent.core.services.pipeline_events import PipelineEvents

logger = get_logger(__name__)

def _get_review_prompt_limits() -> Dict[str, int]:
    """获取审查提示词构建的内部限制（从配置读取，带默认值）。"""
    try:
        from Agent.core.api.config import get_review_prompt_limits
        return get_review_prompt_limits()
    except Exception:
        return {
            "review_index_max_chars": 18_000,
            "intent_max_chars": 6_000,
            "context_bundle_max_items": 10,
            "context_bundle_max_chars": 45_000,
            "context_field_max_chars": 1_800,
            "caller_max_chars": 500,
            "tags_max_count": 6,
        }

def _truncate_prompt_text(text: str | None, max_chars: int, *, label: str) -> str | None:
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[已截断 {label}，省略 {omitted} 字符。]"


def _context_priority(item: Dict[str, Any]) -> int:
    level = str(item.get("final_context_level") or "")
    level_weight = {
        "full_file": 40,
        "file_context": 30,
        "function": 20,
        "diff_only": 10,
    }.get(level, 0)

    meta = cast(Dict[str, Any], item.get("meta") or {})
    file_path = str(meta.get("file_path") or "").replace("\\", "/").lower()
    penalty = 0
    if file_path.startswith(("legacy/", "frontend/reference/", "output/", "dist/")):
        penalty -= 20
    if file_path.endswith((".png", ".jpg", ".jpeg", ".ico", ".gif")):
        penalty -= 20
    if file_path.endswith((".css", ".scss", ".sass", ".less", ".styl")):
        penalty -= 8
    if file_path.endswith((".md", ".txt")):
        penalty -= 6
    if file_path.endswith(("package-lock.json", "pnpm-lock.yaml", "yarn.lock")):
        penalty -= 10

    tags = set(meta.get("tags") or [])
    bonus = 0
    if "security_sensitive" in tags:
        bonus += 12
    if "config_file" in tags or "routing_file" in tags:
        bonus += 8
    if "clustered_changes" in tags:
        bonus += 2

    diff_text = item.get("diff")
    diff_bonus = min(len(diff_text), 4000) // 400 if isinstance(diff_text, str) else 0
    return level_weight + bonus + diff_bonus + penalty


def _compact_context_item(item: Dict[str, Any], limits: Dict[str, int]) -> Dict[str, Any]:
    meta = cast(Dict[str, Any], item.get("meta") or {})
    compact: Dict[str, Any] = {
        "unit_id": item.get("unit_id"),
        "file_path": meta.get("file_path"),
        "location": meta.get("location"),
        "context_level": item.get("final_context_level"),
    }

    tags = list(meta.get("tags") or [])
    if tags:
        compact["tags"] = tags[:limits["tags_max_count"]]

    diff_excerpt = _truncate_prompt_text(
        cast(str | None, item.get("diff")),
        limits["context_field_max_chars"],
        label="diff 片段",
    )
    if diff_excerpt:
        compact["diff_excerpt"] = diff_excerpt

    context_fields = (
        ("function_context", "function"),
        ("file_context", "file"),
        ("full_file", "full_file"),
    )
    for field_name, label in context_fields:
        value = _truncate_prompt_text(
            cast(str | None, item.get(field_name)),
            limits["context_field_max_chars"],
            label=f"{label} 上下文",
        )
        if value:
            compact["context_kind"] = label
            compact["context_excerpt"] = value
            break

    previous_version = _truncate_prompt_text(
        cast(str | None, item.get("previous_version")),
        max(1, limits["context_field_max_chars"] // 2),
        label="历史版本片段",
    )
    if previous_version:
        compact["previous_version_excerpt"] = previous_version

    extra_requests = item.get("extra_requests") or []
    if extra_requests:
        compact["extra_requests"] = [
            req.get("type") if isinstance(req, dict) else str(req) for req in extra_requests[:4]
        ]

    callers: List[Dict[str, str]] = []
    for caller in cast(List[Dict[str, Any]], item.get("callers") or [])[:1]:
        callers.append(
            {
                "file_path": str(caller.get("file_path") or ""),
                "snippet": _truncate_prompt_text(
                    cast(str | None, caller.get("snippet")),
                    limits["caller_max_chars"],
                    label="调用方片段",
                )
                or "",
            }
        )
    if callers:
        compact["callers"] = callers

    return compact


def compact_prompt_context_bundle(bundle: List[Dict[str, Any]]) -> Dict[str, Any]:
    limits = _get_review_prompt_limits()
    ranked = sorted(bundle, key=_context_priority, reverse=True)
    kept: List[Dict[str, Any]] = []
    omitted = 0
    total_chars = 0

    for item in ranked:
        compact = _compact_context_item(item, limits)
        serialized = json.dumps(compact, ensure_ascii=False)
        next_chars = total_chars + len(serialized)
        if kept and (
            len(kept) >= limits["context_bundle_max_items"]
            or next_chars > limits["context_bundle_max_chars"]
        ):
            omitted += 1
            continue
        kept.append(compact)
        total_chars = next_chars

    return {
        "items": kept,
        "kept_items": len(kept),
        "omitted_items": omitted,
        "original_items": len(bundle),
        "approx_chars": total_chars,
    }


class UsageAggregator:
    def __init__(self) -> None:
        self._svc = UsageService()

    def reset(self) -> None:
        self._svc.reset()

    def update(self, usage: Dict[str, Any], call_index: int | None) -> Tuple[Dict[str, int], Dict[str, int]]:
        return self._svc.update(usage, call_index)

    def session_totals(self) -> Dict[str, int]:
        return self._svc.session_totals()


def _is_valid_usage(usage: Dict[str, Any]) -> bool:
    """检查usage数据是否有效（不是全0）。
    
    某些API（如MiniMax）在流式响应中返回的usage全为0，
    这种数据没有意义，不应该显示给用户。
    """
    if not usage or not isinstance(usage, dict):
        return False
    
    # 提取token数量，支持多种字段名
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    total_tokens = usage.get("total_tokens") or 0
    
    # 如果所有token数都是0，认为无效
    return input_tokens > 0 or output_tokens > 0 or total_tokens > 0



class ReviewKernel:
    """核心审查引擎，负责编排各 Agent 与 Context 模块。"""

    def __init__(
        self,
        review_adapter: LLMAdapter,
        planner_adapter: LLMAdapter,
        review_provider: str,
        planner_provider: str,
        trace_id: str,
    ) -> None:
        self.review_adapter = review_adapter
        self.planner_adapter = planner_adapter
        self.intent_adapter = planner_adapter  # 复用同一小模型，后续可独立配置
        self.review_provider = review_provider
        self.planner_provider = planner_provider
        self.trace_id = trace_id

        self.usage_agg = UsageAggregator()
        self.pipe_logger = PipelineLogger(trace_id=trace_id)
        self.session_log = None

    def _get_project_name(self, project_path: str) -> str:
        """获取项目名称。"""
        # 使用项目路径的最后一部分作为项目名称
        return os.path.basename(os.path.abspath(project_path))

    def _get_intent_file_path(self, project_path: str) -> str:
        """获取意图分析文件的存储路径。"""
        project_name = os.path.basename(project_path.rstrip(os.sep))
        file_name = f"{project_name}.json"
        # Preferred layout: Agent/data/Analysis
        agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Agent
        data_dir = os.path.join(agent_dir, "data", "Analysis")
        # 确保目录存在
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, file_name)

    def _read_intent_file(self, project_path: str) -> Optional[Dict[str, Any]]:
        """从文件中读取意图分析结果。"""
        file_path = self._get_intent_file_path(project_path)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read intent file {file_path}: {e}")
        return None

    def _write_intent_file(self, project_path: str, intent_data: Dict[str, Any]) -> None:
        """将意图分析结果写入文件。"""
        file_path = self._get_intent_file_path(project_path)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(intent_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Intent file written to {file_path}")
        except Exception as e:
            logger.warning(f"Failed to write intent file {file_path}: {e}")

    def _delete_intent_file(self, project_path: str) -> None:
        """删除意图分析文件。"""
        file_path = self._get_intent_file_path(project_path)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Intent file deleted: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete intent file {file_path}: {e}")

    def update_intent_file(self, project_path: str) -> None:
        """更新意图分析文件。"""
        # 删除旧文件
        self._delete_intent_file(project_path)
        # 重新生成新文件
        # 注意：这里只是删除旧文件，新文件会在下次运行审查时生成
        logger.info(f"Intent file will be updated for project {project_path}")

    def cleanup_old_intent_files(self, max_age_days: int = 30) -> None:
        """清理过期的意图分析文件。"""
        current_time = datetime.now()
        # Preferred layout: Agent/data/Analysis
        agent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Agent
        data_dir = os.path.join(agent_dir, "data", "Analysis")
        if not os.path.exists(data_dir):
            return

        for file_name in os.listdir(data_dir):
            if file_name.endswith('.json'):
                file_path = os.path.join(data_dir, file_name)
                try:
                    # 获取文件修改时间
                    mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                    # 计算文件年龄
                    age_days = (current_time - mtime).days
                    if age_days > max_age_days:
                        os.remove(file_path)
                        logger.info(f"Deleted old intent file: {file_path} (age: {age_days} days)")
                except Exception as e:
                    logger.warning(f"Failed to process intent file {file_path}: {e}")

    def _summarize_context_bundle(self, bundle: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成上下文包的体积/截断概览。"""
        if not bundle:
            return {"items": 0, "total_chars": 0, "truncated_fields": 0, "by_level": {}}

        text_fields = ("diff", "function_context", "file_context", "full_file", "previous_version")
        total_chars = 0
        truncated_fields = 0
        level_count: Dict[str, int] = {}

        for item in bundle:
            level = str(item.get("final_context_level") or "unknown")
            level_count[level] = level_count.get(level, 0) + 1
            for field in text_fields:
                val = item.get(field)
                if isinstance(val, str):
                    total_chars += len(val)
                    if "TRUNCATED" in val:
                        truncated_fields += 1
            callers = item.get("callers") or []
            for c in callers:
                snippet = c.get("snippet")
                if isinstance(snippet, str):
                    total_chars += len(snippet)
                    if "TRUNCATED" in snippet:
                        truncated_fields += 1

        avg_chars = total_chars // max(len(bundle), 1)
        return {
            "items": len(bundle),
            "total_chars": total_chars,
            "avg_chars": avg_chars,
            "truncated_fields": truncated_fields,
            "by_level": level_count,
        }

    def _notify(self, callback: Optional[Callable], evt: Dict[str, Any]) -> None:
        if callback:
            try:
                callback(evt)
            except Exception:
                pass

    def _collect_intent_inputs(self) -> Dict[str, Any]:
        """收集意图 Agent 所需的轻量上下文：文件列表、README 内容、最近提交。"""

        # 优先使用 Context 中的 project_root
        root_str = get_project_root()
        project_root = Path(root_str) if root_str else Path(".")

        def _read_readme() -> str | None:
            """读取README文件内容，最多8000字符。"""
            readme_files = ["README.md", "readme.md", "README.rst", "readme.rst", "README.txt", "readme.txt"]
            for filename in readme_files:
                path = project_root / filename
                if path.exists() and path.is_file():
                    try:
                        content = path.read_text(encoding="utf-8", errors="ignore")
                        return content[:8000]  # 限制README内容长度
                    except Exception:
                        continue
            return None

        def _build_file_tree() -> Dict[str, Any]:
            """构建项目文件树结构，基于 gitignore + 基础规则过滤。
            
            过滤策略：
            1. git ls-files 自动排除 .gitignore 中的文件
            2. 基础规则排除：测试文件、缓存、构建产物、IDE配置等
            3. 白名单保留核心代码文件类型
            """
            file_tree = {}

            # ===== 基础过滤规则 =====
            # 需要排除的目录（完整路径前缀匹配）
            EXCLUDED_DIRS = {
                # 测试相关
                "tests/", "test/", "__tests__/", "spec/", "specs/",
                # 缓存和构建产物
                "__pycache__/", ".cache/", ".pytest_cache/", ".mypy_cache/",
                "node_modules/", "dist/", "build/", "target/", "out/",
                ".tox/", ".nox/", ".eggs/", "*.egg-info/",
                # IDE 和编辑器
                ".vscode/", ".idea/", ".vs/", ".eclipse/",
                # 版本控制
                ".git/", ".svn/", ".hg/",
                # 虚拟环境
                "venv/", ".venv/", "env/", ".env/", "virtualenv/",
                # 文档和静态资源（可选保留）
                "docs/", "doc/", "static/", "assets/", "images/",
                # 日志和数据
                "log/", "logs/", "data/", "tmp/", "temp/",
                # 项目特定噪音目录
                "etc/",
            }

            # 需要排除的文件名模式
            EXCLUDED_FILES = {
                # 测试文件
                "test_", "_test.py", "_spec.py", ".test.js", ".spec.js",
                "conftest.py",
                # 配置文件
                ".gitignore", ".gitattributes", ".editorconfig",
                ".dockerignore", ".eslintignore", ".prettierignore",
                # 锁文件
                "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
                # 编译产物
                ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
                ".o", ".a", ".lib", ".exe", ".bin",
                # 压缩文件
                ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
                # 图片和媒体
                ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
                ".mp3", ".mp4", ".wav", ".avi",
                # 数据文件
                ".db", ".sqlite", ".sqlite3", ".pickle", ".pkl",
                # 日志
                ".log",
            }

            # 白名单：保留的核心代码文件扩展名
            ALLOWED_EXTENSIONS = {
                ".py", ".js", ".ts", ".jsx", ".tsx",
                ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
                ".rb", ".php", ".swift", ".kt", ".scala",
                ".md", ".rst", ".txt",
                ".json", ".yaml", ".yml", ".toml",
                ".html", ".css", ".scss", ".less",
                ".sh", ".bash", ".zsh", ".ps1",
                ".sql",
            }

            # 获取文件列表（git ls-files 已自动排除 .gitignore）
            files: List[str] = []
            try:
                index_path = ProjectAPI._get_git_index_path(project_root.resolve())
                if index_path is not None:
                    files = ProjectAPI._read_git_index_paths(index_path, max_entries=5000)
                if not files:
                    output = run_git("ls-files", cwd=str(project_root))
                    files = [line.strip() for line in output.splitlines() if line.strip()]
            except Exception:
                files = []

            if not files:
                try:
                    max_fallback_files = 200
                    for p in project_root.rglob("*"):
                        if not p.is_file():
                            continue
                        try:
                            files.append(str(p.relative_to(project_root)))
                        except ValueError:
                            continue
                        if len(files) >= max_fallback_files:
                            break
                except Exception:
                    pass
            
            def is_allowed_file(file_path: str) -> bool:
                """基于基础规则过滤文件。"""
                # 统一使用正斜杠
                normalized_path = file_path.replace("\\", "/")
                path_lower = normalized_path.lower()
                
                # 1. 排除特定目录下的文件
                for excluded_dir in EXCLUDED_DIRS:
                    # 匹配目录前缀或路径中包含该目录
                    if path_lower.startswith(excluded_dir.rstrip("/") + "/") or \
                       ("/" + excluded_dir.rstrip("/") + "/") in path_lower:
                        return False
                
                # 2. 排除特定文件名模式
                file_name = normalized_path.split("/")[-1].lower()
                for pattern in EXCLUDED_FILES:
                    if pattern.startswith("."):
                        # 扩展名匹配
                        if file_name.endswith(pattern):
                            return False
                    elif pattern.endswith(".py") or pattern.endswith(".js"):
                        # 文件名模式匹配
                        if file_name.startswith(pattern.rstrip(".py").rstrip(".js")) or \
                           file_name.endswith(pattern):
                            return False
                    else:
                        # 完整文件名匹配
                        if file_name == pattern or file_name.startswith(pattern):
                            return False
                
                # 3. 白名单检查：只保留特定扩展名
                ext = "." + file_name.split(".")[-1] if "." in file_name else ""
                if ext not in ALLOWED_EXTENSIONS:
                    return False
                
                return True
            
            filtered_files = [f for f in files if is_allowed_file(f)]
            
            # 构建文件树，限制数量
            for file_path in filtered_files[:150]:
                parts = file_path.replace("\\", "/").split("/")
                current = file_tree
                
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        current[part] = None
                    else:
                        if part not in current:
                            current[part] = {}
                        current = current[part]
            
            return file_tree
        
        def _list_files() -> List[str]:
            """获取项目文件列表，过滤掉不必要的文件，限制数量。"""
            # 兼容旧接口，返回空列表
            return []

        def _recent_commits() -> List[str]:
            """获取最近的git提交记录，最多20条。"""
            try:
                # 使用 run_git
                output = run_git("log", "-n20", "--pretty=format:%h %s", cwd=str(project_root))
                return [line.strip() for line in output.splitlines() if line.strip()]
            except Exception:
                pass
            return []

        return {
            "file_tree": _build_file_tree(),  # 构建文件树
            "file_list": _list_files(),  # 保留file_list字段以保持兼容性
            "readme_content": _read_readme(),  # 重命名为readme_content，更清晰
            "git_history": _recent_commits(),  # 重命名为git_history，更清晰
        }

    async def run(
        self,
        prompt: str,
        tool_names: List[str],
        auto_approve: bool,
        diff_ctx: DiffContext,
        stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        tool_approver: Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
        agents: Optional[List[str]] = None,
    ) -> str:
        """运行审查流程核心逻辑。"""
        
        # 默认启用所有 Agent
        if agents is None:
            active_agents = {"intent", "planner", "reviewer"}
        else:
            active_agents = set(agents)
        
        # 预先收集项目文件树，供 intent 和 reviewer 阶段共用
        intent_inputs = self._collect_intent_inputs()
        project_file_tree = intent_inputs.get("file_tree", {})
            
        fallback_tracker.reset()
        
        self.session_log = self.pipe_logger.start(
            "planning_review_service_async",
            {
                "review_provider": self.review_provider,
                "planner_provider": self.planner_provider,
                "trace_id": self.trace_id,
            },
        )
        
        self.pipe_logger.log(
            "diff_summary",
            {
                "mode": diff_ctx.mode.value,
                "files": len(diff_ctx.files),
                "units": len(diff_ctx.units),
                "review_index_units": len(diff_ctx.review_index.get("units", [])),
                "review_index_preview": diff_ctx.review_index.get("units", [])[:3],
                "trace_id": self.trace_id,
            },
        )

        events = PipelineEvents(stream_callback)
        events.stage_end("diff_parse", files=len(diff_ctx.files), units=len(diff_ctx.units))
        events.stage_end("review_units")
        events.stage_end("rule_layer")
        events.stage_end("review_index")

        # Intent Analysis Phase
        events.stage_start("intent_analysis")
        intent_summary_md: str | None = None
        intent_agent = None
        try:
            # 获取项目路径
            root_str = get_project_root()
            project_path = root_str if root_str else os.getcwd()
            
            # 尝试从文件读取意图分析结果
            intent_file_data = self._read_intent_file(project_path)
            
            if intent_file_data:
                # 从文件读取成功
                logger.info(f"Read intent from file for project {project_path}")
                # 提取正式输出内容
                intent_summary_md = (
                    intent_file_data.get("content")
                    or intent_file_data.get("response", {}).get("content", "")
                    or ""
                )
                # 空内容不应视为命中缓存，否则会导致意图分析被错误跳过
                if not str(intent_summary_md).strip():
                    intent_file_data = None
                    intent_summary_md = None
                else:
                    events.stage_end("intent_analysis", has_output=True)
            elif "intent" in active_agents:
                # 文件不存在且启用了 intent agent，生成新的意图分析结果
                # 使用已在 run() 开头收集的 intent_inputs
                intent_agent = IntentAgent(self.intent_adapter, ConversationState())

                # 收集完整的思考和正式内容
                full_reasoning = ""
                full_content = ""

                def _intent_observer(evt: Dict[str, Any]) -> None:
                    nonlocal full_reasoning, full_content
                    content_delta = evt.get("content_delta") or ""
                    reasoning_delta = evt.get("reasoning_delta") or ""
                    
                    # 收集完整内容 (修复P0问题: 必须在stream_callback检查之前收集,否则缓存写入为空)
                    full_reasoning += reasoning_delta
                    full_content += content_delta
                    
                    # 如果有stream_callback,转发delta事件
                    if stream_callback and (content_delta or reasoning_delta):
                        stream_callback({
                            "type": "intent_delta", 
                            "content_delta": content_delta,
                            "reasoning_delta": reasoning_delta
                        })
                
                intent_summary_md = await intent_agent.run(intent_inputs, stream=True, observer=_intent_observer)
                
                # 生成结构化数据
                now = datetime.now().isoformat()
                intent_data = {
                    "project_name": self._get_project_name(project_path),
                    "project_root": project_path,
                    "content": full_content or intent_summary_md,
                    "created_at": now,
                    "updated_at": now,
                    "source": "agent",
                }
                
                # 写入文件
                self._write_intent_file(project_path, intent_data)
                events.stage_end("intent_analysis", has_output=bool(intent_summary_md))
            
                if intent_agent and intent_agent.last_usage:
                    # 只有当usage数据有效（不是全0）时才发送事件
                    if _is_valid_usage(intent_agent.last_usage):
                        call_usage, session_usage = self.usage_agg.update(intent_agent.last_usage, None)
                        self._notify(stream_callback, {
                            "type": "usage_summary",
                            "usage_stage": "intent",
                            "usage": intent_agent.last_usage,
                            "call_usage": call_usage,
                            "session_usage": session_usage,
                        })
                    self.pipe_logger.log(
                        "intent_usage",
                        {
                            "usage": intent_agent.last_usage,
                            "trace_id": self.trace_id,
                        },
                    )
            else:
                # 跳过 Intent Agent
                intent_summary_md = None
                events.stage_end("intent_analysis", skipped=True)

        except Exception as exc:
            logger.warning("intent agent failed: %s", exc)
            events.stage_end("intent_analysis", error=str(exc))
            intent_summary_md = None

        # Planning Phase
        plan = {}
        if "planner" in active_agents:
            events.stage_start("planner")
            
            try:
                planner_index = build_planner_index(diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch)
                planner_model = getattr(getattr(self.planner_adapter, "client", None), "model", None)
                started_at = time.monotonic()
                planner_content_streamed = False

                def _planner_observer(evt: Dict[str, Any]) -> None:
                    nonlocal planner_content_streamed
                    if not stream_callback:
                        return
                    try:
                        reasoning = evt.get("reasoning_delta")
                        content = evt.get("content_delta")
                        if content is not None and len(content) > 0:
                            planner_content_streamed = True
                        if reasoning or content:
                            stream_callback(
                                {
                                    "type": "planner_delta",
                                    "content_delta": content,
                                    "reasoning_delta": reasoning,
                                }
                            )
                    except Exception as e:
                        if hasattr(self, "pipe_logger"):
                            self.pipe_logger.log("planner_observer_error", {"error": str(e)})

                self.pipe_logger.log(
                    "planner_attempt",
                    {
                        "attempt": 0,
                        "max_attempts": 1,
                        "provider": self.planner_provider,
                        "model": planner_model,
                    },
                )

                planner_state = ConversationState()
                planner = PlanningAgent(self.planner_adapter, planner_state, logger=self.pipe_logger)
                plan = await planner.run(
                    planner_index,
                    stream=False,
                    observer=None,
                    intent_md=intent_summary_md,
                    user_prompt=prompt,
                )
                if not isinstance(plan, dict):
                    raise RuntimeError("planner returned invalid plan payload")

                self.pipe_logger.log(
                    "planner_attempt_result",
                    {
                        "attempt": 0,
                        "provider": self.planner_provider,
                        "model": planner_model,
                        "ok": True,
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                        "error": None,
                    },
                )
                
                # 将规划结果作为上下文决策发送到前端
                if stream_callback and not planner_content_streamed:
                    try:
                        plan_summary = json.dumps(plan, ensure_ascii=False, indent=2)
                        stream_callback({
                            "type": "planner_delta",
                            "content_delta": plan_summary,
                            "reasoning_delta": None,
                        })
                    except Exception:
                        pass
                
                events.stage_end("planner")

                planner_usage = getattr(planner, "last_usage", None)
                if planner_usage and _is_valid_usage(planner_usage):
                    call_usage, session_usage = self.usage_agg.update(planner_usage, 0)
                    self.pipe_logger.log(
                        "planner_usage",
                        {
                            "call_index": 0,
                            "usage": planner_usage,
                            "call_usage": call_usage,
                            "session_usage": session_usage,
                            "trace_id": self.trace_id,
                        },
                    )
                    self._notify(stream_callback, {
                        "type": "usage_summary",
                        "usage_stage": "planner",
                        "call_index": 0,
                        "usage": planner_usage,
                        "call_usage": call_usage,
                        "session_usage": session_usage,
                    })
            except Exception as exc:
                if stream_callback:
                    try:
                        self._notify(stream_callback, {
                            "type": "error",
                            "stage": "planner",
                            "message": str(exc),
                        })
                    except Exception:
                        pass
                logger.exception("planner failed")
                events.stage_end("planner", error=str(exc))
                raise
        else:
            events.stage_start("planner")
            events.stage_end("planner", skipped=True)

        # 如果不执行 reviewer，直接返回中间结果
        if "reviewer" not in active_agents:
            if "planner" in active_agents:
                return json.dumps(plan, ensure_ascii=False, indent=2)
            if "intent" in active_agents:
                return intent_summary_md or ""
            return "No agents executed."

        try:
            # Fusion & Context Phase
            events.stage_start("fusion")
            fused = fuse_plan(diff_ctx.review_index, plan)
            
            events.stage_start("context_provider")
            events.stage_start("context_bundle")
            
            context_bundle = build_context_bundle(diff_ctx, fused)
            bundle_stats = self._summarize_context_bundle(context_bundle)
            
            logger.info(
                "plan fused provider=%s plan_units=%d bundle_items=%d",
                self.review_provider,
                len(plan.get("plan", [])) if isinstance(plan, dict) else 0,
                len(context_bundle),
            )
            self.pipe_logger.log("planning_output", {"plan": plan})
            self.pipe_logger.log("fusion_output", {"fused": fused})
            
            events.stage_end("fusion")
            events.stage_end("final_context_plan")
            
            self.pipe_logger.log(
                "context_bundle_summary",
                {
                    "bundle_size": len(context_bundle),
                    "unit_ids": [c.get("unit_id") for c in context_bundle],
                    "bundle_stats": bundle_stats,
                },
            )

            if stream_callback:
                for item in context_bundle:
                    events.bundle_item(item)
            
            events.stage_end("context_bundle")
            events.stage_end("context_provider")

        except Exception as exc:
            logger.exception("pipeline failure after planner")
            self.pipe_logger.log(
                "pipeline_error",
                {"stage": "post_planner", "error": repr(exc), "trace_id": self.trace_id},
            )
            self._notify(stream_callback, {
                "type": "error",
                "stage": "post_planner",
                "message": str(exc),
            })
            raise

        # Review Phase
        # 设置 diff_units 上下文，供工具获取扫描结果时进行过滤
        from Agent.core.context.runtime_context import set_diff_units
        set_diff_units(diff_ctx.units or [])
        
        runtime = ToolRuntime()
        for name, func in get_tool_functions(tool_names).items():
            runtime.register(name, func)
        
        tp = resolve_tools(tool_names, auto_approve)
        tools = tp["schemas"]
        auto_approve_list = tp["auto_approve"]

        context_provider = ContextProvider()
        state = ConversationState()
        
        # 如果提供了消息历史，加载到 ConversationState 中
        if message_history:
            for msg in message_history:
                role = msg.get("role")
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")
                
                if role == "user":
                    state.add_user_message(str(content))
                elif role == "assistant":
                    state.add_assistant_message(str(content), tool_calls or [])
                elif role == "system":
                    state.add_system_message(str(content))

        trace_logger = APILogger(trace_id=self.trace_id)

        review_limits = _get_review_prompt_limits()
        review_index_md, _ = build_markdown_and_json_context(diff_ctx, max_files=4, max_changes_per_file=2)
        review_index_md = _truncate_prompt_text(
            review_index_md,
            review_limits["review_index_max_chars"],
            label="审查索引",
        ) or ""
        compact_bundle = compact_prompt_context_bundle(context_bundle)
        ctx_json = json.dumps({"context_bundle": compact_bundle}, ensure_ascii=False, indent=2)
        compact_intent_md = _truncate_prompt_text(
            intent_summary_md,
            review_limits["intent_max_chars"],
            label="项目意图摘要",
        )
        self.pipe_logger.log(
            "review_prompt_budget",
            {
                "review_index_chars": len(review_index_md),
                "intent_chars": len(compact_intent_md or ""),
                "context_items_original": len(context_bundle),
                "context_items_kept": compact_bundle["kept_items"],
                "context_items_omitted": compact_bundle["omitted_items"],
                "context_chars": compact_bundle["approx_chars"],
            },
        )
        augmented_prompt = build_review_prompt(review_index_md, ctx_json, prompt, intent_md=compact_intent_md)
        self.pipe_logger.log(
            "review_request",
            {
                "mode": diff_ctx.mode.value,
                "prompt_preview": augmented_prompt[:2000],
                "context_bundle_size": len(context_bundle),
                "trace_id": self.trace_id,
            },
        )

        events.stage_start("reviewer")
        
        agent = CodeReviewAgent(
            self.review_adapter, runtime, context_provider, state, 
            trace_logger=trace_logger,
            file_tree=project_file_tree
        )

        def _dispatch_stream(evt: Dict[str, Any]) -> None:
            """为用量事件补充聚合统计并记录日志。"""
            usage = evt.get("usage")
            call_index = evt.get("call_index")
            stage = evt.get("usage_stage") or ("planner" if call_index == 0 else "review")
            enriched = dict(evt)

            # 如果有usage字段，检查其有效性
            if usage:
                # 只有usage有效时才更新聚合数据
                if _is_valid_usage(usage):
                    call_usage, session_usage = self.usage_agg.update(usage, call_index)
                    enriched["call_usage"] = call_usage
                    enriched["session_usage"] = session_usage
                    enriched["usage_stage"] = stage
                    if self.pipe_logger and evt.get("type") == "usage_summary":
                        self.pipe_logger.log(
                            "review_call_usage",
                            {
                                "call_index": call_index,
                                "usage_stage": stage,
                                "usage": usage,
                                "call_usage": call_usage,
                                "session_usage": session_usage,
                                "trace_id": self.trace_id,
                            },
                        )
                else:
                    # usage无效（全0），如果是usage_summary事件则不发送
                    if evt.get("type") == "usage_summary":
                        return  # 直接返回，不通知前端
            
            # 通知前端（包括非usage事件和有效的usage事件）
            self._notify(stream_callback, enriched)


        tool_approver_cast = cast(Optional[Callable[[List[NormalizedToolCall]], List[NormalizedToolCall]]], tool_approver)
        result = await agent.run(
            augmented_prompt,
            files=diff_ctx.files,
            stream_observer=_dispatch_stream,
            tools=tools,  # type: ignore[arg-type]
            auto_approve_tools=auto_approve_list,
            tool_approver=tool_approver_cast,
        )
        
        self.pipe_logger.log("review_result", {"result_preview": str(result)[:500]})
        events.stage_end("reviewer")
        
        # 解析审查主题作为会话命名
        # 优先使用第二个标题（跳过固定的"代码审查报告"等格式标题）
        if stream_callback and isinstance(result, str):
            import re
            
            # 定义需要跳过的固定报告标题模式
            generic_titles = {
                "代码审查报告", "审查报告", "代码审查", "code review report",
                "code review", "review report", "审查结果", "审查总结",
                "变更审查", "变更审查报告"
            }
            
            # 匹配所有标题（#、##、### 等）
            heading_pattern = r'^#{1,3}\s+(.+?)(?:\s*L\d+.*)?$'
            all_headings = re.findall(heading_pattern, result, re.MULTILINE)
            
            session_title = None
            for heading in all_headings:
                # 清理 Markdown 格式
                cleaned = re.sub(r'[#*`\[\]:：]', '', heading).strip()
                # 跳过空标题和固定报告标题
                if not cleaned:
                    continue
                # 检查是否为固定报告标题（不区分大小写）
                if cleaned.lower() in {t.lower() for t in generic_titles}:
                    continue
                # 检查是否以 "文件:" 开头（跳过文件标题）
                if cleaned.startswith("文件") or cleaned.lower().startswith("file"):
                    continue
                # 找到有意义的标题
                session_title = cleaned[:20]  # 限制长度
                break
            
            # 如果没找到有意义的标题，使用第一个标题
            if not session_title and all_headings:
                session_title = re.sub(r'[#*`\[\]:：]', '', all_headings[0]).strip()[:20]
            
            if session_title:
                self._notify(stream_callback, {
                    "type": "session_title",
                    "title": session_title,
                    "trace_id": self.trace_id,
                })
        
        fb_summary = fallback_tracker.emit_summary(logger=logger, pipeline_logger=self.pipe_logger)
        if fb_summary.get("total"):
            self._notify(stream_callback, {
                "type": "warning",
                "message": f"回退触发 {fb_summary['total']} 次：{fb_summary['by_key']}",
                "fallback_summary": fb_summary,
            })
            
        self.pipe_logger.log(
            "session_end",
            {
                "log_path": str(self.session_log),
                "session_usage": self.usage_agg.session_totals(),
                "trace_id": self.trace_id,
            },
        )
        events.stage_end("final_output", result_preview=str(result)[:300])
        
        return result
