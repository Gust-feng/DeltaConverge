"""内核端口可替换性测试。

用 Fake 实现替换端口，验证 application 层确实只依赖端口抽象、不依赖旧的
``Agent/`` 实现。这是"内核独立"的可执行证据：

- 若某个 Stage 仍偷偷直接调用旧模块，注入 Fake 就不会生效，本测试会失败；
- 同时验证 Legacy 适配器满足端口协议（isinstance 检查），
  以及组合根 build_kernel_facade 可被测试替换/隔离。
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kernel.domain.context import PipelineContext
from kernel.domain.models import ReviewCreateRequest, ReviewRun
from kernel.ports.config import ConfigPort, ReviewPromptLimits
from kernel.ports.context import ContextPort
from kernel.ports.engines import (
    FusionEnginePort,
    IntentEnginePort,
    IntentEngineResult,
    PlannerEnginePort,
    PlannerEngineResult,
    ReviewEngineResult,
    ReviewerEnginePort,
)
from kernel.ports.git import DiffMode, DiffResult, GitPort
from kernel.ports.project import ProjectPort
from kernel.ports.runtime import RuntimeContextPort

# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


class FakeEmitter:
    """记录事件的最小 EventEmitter 实现。"""

    def __init__(self) -> None:
        self.events: List[Tuple[str, Dict[str, Any]]] = []

    def stage_started(self, stage: str, **payload: Any) -> None:
        self.events.append(("stage_started", {"stage": stage, **payload}))

    def stage_finished(self, stage: str, **payload: Any) -> None:
        self.events.append(("stage_finished", {"stage": stage, **payload}))

    def delta(self, stage: str, **payload: Any) -> None:
        self.events.append(("delta", {"stage": stage, **payload}))

    def scan_event(self, event_type: str, **payload: Any) -> None:
        self.events.append(("scan_event", {"event_type": event_type, **payload}))

    def tool_event(self, event_type: str, stage: str, **payload: Any) -> None:
        self.events.append(("tool_event", {"event_type": event_type, "stage": stage, **payload}))


class FakeRuntimeContext(RuntimeContextPort):
    """内存版运行时上下文，记录调用轨迹。"""

    def __init__(self) -> None:
        self.project_root: Optional[str] = None
        self.session_id: Optional[str] = None
        self.diff_units: List[Dict[str, Any]] = []
        self.rule_callback: Any = None
        self.cleared: List[Optional[str]] = []
        self.reset_calls = 0

    def set_project_root(self, path: Optional[str]) -> None:
        self.project_root = path

    def get_project_root(self) -> Optional[str]:
        return self.project_root

    def set_session_id(self, session_id: Optional[str]) -> None:
        self.session_id = session_id

    def get_session_id(self) -> Optional[str]:
        return self.session_id

    def set_diff_units(self, units: List[Dict[str, Any]]) -> None:
        self.diff_units = units

    def get_diff_units(self) -> List[Dict[str, Any]]:
        return self.diff_units

    def set_rule_event_callback(self, callback: Any) -> None:
        self.rule_callback = callback

    def clear_file_caches(self, project_root: Optional[str] = None) -> None:
        self.cleared.append(project_root)

    def reset(self) -> None:
        self.reset_calls += 1
        self.project_root = None
        self.session_id = None
        self.diff_units = []
        self.rule_callback = None


class FakeGitPort(GitPort):
    """返回固定内容的 GitPort。"""

    def __init__(self, ls_files: Optional[List[str]] = None) -> None:
        self.ls_files = ls_files or []
        self.run_git_calls: List[List[str]] = []

    def run_git(
        self,
        args: List[str],
        *,
        cwd: Optional[str] = None,
        capture_output: bool = True,
        check: bool = True,
    ) -> Tuple[str, str, int]:
        self.run_git_calls.append(list(args))
        if args and args[0] == "ls-files":
            return "\n".join(self.ls_files), "", 0
        if args and args[0] == "log":
            return "abc1234 fake commit", "", 0
        return "", "", 0

    def get_diff(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        paths: Optional[List[str]] = None,
        context_lines: int = 3,
    ) -> DiffResult:
        return DiffResult(
            mode=mode, base_ref=base_ref, head_ref=head_ref, raw_diff="fake diff"
        )

    def get_diff_text(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        paths: Optional[List[str]] = None,
        context_lines: int = 3,
    ) -> str:
        return "fake diff"

    def get_commit(self, ref: str = "HEAD", *, cwd: Optional[str] = None) -> Any:
        return None

    def get_commit_history(
        self, *, limit: int = 20, cwd: Optional[str] = None
    ) -> List[Any]:
        return []

    def get_file_at_ref(
        self, ref: str, path: str, *, cwd: Optional[str] = None
    ) -> Optional[str]:
        return None

    def get_changed_files(
        self, mode: DiffMode, *, cwd: Optional[str] = None
    ) -> List[Any]:
        return []

    def get_config(self, cwd: Optional[str] = None) -> Any:
        raise NotImplementedError

    def get_current_branch(self, cwd: Optional[str] = None) -> Optional[str]:
        return "fake-branch"

    def get_remote_url(self, *, cwd: Optional[str] = None) -> Optional[str]:
        return None

    def is_git_repo(self, path: str) -> bool:
        return True

    def get_repo_root(self, path: str) -> Optional[str]:
        return path


class FakeProjectPort(ProjectPort):
    """只提供文件列表的 ProjectPort。"""

    def __init__(self, paths: Optional[List[str]] = None) -> None:
        self.paths = paths or []

    def get_git_index_paths(
        self, project_root: str, *, max_entries: int = 5000
    ) -> List[str]:
        return list(self.paths)[:max_entries]

    def get_project_info(self, project_root: str) -> Dict[str, Any]:
        return {}

    def get_file_tree(self, project_root: str) -> Dict[str, Any]:
        return {}

    def get_readme_content(self, project_root: str) -> Dict[str, Any]:
        return {}

    def get_dependencies(self, project_root: str) -> Dict[str, Any]:
        return {}

    def get_git_info(self, project_root: str) -> Dict[str, Any]:
        return {}

    def get_scanner_languages(self) -> List[Dict[str, Any]]:
        return []

    def get_diff_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        return {}

    def get_diff_summary(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def get_diff_files(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    def get_file_diff(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}


class FakeIntentEngine(IntentEnginePort):
    """记录调用并返回固定摘要。"""

    def __init__(self, summary: str = "fake intent summary") -> None:
        self.summary = summary
        self.calls: List[Dict[str, Any]] = []

    async def analyze(
        self,
        *,
        llm_adapter: Any,
        intent_input: Dict[str, Any],
        stream: bool = True,
        observer: Any = None,
    ) -> IntentEngineResult:
        self.calls.append({"intent_input": intent_input, "llm_adapter": llm_adapter})
        if observer is not None:
            observer({"content_delta": "streamed-"})
        return IntentEngineResult(summary=self.summary, usage={"total_tokens": 7})


class FakePlannerEngine(PlannerEnginePort):
    def __init__(self, plan: Optional[Dict[str, Any]] = None) -> None:
        self.plan = plan or {"plan": [{"unit_id": "u1"}]}
        self.calls: List[Dict[str, Any]] = []

    async def plan(
        self,
        *,
        llm_adapter: Any,
        review_index: Dict[str, Any],
        stream: bool = False,
        observer: Any = None,
        intent_summary: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> PlannerEngineResult:
        self.calls.append({"review_index": review_index, "intent_summary": intent_summary})
        return PlannerEngineResult(plan=self.plan, usage={"prompt_tokens": 3})


class FakeFusionEngine(FusionEnginePort):
    """记录输入并返回可预测的融合计划。"""

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, Any]] = []

    def fuse(self, review_index: Dict[str, Any], llm_plan: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append((review_index, llm_plan))
        return {"plan": [{"unit_id": "u1", "final_context_level": "function"}]}


class FakeReviewerEngine(ReviewerEnginePort):
    def __init__(self, report: str = "fake report") -> None:
        self.report = report
        self.calls: List[Dict[str, Any]] = []

    async def review(
        self,
        *,
        llm_adapter: Any,
        prompt: str,
        files: Sequence[str],
        tools: Optional[List[Dict[str, Any]]] = None,
        auto_approve_tools: Optional[List[str]] = None,
        tool_approver: Any = None,
        stream_observer: Any = None,
        trace_id: Optional[str] = None,
        file_tree: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        with_context_provider: bool = True,
    ) -> ReviewEngineResult:
        self.calls.append({"prompt": prompt, "files": list(files)})
        return ReviewEngineResult(report=self.report, usage={"total_tokens": 11})


class FakeContextPort(ContextPort):
    def __init__(self) -> None:
        self.calls: List[Any] = []

    def build_context_bundle(
        self, diff_context: Any, fused_plan: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        self.calls.append(fused_plan)
        return [
            {
                "unit_id": "u1",
                "final_context_level": "function",
                "meta": {"location": "f.py:1"},
                "content": "code",
            }
        ]

    def build_context(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def get_file_context(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def expand_context(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def filter_context(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def merge_contexts(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FakeConfigPort(ConfigPort):
    def __init__(self) -> None:
        self.limits = ReviewPromptLimits()

    def get_review_prompt_limits(self) -> ReviewPromptLimits:
        return self.limits

    def get_config(self) -> Dict[str, Any]:
        return {}

    def update_config(self, updates: Dict[str, Any], *, persist: bool = True) -> Dict[str, Any]:
        return {}

    def get_config_doctor(self) -> Dict[str, Any]:
        return {}

    def get_model_providers(self) -> List[Dict[str, Any]]:
        return []

    def get_tools(self) -> List[Dict[str, Any]]:
        return []


# ──────────────────────────────────────────────────────────────────────
# 测试
# ──────────────────────────────────────────────────────────────────────


def _make_context(project_root: str, agents: Optional[List[str]] = None) -> PipelineContext:
    request = ReviewCreateRequest(
        prompt="review this",
        project_root=project_root,
        agents=agents or ["intent", "planner", "reviewer"],
    )
    run = ReviewRun(
        id="run-test",
        session_id="sess-test",
        prompt="review this",
        model="fake",
        status="running",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    return PipelineContext(
        request=request,
        run=run,
        session_id="sess-test",
        project_root=project_root,
        trace_id="trace-test",
    )


class PortSubstitutionTests(unittest.TestCase):
    """端口可替换性：注入 Fake 后 Stage 必须只走 Fake。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = self._tmp.name

    def tearDown(self) -> None:
        # IntentStage 会把意图缓存写到 Agent/data/Analysis/<项目名>.json，
        # 测试结束后清理，避免污染工作区。
        cache = (
            Path(__file__).resolve().parents[1]
            / "Agent"
            / "data"
            / "Analysis"
            / f"{Path(self.project_root).name}.json"
        )
        if cache.exists():
            cache.unlink()
        self._tmp.cleanup()

    def test_intent_stage_driven_by_injected_engine(self) -> None:
        from kernel.application.stages.intent_stage import IntentStage

        engine = FakeIntentEngine(summary="from-fake-engine")
        runtime = FakeRuntimeContext()
        git = FakeGitPort(ls_files=["pkg/a.py", "pkg/b.py"])
        project = FakeProjectPort(paths=["pkg/a.py", "pkg/b.py"])

        stage = IntentStage(
            intent_engine=engine,
            runtime_context=runtime,
            git_port=git,
            project_port=project,
        )
        ctx = _make_context(self.project_root)
        emitter = FakeEmitter()

        asyncio.run(stage.execute(ctx, emitter))

        # 摘要必须来自 Fake 引擎
        self.assertEqual(ctx.intent_summary, "from-fake-engine")
        self.assertEqual(len(engine.calls), 1)
        # 文件树必须来自 Fake ProjectPort
        self.assertIn("pkg", ctx.project_file_tree)
        self.assertIn("a.py", ctx.project_file_tree["pkg"])
        # 输出契约
        self.assertIsNotNone(ctx.intent_output)
        self.assertEqual(ctx.intent_output.source, "agent")
        self.assertFalse(ctx.intent_output.cache_hit)
        self.assertEqual(ctx.intent_output.usage, {"total_tokens": 7})

    def test_intent_stage_skips_engine_when_agent_disabled(self) -> None:
        from kernel.application.stages.intent_stage import IntentStage

        engine = FakeIntentEngine()
        stage = IntentStage(
            intent_engine=engine,
            runtime_context=FakeRuntimeContext(),
            git_port=FakeGitPort(),
            project_port=FakeProjectPort(),
        )
        ctx = _make_context(self.project_root, agents=["reviewer"])

        asyncio.run(stage.execute(ctx, FakeEmitter()))

        self.assertEqual(engine.calls, [])
        self.assertIsNone(ctx.intent_summary)

    def test_fusion_stage_driven_by_injected_engine(self) -> None:
        from kernel.application.stages.fusion_stage import FusionStage

        engine = FakeFusionEngine()
        context_port = FakeContextPort()
        config_port = FakeConfigPort()

        stage = FusionStage(
            fusion_engine=engine,
            context_port=context_port,
            config_port=config_port,
        )
        ctx = _make_context(self.project_root)

        class _DiffCtx:
            review_index = {"units": [{"unit_id": "u1"}]}

        ctx.diff_ctx = _DiffCtx()
        ctx.plan = {"plan": [{"unit_id": "u1"}]}

        asyncio.run(stage.execute(ctx, FakeEmitter()))

        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(engine.calls[0][1], ctx.plan)
        self.assertEqual(ctx.fused_plan["plan"][0]["unit_id"], "u1")
        self.assertEqual(len(context_port.calls), 1)
        self.assertIsNotNone(ctx.fusion_output)

    def test_runtime_context_port_records_calls(self) -> None:
        runtime = FakeRuntimeContext()
        runtime.set_project_root("/tmp/x")
        runtime.set_session_id("s")
        runtime.set_diff_units([{"u": 1}])
        runtime.set_rule_event_callback(lambda e: None)
        self.assertEqual(runtime.get_project_root(), "/tmp/x")
        self.assertEqual(runtime.get_session_id(), "s")
        self.assertEqual(runtime.get_diff_units(), [{"u": 1}])
        self.assertIsNotNone(runtime.rule_callback)

        runtime.reset()
        self.assertEqual(runtime.reset_calls, 1)
        self.assertIsNone(runtime.get_project_root())
        self.assertEqual(runtime.get_diff_units(), [])


class LegacyAdapterConformanceTests(unittest.TestCase):
    """Legacy 适配器必须满足各自端口协议（isinstance 检查）。"""

    def test_all_legacy_adapters_satisfy_their_ports(self) -> None:
        from kernel import infrastructure as infra
        from kernel.ports.config import ConfigPort as _ConfigPort
        from kernel.ports.context import ContextPort as _ContextPort
        from kernel.ports.conversation import ConversationPort as _ConversationPort
        from kernel.ports.diff import DiffPort as _DiffPort
        from kernel.ports.engines import (
            FusionEnginePort as _FusionEnginePort,
            IntentEnginePort as _IntentEnginePort,
            PlannerEnginePort as _PlannerEnginePort,
            ReviewerEnginePort as _ReviewerEnginePort,
        )
        from kernel.ports.git import GitPort as _GitPort
        from kernel.ports.llm import LLMFactoryPort as _LLMFactoryPort
        from kernel.ports.prompt import PromptPort as _PromptPort
        from kernel.ports.project import ProjectDiffPort as _ProjectDiffPort
        from kernel.ports.project import ProjectPort as _ProjectPort
        from kernel.ports.rule import RulePort as _RulePort
        from kernel.ports.stream import StreamPort as _StreamPort
        from kernel.ports.tool import (
            ToolPolicyPort as _ToolPolicyPort,
            ToolRegistryPort as _ToolRegistryPort,
            ToolRuntimePort as _ToolRuntimePort,
        )

        pairs = [
            (infra.LegacyGitAdapter(), _GitPort),
            (infra.LegacyDiffAdapter(), _DiffPort),
            (infra.LegacyConversationAdapter(), _ConversationPort),
            (infra.LegacyToolRegistry(), _ToolRegistryPort),
            (infra.LegacyToolRuntime(), _ToolRuntimePort),
            (infra.LegacyToolPolicy(), _ToolPolicyPort),
            (infra.LegacyPromptAdapter(), _PromptPort),
            (infra.LegacyContextAdapter(), _ContextPort),
            (infra.LegacyStreamAdapter(), _StreamPort),
            (infra.LegacyLLMFactory(), _LLMFactoryPort),
            (infra.LegacyConfigAdapter(), _ConfigPort),
            (infra.LegacyRuleAdapter(), _RulePort),
            (infra.LegacyProjectAdapter(), _ProjectPort),
            (infra.LegacyProjectDiffAdapter(), _ProjectDiffPort),
            (infra.LegacyRuntimeContextAdapter(), RuntimeContextPort),
            (infra.LegacyIntentEngine(), _IntentEnginePort),
            (infra.LegacyPlannerEngine(), _PlannerEnginePort),
            (infra.LegacyFusionEngine(), _FusionEnginePort),
            (infra.LegacyReviewerEngine(), _ReviewerEnginePort),
        ]
        for adapter, port in pairs:
            with self.subTest(adapter=type(adapter).__name__, port=port.__name__):
                self.assertIsInstance(adapter, port)


class CompositionRootTests(unittest.TestCase):
    """组合根应可在隔离目录下构造，并接受测试注入。"""

    def test_build_kernel_facade_in_isolated_root(self) -> None:
        from kernel.bootstrap import build_kernel_facade

        with tempfile.TemporaryDirectory() as td:
            facade = build_kernel_facade(root=Path(td))
            self.assertIsNotNone(facade)
            self.assertTrue((Path(td) / "data" / "kernel").exists())

            orchestrator = facade.orchestrator
            # 组合根应真正注入端口，而不是留给 Stage 隐式兜底
            for attr in (
                "_intent_engine",
                "_planner_engine",
                "_fusion_engine",
                "_reviewer_engine",
                "_context_port",
                "_prompt_port",
                "_config_port",
                "_project_port",
                "_tool_policy",
                "_runtime_context",
                "_scan_runner",
            ):
                with self.subTest(attr=attr):
                    self.assertIsNotNone(
                        getattr(orchestrator, attr),
                        f"{attr} 未被组合根注入",
                    )

    def test_composition_root_accepts_substituted_ports(self) -> None:
        """组合根构造出的 Stage 应可被 Fake 端口替换（可测试性的直接证据）。"""
        from kernel.application.stages.intent_stage import IntentStage

        engine = FakeIntentEngine(summary="substituted")
        stage = IntentStage(
            intent_engine=engine,
            runtime_context=FakeRuntimeContext(),
            git_port=FakeGitPort(),
            project_port=FakeProjectPort(),
        )
        # 组合根产出的默认 Stage 与注入版共存，说明端口可替换而非硬编码
        default_stage = IntentStage()
        self.assertIsNot(default_stage.intent_engine, engine)
        self.assertIs(stage.intent_engine, engine)


if __name__ == "__main__":
    unittest.main()
