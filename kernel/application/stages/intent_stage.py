"""Intent 分析 Stage。

负责：
1. 收集项目文件树、README、git 历史等轻量上下文
2. 检查意图文件缓存，命中则跳过 Agent 调用
3. 调用 IntentAgent 生成项目意图摘要
4. 将结果写入缓存文件并设置 ctx.intent_summary
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from kernel.domain.context import IntentStageOutput, PipelineContext
from kernel.domain.protocols import EventEmitter
from kernel.ports.engines import IntentEnginePort
from kernel.ports.git import GitPort
from kernel.ports.project import ProjectPort
from kernel.ports.runtime import RuntimeContextPort

logger = logging.getLogger(__name__)


class IntentStage:
    """项目意图分析。"""

    def __init__(
        self,
        *,
        intent_engine: IntentEnginePort | None = None,
        runtime_context: RuntimeContextPort | None = None,
        git_port: GitPort | None = None,
        project_port: ProjectPort | None = None,
    ) -> None:
        if intent_engine is None:
            from kernel.infrastructure import LegacyIntentEngine
            intent_engine = LegacyIntentEngine()
        if runtime_context is None:
            from kernel.infrastructure import LegacyRuntimeContextAdapter
            runtime_context = LegacyRuntimeContextAdapter()
        if git_port is None:
            from kernel.infrastructure import LegacyGitAdapter
            git_port = LegacyGitAdapter()
        if project_port is None:
            from kernel.infrastructure import LegacyProjectAdapter
            project_port = LegacyProjectAdapter()
        self.intent_engine = intent_engine
        self.runtime_context = runtime_context
        self.git_port = git_port
        self.project_port = project_port

    @property
    def name(self) -> str:
        return "intent_analysis"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        request = ctx.request
        agents = set(request.agents or ["intent", "planner", "reviewer"])

        if "intent" not in agents:
            return

        # 收集轻量上下文（文件树、README 等）
        intent_inputs = self._collect_intent_inputs(ctx)
        ctx.project_file_tree = intent_inputs.get("file_tree", {})

        # 尝试从缓存读取
        project_path = ctx.project_root or os.getcwd()
        cached = self._read_intent_file(project_path)

        if cached:
            content = cached.get("content") or cached.get("response", {}).get("content", "")
            if str(content).strip():
                ctx.intent_summary = str(content)
                ctx.intent_output = IntentStageOutput(
                    summary=ctx.intent_summary,
                    project_file_tree=ctx.project_file_tree or {},
                    cache_hit=True,
                    source="cache",
                )
                return

        # 运行意图引擎（通过端口，legacy 装配由适配器负责）
        full_content = ""

        def _observer(evt: Dict[str, Any]) -> None:
            nonlocal full_content
            content_delta = evt.get("content_delta") or ""
            reasoning_delta = evt.get("reasoning_delta") or ""
            full_content += content_delta
            if content_delta or reasoning_delta:
                emit.delta("intent", content_delta=content_delta, reasoning_delta=reasoning_delta)

        result = await self.intent_engine.analyze(
            llm_adapter=ctx.planner_adapter,
            intent_input=intent_inputs,
            stream=True,
            observer=_observer,
        )
        ctx.intent_summary = result.summary
        ctx.intent_output = IntentStageOutput(
            summary=ctx.intent_summary,
            project_file_tree=ctx.project_file_tree or {},
            cache_hit=False,
            source="agent",
            usage=result.usage,
        )

        # 写入缓存
        now = datetime.now().isoformat()
        self._write_intent_file(project_path, {
            "project_name": os.path.basename(os.path.abspath(project_path)),
            "project_root": project_path,
            "content": full_content or ctx.intent_summary,
            "created_at": now,
            "updated_at": now,
            "source": "agent",
        })

        # 上报用量
        if result.usage:
            emit.delta("intent", type="usage_summary", usage_stage="intent", usage=result.usage)

    # ------------------------------------------------------------------

    def _collect_intent_inputs(self, ctx: PipelineContext) -> Dict[str, Any]:
        """收集意图引擎所需的轻量上下文（全部经端口访问）。"""
        root_str = self.runtime_context.get_project_root() or ctx.project_root
        project_root = Path(root_str) if root_str else Path(".")

        def _read_readme() -> Optional[str]:
            for name in ["README.md", "readme.md", "README.rst", "readme.rst", "README.txt"]:
                path = project_root / name
                if path.exists() and path.is_file():
                    try:
                        return path.read_text(encoding="utf-8", errors="ignore")[:8000]
                    except Exception:
                        continue
            return None

        def _build_file_tree() -> Dict[str, Any]:
            # 经 ProjectPort 读取 git index 文件列表，失败时回退 GitPort ls-files
            file_tree: Dict[str, Any] = {}

            EXCLUDED_DIRS = {
                "tests/", "test/", "__tests__/", "__pycache__/", ".cache/",
                "node_modules/", "dist/", "build/", ".vscode/", ".idea/",
                ".git/", "venv/", ".venv/", "docs/", "log/", "logs/",
                "data/", "tmp/", "etc/",
            }
            ALLOWED_EXTENSIONS = {
                ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
                ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".swift", ".kt",
                ".md", ".json", ".yaml", ".yml", ".toml", ".html", ".css",
                ".sh", ".sql",
            }

            files = []
            try:
                files = self.project_port.get_git_index_paths(
                    str(project_root), max_entries=5000
                )
                if not files:
                    output, _, _ = self.git_port.run_git(
                        ["ls-files"], cwd=str(project_root)
                    )
                    files = [l.strip() for l in output.splitlines() if l.strip()]
            except Exception:
                # 文件列表获取失败时退化为空树，但需要留痕便于排查
                logger.warning(
                    "读取项目文件列表失败 (project_root=%s)",
                    project_root,
                    exc_info=True,
                )

            def is_allowed(fp: str) -> bool:
                norm = fp.replace("\\", "/").lower()
                for d in EXCLUDED_DIRS:
                    if norm.startswith(d.rstrip("/") + "/") or ("/" + d.rstrip("/") + "/") in norm:
                        return False
                ext = "." + norm.split(".")[-1] if "." in norm else ""
                return ext in ALLOWED_EXTENSIONS

            filtered = [f for f in files if is_allowed(f)]
            for fp in filtered[:150]:
                parts = fp.replace("\\", "/").split("/")
                cur = file_tree
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        cur[part] = None
                    else:
                        if part not in cur:
                            cur[part] = {}
                        cur = cur[part]
            return file_tree

        def _recent_commits():
            try:
                output, _, _ = self.git_port.run_git(
                    ["log", "-n20", "--pretty=format:%h %s"], cwd=str(project_root)
                )
                return [l.strip() for l in output.splitlines() if l.strip()]
            except Exception:
                logger.warning(
                    "读取最近提交历史失败 (project_root=%s)", project_root, exc_info=True
                )
                return []

        return {
            "file_tree": _build_file_tree(),
            "file_list": [],
            "readme_content": _read_readme(),
            "git_history": _recent_commits(),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _get_intent_file_path(project_path: str) -> str:
        project_name = os.path.basename(project_path.rstrip(os.sep))
        agent_dir = Path(__file__).resolve().parents[3] / "Agent"
        data_dir = agent_dir / "data" / "Analysis"
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / f"{project_name}.json")

    @staticmethod
    def _read_intent_file(project_path: str) -> Optional[Dict[str, Any]]:
        fp = IntentStage._get_intent_file_path(project_path)
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                # 缓存损坏或不可读时按未命中处理，但记录原因
                logger.warning("读取意图缓存文件失败 (path=%s)", fp, exc_info=True)
        return None

    @staticmethod
    def _write_intent_file(project_path: str, data: Dict[str, Any]) -> None:
        fp = IntentStage._get_intent_file_path(project_path)
        try:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            # 缓存写入失败不影响本次审查结果，仅记录
            logger.warning("写入意图缓存文件失败 (path=%s)", fp, exc_info=True)
