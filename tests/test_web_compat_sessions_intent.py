from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from adapters.web.dependencies import get_facade
from adapters.web.routers.cache import cache_router
from adapters.web.routers.intents import intents_router
from adapters.web.routers.scans import router as scans_router
from adapters.web.routers.sessions import router as sessions_router
from Agent.core.api.cache import CacheManager
from Agent.core.api.intent import IntentAPI
from kernel.application import KernelFacade, ReviewOrchestrator, RunEventBus
from kernel.application.services.config_service import ConfigService
from kernel.application.services.intent_service import IntentService
from kernel.application.services.project_service import ProjectService
from kernel.application.services.review_service import ReviewService
from kernel.application.services.rule_service import RuleService
from kernel.application.services.session_service import SessionService
from kernel.application.services.system_service import SystemService
from kernel.domain.models import ScanResult, WorkflowEvent
from kernel.infrastructure import FileArtifactStore, SQLiteKernelStore


def _build_facade(tmp_path: Path) -> KernelFacade:
    store = SQLiteKernelStore(tmp_path / "kernel.db")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    event_bus = RunEventBus()
    orchestrator = ReviewOrchestrator(store, artifacts, event_bus)
    review_service = ReviewService(store, artifacts, event_bus, orchestrator)
    session_service = SessionService(store, artifacts)
    return KernelFacade(
        store=store,
        artifact_store=artifacts,
        event_bus=event_bus,
        orchestrator=orchestrator,
        review_service=review_service,
        session_service=session_service,
        config_service=ConfigService(),
        project_service=ProjectService(),
        rule_service=RuleService(),
        system_service=SystemService(),
        intent_service=IntentService(),
    )


def _make_app(facade: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(sessions_router)
    app.include_router(scans_router)
    app.include_router(intents_router)
    app.include_router(cache_router)
    app.dependency_overrides[get_facade] = lambda: facade
    return app


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _patched_cache_dir(cache_dir: Path):
    manager = CacheManager()
    manager._intent_cache_dir = cache_dir
    manager._intent_cache_dirs = [cache_dir]
    with patch.object(IntentAPI, "_get_preferred_cache_dir", return_value=cache_dir), patch(
        "Agent.core.api.cache.get_cache_manager", return_value=manager
    ):
        yield


def _create_run(store: SQLiteKernelStore, session_id: str, run_id: str) -> None:
    store.create_run(
        run_id=run_id,
        session_id=session_id,
        prompt="prompt",
        model="auto",
        enable_static_scan=False,
        diff_mode="working",
        commit_from=None,
        commit_to=None,
    )


def _sse_events(text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in text.split("\n\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


def test_session_create_status_and_chat_404(tmp_path):
    facade = _build_facade(tmp_path)
    app = _make_app(facade)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/v2/sessions", json={"project_root": str(tmp_path)})
            assert created.status_code == 200
            payload = created.json()
            assert payload["status"] == "ok"
            session_id = payload["session"]["id"]
            assert re.fullmatch(r"sess_\d+_[0-9a-f]{8}", session_id)
            assert payload["session"]["project_root"] == str(tmp_path)

            again = await client.post(
                "/api/v2/sessions",
                json={"session_id": session_id, "name": "Renamed", "project_root": str(tmp_path)},
            )
            assert again.status_code == 200
            assert again.json()["session"]["id"] == session_id
            assert again.json()["session"]["name"] == "Renamed"

            status = await client.get(f"/api/v2/sessions/{session_id}/status")
            assert status.status_code == 200
            assert status.json() == {"completed": False, "status": "active"}

            facade.store.update_session(session_id, status="completed")
            completed = await client.get(f"/api/v2/sessions/{session_id}/status")
            assert completed.json() == {"completed": True, "status": "completed"}

            unknown = await client.get("/api/v2/sessions/sess-missing/status")
            assert unknown.status_code == 404
            assert unknown.json()["detail"] == "session_not_found"

            missing_chat = await client.post(
                "/api/v2/sessions/sess-missing/chat", json={"message": "hello"}
            )
            assert missing_chat.status_code == 404
            assert missing_chat.json()["detail"] == "session_not_found"

    _run(scenario())


def test_scan_issues_pagination_and_summary_counts(tmp_path):
    facade = _build_facade(tmp_path)
    store = facade.store
    store.create_session(session_id="sess-scan", name="Scan", project_root=None)
    _create_run(store, "sess-scan", "run-scan")
    app = _make_app(facade)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            missing_run = await client.get("/api/v2/scans/run-missing/issues")
            assert missing_run.status_code == 404
            assert missing_run.json()["detail"] == "run_not_found"

            pending = await client.get("/api/v2/scans/run-scan/issues")
            assert pending.status_code == 404
            assert pending.json()["detail"] == "scan_result_not_found"

            store.upsert_scan_result(
                ScanResult(
                    run_id="run-scan",
                    session_id="sess-scan",
                    summary={"files_total": 3},
                    issues_by_severity={
                        "error": [{"message": f"e{i}"} for i in range(3)],
                        "warning": [{"message": "w0"}],
                        "info": [],
                    },
                    linked={},
                    created_at="2026-01-01T00:00:00Z",
                )
            )

            first = await client.get("/api/v2/scans/run-scan/issues", params={"limit": 2})
            body = first.json()
            assert first.status_code == 200
            assert body["severity"] == "error"
            assert body["offset"] == 0
            assert body["limit"] == 2
            assert body["total"] == 3
            assert body["has_more"] is True
            assert [item["message"] for item in body["issues"]] == ["e0", "e1"]

            tail = await client.get(
                "/api/v2/scans/run-scan/issues", params={"offset": 2, "limit": 2}
            )
            assert tail.json()["has_more"] is False
            assert [item["message"] for item in tail.json()["issues"]] == ["e2"]

            beyond = await client.get(
                "/api/v2/scans/run-scan/issues", params={"offset": 99, "limit": 50}
            )
            assert beyond.json()["issues"] == []
            assert beyond.json()["total"] == 3
            assert beyond.json()["has_more"] is False

            invalid = await client.get(
                "/api/v2/scans/run-scan/issues", params={"severity": "bogus"}
            )
            assert invalid.json()["severity"] == "error"
            assert invalid.json()["total"] == 3

            out_of_range = await client.get(
                "/api/v2/scans/run-scan/issues", params={"limit": 201}
            )
            assert out_of_range.status_code == 422

            full = await client.get("/api/v2/scans/run-scan")
            summary = full.json()["summary"]
            assert summary["total_issues"] == 4
            assert summary["error_count"] == 3
            assert summary["warning_count"] == 1
            assert summary["info_count"] == 0

    _run(scenario())


def test_intent_read_write_and_stream(tmp_path):
    facade = _build_facade(tmp_path)
    app = _make_app(facade)
    project = tmp_path / "proj"
    project.mkdir()
    cache_dir = tmp_path / "intent-cache"
    cache_dir.mkdir()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            updated = await client.post(
                "/api/v2/intent/update",
                json={"project_root": str(project), "content": "# Project intent"},
            )
            assert updated.status_code == 200
            assert updated.json()["success"] is True
            assert updated.json()["project_name"] == "proj"

            fetched = await client.get("/api/v2/intent", params={"project_root": str(project)})
            assert fetched.status_code == 200
            body = fetched.json()
            assert body["found"] is True
            assert body["project_name"] == "proj"
            assert body["content"] == "# Project intent"
            assert body["source"] == "manual"

            empty = await client.post(
                "/api/v2/intent/update",
                json={"project_root": str(project), "content": "   "},
            )
            assert empty.status_code == 400
            assert empty.json()["detail"] == "Content cannot be empty"

            missing = await client.get(
                "/api/v2/intent", params={"project_root": str(tmp_path / "nope")}
            )
            assert missing.status_code == 404
            assert missing.json()["detail"] == "intent_cache_not_found"

            missing_root = await client.get("/api/v2/intent")
            assert missing_root.status_code == 400

            missing_path = await client.post(
                "/api/v2/intent/analyze-stream",
                json={"project_root": str(tmp_path / "does-not-exist"), "model": "m"},
            )
            assert missing_path.status_code == 400

            raw_events = [
                {"type": "progress", "stage": "collecting", "message": "collecting"},
                {"type": "reasoning", "delta": "because"},
                {"type": "content", "delta": "hello "},
                {"type": "content", "delta": "world"},
                {"type": "final", "result": {"content": "# Final"}},
                {"type": "done"},
            ]

            async def fake_stream(project_root, force_refresh=False, model=None):
                for event in raw_events:
                    yield event

            with patch.object(IntentAPI, "run_intent_analysis_sse", new=fake_stream):
                streamed = await client.post(
                    "/api/v2/intent/analyze-stream",
                    json={"project_root": str(project), "model": "m"},
                )
            assert streamed.status_code == 200
            assert streamed.headers["content-type"].startswith("text/event-stream")
            assert _sse_events(streamed.text) == [
                {"type": "thought", "content": "collecting"},
                {"type": "thought", "content": "because"},
                {"type": "chunk", "content": "hello "},
                {"type": "chunk", "content": "world"},
                {"type": "final", "content": "# Final"},
                {"type": "done"},
            ]

    with _patched_cache_dir(cache_dir):
        _run(scenario())


def test_cache_stats_list_and_delete(tmp_path):
    facade = _build_facade(tmp_path)
    app = _make_app(facade)
    project = tmp_path / "proj"
    project.mkdir()
    cache_dir = tmp_path / "intent-cache"
    cache_dir.mkdir()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/api/v2/intent/update",
                json={"project_root": str(project), "content": "# Project intent"},
            )

            stats = await client.get("/api/v2/cache/stats")
            assert stats.status_code == 200
            stats_body = stats.json()
            assert stats_body["intent_cache_count"] == 1
            assert stats_body["intent_cache_size"] == 1
            assert stats_body["diff_cache_size"] == 0
            assert stats_body["projects_cached"] == ["proj"]

            listed = await client.get("/api/v2/cache/intent")
            assert listed.status_code == 200
            entries = listed.json()
            assert len(entries) == 1
            assert entries[0]["project_name"] == "proj"
            assert entries[0]["file_path"].endswith(".json")
            assert entries[0]["size_bytes"] > 0

            deleted = await client.delete(
                "/api/v2/cache/intent", params={"project_name": "proj"}
            )
            assert deleted.status_code == 200
            assert deleted.json() == {"cleared_count": 1, "failed_count": 0, "project": "proj"}

            assert (await client.get("/api/v2/cache/intent")).json() == []
            assert (await client.get("/api/v2/cache/stats")).json()["intent_cache_count"] == 0

    with _patched_cache_dir(cache_dir):
        _run(scenario())


class _FakeChatFacade:
    def __init__(self) -> None:
        self.kwargs: Dict[str, Any] | None = None

    async def create_chat_turn(self, **kwargs):
        self.kwargs = kwargs
        return "run-chat"

    async def stream_review(self, run_id: str):
        yield WorkflowEvent(
            id=1,
            run_id=run_id,
            session_id="sess-chat",
            seq=1,
            type="review.started",
            created_at="2026-01-01T00:00:00Z",
            payload={"run_id": run_id},
        )


def test_chat_endpoint_forwards_legacy_payload_and_streams_envelope(tmp_path):
    fake = _FakeChatFacade()
    app = _make_app(fake)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v2/sessions/sess-chat/chat",
                json={
                    "message": "continue",
                    "model": "deepseek:deepseek-chat",
                    "tools": ["read_file"],
                    "autoApprove": True,
                    "project_root": str(tmp_path),
                },
            )
        assert response.status_code == 200
        assert fake.kwargs == {
            "session_id": "sess-chat",
            "message": "continue",
            "model": "deepseek:deepseek-chat",
            "tools": ["read_file"],
            "auto_approve": True,
            "project_root": str(tmp_path),
        }
        events = _sse_events(response.text)
        assert events == [
            {
                "id": 1,
                "run_id": "run-chat",
                "session_id": "sess-chat",
                "seq": 1,
                "type": "review.started",
                "created_at": "2026-01-01T00:00:00Z",
                "stage": None,
                "payload": {"run_id": "run-chat"},
            }
        ]

    _run(scenario())
