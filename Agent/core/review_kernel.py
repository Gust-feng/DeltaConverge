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
                    if not stream_callback:
                        return
                    content_delta = evt.get("content_delta") or ""
                    reasoning_delta = evt.get("reasoning_delta") or ""
                    
                    # 收集完整内容
                    full_reasoning += reasoning_delta
                    full_content += content_delta
                    
                    if content_delta or reasoning_delta:
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
                    "content": full_content,
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
            
            def _planner_observer(evt: Dict[str, Any]) -> None:
                if not stream_callback:
                    return
                try:
                    reasoning = evt.get("reasoning_delta")
                    content = evt.get("content_delta")
                    
                    if reasoning or content:
                        stream_callback(
                            {
                                "type": "planner_delta",
                                "content_delta": content,
                                "reasoning_delta": reasoning,
                            }
                        )
                except Exception:
                    pass

            try:
                planner_index = build_planner_index(diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch)

                # 简化重试机制：最多尝试 2 次（首次 + 1 次重试）
                max_attempts = 2
                retry_delay = 1.0

                plan_error: str | None = None
                last_exc: Exception | None = None
                planner_model = getattr(getattr(self.planner_adapter, "client", None), "model", None)

                for attempt in range(max_attempts):
                    started_at = time.monotonic()

                    # 非首次尝试，通知前端正在重试
                    if attempt > 0 and stream_callback:
                        self._notify(
                            stream_callback,
                            {
                                "type": "warning",
                                "stage": "planner",
                                "message": f"规划模型响应异常，正在进行第 {attempt + 1} 次尝试...",
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                            },
                        )

                    self.pipe_logger.log(
                        "planner_attempt",
                        {
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "provider": self.planner_provider,
                            "model": planner_model,
                        },
                    )

                    try:
                        planner_state = ConversationState()
                        planner = PlanningAgent(self.planner_adapter, planner_state, logger=self.pipe_logger)
                        plan = await planner.run(
                            planner_index,
                            stream=True,
                            observer=_planner_observer,
                            intent_md=intent_summary_md,
                            user_prompt=prompt,
                        )
                        plan_error = plan.get("error") if isinstance(plan, dict) else "invalid_plan"
                        ok = not bool(plan_error)
                        self.pipe_logger.log(
                            "planner_attempt_result",
                            {
                                "attempt": attempt,
                                "provider": self.planner_provider,
                                "model": planner_model,
                                "ok": ok,
                                "duration_ms": int((time.monotonic() - started_at) * 1000),
                                "error": plan_error,
                            },
                        )
                        if ok:
                            break
                    except Exception as exc:
                        last_exc = exc
                        self.pipe_logger.log(
                            "planner_attempt_result",
                            {
                                "attempt": attempt,
                                "provider": self.planner_provider,
                                "model": planner_model,
                                "ok": False,
                                "duration_ms": int((time.monotonic() - started_at) * 1000),
                                "error": f"exception:{type(exc).__name__}: {exc}",
                            },
                        )
                        plan = {"plan": [], "error": f"exception:{type(exc).__name__}: {exc}"}
                        plan_error = plan["error"]

                    # 如果还有重试机会，等待后继续
                    if attempt + 1 < max_attempts:
                        try:
                            await asyncio.sleep(float(retry_delay))
                        except Exception:
                            pass

                if plan_error and last_exc is not None:
                    pass

                if stream_callback and isinstance(plan, dict) and plan.get("error"):
                    self._notify(
                        stream_callback,
                        {
                            "type": "warning",
                            "stage": "planner",
                            "message": f"planner_warning: {plan.get('error')}",
                        },
                    )
                
                # 将规划结果作为上下文决策发送到前端
                if stream_callback:
                    try:
                        plan_to_send: Dict[str, Any]
                        if isinstance(plan, dict):
                            plan_to_send = dict(plan)
                        else:
                            plan_to_send = {"plan": []}
                        if not isinstance(plan_to_send.get("plan"), list):
                            plan_to_send["plan"] = []
                        plan_summary = json.dumps(plan_to_send, ensure_ascii=False, indent=2)
                        stream_callback({
                            "type": "planner_delta",
                            "content_delta": plan_summary,
                            "reasoning_delta": None,
                        })
                        plan = plan_to_send
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
                plan = {"plan": [], "error": f"exception:{type(exc).__name__}: {exc}"}
                if stream_callback:
                    try:
                        stream_callback({
                            "type": "planner_delta",
                            "content_delta": json.dumps(plan, ensure_ascii=False, indent=2),
                            "reasoning_delta": None,
                        })
                    except Exception:
                        pass
                logger.exception("planner failed")
                events.stage_end("planner", error=str(exc))
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

        review_index_md, _ = build_markdown_and_json_context(diff_ctx)
        ctx_json = json.dumps({"context_bundle": context_bundle}, ensure_ascii=False, indent=2)
        augmented_prompt = build_review_prompt(review_index_md, ctx_json, prompt, intent_md=intent_summary_md)
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
