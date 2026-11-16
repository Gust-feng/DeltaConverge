from __future__ import annotations

import asyncio
import ast
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from Agent.core.api.intent import IntentAPI
from kernel.application.stages.intent_stage import IntentStage
from kernel.application.stages.llm_setup_stage import LLMSetupStage
from kernel.domain.context import PipelineContext
from kernel.domain.models import ScanResult
from kernel.infrastructure.persistence import FileArtifactStore, SQLiteKernelStore


def test_artifact_paths_and_cascade(tmp_path):
    files = FileArtifactStore(tmp_path / "artifacts")
    params = dict(session_id="s", run_id="r", kind="report", content="ok", extension="txt", mime_type="text/plain")
    for field, value in [("session_id", "../out"), ("run_id", "a/b"), ("kind", "x\\y"), ("extension", "../txt")]:
        with pytest.raises(ValueError):
            files.save_text(**(params | {field: value}))
    artifact = files.save_text(**params)
    artifact.rel_path = "../outside"
    with pytest.raises(ValueError):
        files.read_text(artifact)
    store = SQLiteKernelStore(tmp_path / "kernel.db")
    store.create_session(session_id="s", name="s", project_root=None)
    store.create_run(run_id="r", session_id="s", prompt="p", model="m", enable_static_scan=False, diff_mode=None, commit_from=None, commit_to=None)
    store.add_message(session_id="s", run_id="r", role="user", content="p")
    store.append_event(run_id="r", session_id="s", event_type="start", stage=None, payload={})
    artifact = files.save_text(**params)
    store.register_artifact(artifact)
    store.upsert_scan_result(ScanResult(run_id="r", session_id="s", artifact_id=artifact.id, created_at=artifact.created_at, summary={}, issues_by_severity={}, linked={}))
    store.delete_session("s")
    with store._connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        for table in ("sessions", "runs", "messages", "events", "artifacts", "scan_results"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_frontend_traversal_and_spa(tmp_path):
    source = Path("adapters/web/app.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    route = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "serve_frontend")
    route.decorator_list = []
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("app")
    (tmp_path / "secret.txt").write_text("secret")
    ns = dict(dist_dir=dist, FileResponse=FileResponse, HTMLResponse=HTMLResponse, JSONResponse=JSONResponse, PureWindowsPath=PureWindowsPath)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])), str(source), "exec"), ns)
    app = FastAPI()
    app.add_api_route("/{path:path}", ns["serve_frontend"], methods=["GET"])
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            assert (await client.get("/%2e%2e/secret.txt")).status_code == 404
            assert (await client.get("/dashboard")).text == "app"
            assert (await client.get("/api/missing")).status_code == 404
            assert (await ns["serve_frontend"]("C:\\secret.txt")).status_code == 404
    asyncio.run(check())


def test_intent_cache_identity_and_controls(tmp_path):
    a, b = str(tmp_path / "a" / "service"), str(tmp_path / "b" / "service")
    cache = tmp_path / "cache"
    engine = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(summary="fresh", usage=None)))
    config = Mock(get_config=Mock(return_value={"review": {"enable_intent_cache": True, "intent_cache_ttl_days": 1}}))
    stage = IntentStage(intent_engine=engine, runtime_context=Mock(), git_port=Mock(), project_port=Mock(), config_port=config)
    stage._collect_intent_inputs = Mock(return_value={})
    with patch.object(IntentStage, "_cache_dir", return_value=cache), patch.object(IntentAPI, "_get_preferred_cache_dir", return_value=cache):
        IntentAPI.save_intent_cache(a, "from a")
        assert not IntentAPI.get_intent_cache(b)["found"]
        async def execute(root):
            ctx = PipelineContext(request=SimpleNamespace(agents=["intent"]), run=None, session_id="s", project_root=root, trace_id="trace")
            await stage.execute(ctx, Mock())
            return ctx
        assert asyncio.run(execute(a)).intent_summary == "from a"
        assert asyncio.run(execute(b)).intent_summary == "fresh"
        config.get_config.return_value["review"]["enable_intent_cache"] = False
        assert asyncio.run(execute(a)).intent_summary == "fresh"
        config.get_config.return_value["review"]["enable_intent_cache"] = True
        IntentStage._write_intent_file(a, {"project_root": a, "content": "old", "source": "agent", "updated_at": (datetime.now() - timedelta(days=2)).isoformat()})
        assert asyncio.run(execute(a)).intent_summary == "fresh"
        IntentAPI.update_intent_cache(a, "manual")
        assert asyncio.run(execute(a)).intent_summary == "manual"


def test_trace_is_forwarded():
    runtime = SimpleNamespace(client=object(), provider="test", adapter=object())
    factory = Mock(create_runtime_client=Mock(return_value=runtime), resolve_planner_preference=Mock(return_value="model"))
    ctx = PipelineContext(request=SimpleNamespace(model="model", planner_model=None), run=None, session_id="s", project_root=None, trace_id="original")
    asyncio.run(LLMSetupStage(llm_factory=factory).execute(ctx, Mock()))
    assert ctx.trace_id == "original"
    factory.create_runtime_client.assert_called_once_with("model", trace_id="original")


def test_cleanup_continues_after_client_failure(tmp_path):
    import kernel.application.review_orchestrator as module
    from kernel.application.event_bus import RunEventBus
    from kernel.domain.models import ReviewCreateRequest

    second = SimpleNamespace(aclose=AsyncMock())
    class Pipeline:
        def __init__(self, *args):
            pass
        async def run(self, ctx):
            ctx.review_client = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("close failed")))
            ctx.planner_client = second
            raise RuntimeError("original failure")

    emitter = Mock(raw_log=[], flush=AsyncMock())
    runtime = Mock()
    store = Mock()
    bus = RunEventBus()
    orchestrator = module.ReviewOrchestrator(
        store=store, artifact_store=FileArtifactStore(tmp_path / "artifacts"), event_bus=bus,
        llm_factory=Mock(), git_port=Mock(), diff_port=Mock(), runtime_context=runtime,
        scan_runner=Mock(), context_port=Mock(), prompt_port=Mock(), config_port=Mock(),
        project_port=Mock(), tool_policy=Mock(), intent_engine=Mock(), planner_engine=Mock(),
        fusion_engine=Mock(), reviewer_engine=Mock())
    with patch.object(module, "PipelineExecutor", Pipeline), patch.object(module, "WorkflowEventEmitter", return_value=emitter):
        asyncio.run(orchestrator._run_review(ReviewCreateRequest(prompt="probe", project_root=str(tmp_path)), SimpleNamespace(id="r", session_id="s")))
    second.aclose.assert_awaited_once()
    runtime.reset.assert_called_once()
    emitter.flush.assert_awaited_once()
    assert bus.is_closed("r")
    assert any(call.kwargs.get("error_message") == "original failure" for call in store.update_run.call_args_list)
    store.register_artifact.assert_called_once()


def test_legacy_and_pipeline_read_same_manual_intent(tmp_path):
    from Agent.core.review_kernel import ReviewKernel
    from kernel.intent_cache import cache_path

    root = str(tmp_path / "repo")
    other = str(tmp_path / "other" / "repo")
    cache_dir = tmp_path / "cache"
    legacy = object.__new__(ReviewKernel)
    assert Path(legacy._get_intent_file_path(root)) == Path(IntentStage._get_intent_file_path(root))
    with patch.object(IntentAPI, "_get_preferred_cache_dir", return_value=cache_dir), \
         patch.object(IntentStage, "_cache_dir", return_value=cache_dir), \
         patch.object(ReviewKernel, "_get_intent_file_path", lambda self, project: str(cache_path(cache_dir, project))):
        assert IntentAPI.update_intent_cache(root, "manually edited")["success"]
        assert legacy._read_intent_file(root)["content"] == "manually edited"
        assert IntentStage._read_intent_file(root)["content"] == "manually edited"
        assert legacy._read_intent_file(other) is None
        assert IntentStage._read_intent_file(other) is None


def test_legacy_refresh_removes_only_matching_caches(tmp_path):
    import json
    from Agent.core.review_kernel import ReviewKernel
    from kernel.intent_cache import cache_path

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    project = str(tmp_path / "a" / "service")
    other = str(tmp_path / "b" / "service")
    legacy_path = cache_dir / "service.json"
    legacy = object.__new__(ReviewKernel)
    with patch.object(ReviewKernel, "_get_intent_file_path", lambda self, root: str(cache_path(cache_dir, root))):
        cache_path(cache_dir, project).write_text(json.dumps({"project_root": project, "content": "new"}), encoding="utf-8")
        legacy_path.write_text(json.dumps({"project_root": project, "content": "old"}), encoding="utf-8")
        legacy.update_intent_file(project)
        assert legacy._read_intent_file(project) is None
        assert not legacy_path.exists()

        cache_path(cache_dir, project).write_text(json.dumps({"project_root": project, "content": "new"}), encoding="utf-8")
        legacy_path.write_text(json.dumps({"project_root": other, "content": "other"}), encoding="utf-8")
        legacy.update_intent_file(project)
        assert legacy._read_intent_file(project) is None
        assert legacy._read_intent_file(other)["content"] == "other"
        assert legacy_path.exists()
