from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from adapters.web.dependencies import get_facade
from adapters.web.routers.scans import router as scans_router
from kernel.application.services.session_service import SessionService
from kernel.domain.models import ScanResult
from kernel.infrastructure import FileArtifactStore, SQLiteKernelStore


REPORT = """## 文件: src/example.py L10-12
严重性: error
问题:
- 未校验输入就执行命令。
建议:
- 在执行前验证输入。

## 文件: src/other.py L30-31
严重性: warning
问题:
- 未处理读取失败。
"""
UNITS = [{
    "unit_id": "unit-example",
    "file_path": "src/example.py",
    "hunk_range": {"new_start": 10, "new_lines": 3},
    "unified_diff": "@@ -10,1 +10,3 @@\n-old\n+new\n+line\n+line\n",
}]


def seed_report(root: Path):
    store = SQLiteKernelStore(root / "kernel.db")
    artifacts = FileArtifactStore(root / "artifacts")
    store.create_session(session_id="session", name="Report", project_root=None)
    store.create_run(
        run_id="run", session_id="session", prompt="review", model="auto",
        enable_static_scan=False, diff_mode="working", commit_from=None, commit_to=None,
    )
    diff = artifacts.save_json(
        session_id="session", run_id="run", kind="review_diff_snapshot",
        payload={"diff_files": [{"path": "src/example.py"}], "diff_units": UNITS},
    )
    store.register_artifact(diff)
    report = artifacts.save_text(
        session_id="session", run_id="run", kind="final_report", content=REPORT,
        extension="md", mime_type="text/markdown",
    )
    store.register_artifact(report)
    store.update_run("run", status="completed", final_report_artifact_id=report.id)
    return store, artifacts


@pytest.mark.parametrize("with_scan", [False, True])
def test_report_issues_are_linked_without_repeating_review(tmp_path, with_scan):
    store, artifacts = seed_report(tmp_path)
    scanner_issue = {"file": "src/example.py", "line": 11, "message": "scanner issue"}
    if with_scan:
        store.upsert_scan_result(ScanResult(
            run_id="run", session_id="session", summary={"total_issues": 1},
            issues_by_severity={"warning": [scanner_issue]},
            linked={"unit_issues": {"unit-example": [scanner_issue]}, "mapped_count": 1},
            created_at="2026-11-16T00:00:00Z",
        ))

    # Reopening storage exercises historical reads with no in-memory scan cache.
    service = SessionService(SQLiteKernelStore(tmp_path / "kernel.db"), artifacts)
    result = service.get_scan_result("run")
    assert result is not None
    linked = result.linked
    assert linked["diff_units"] == UNITS
    assert linked["llm_mapped_count"] >= 1
    assert linked["llm_unmapped_count"] >= 1
    assert any("未校验输入" in issue["message"] for issue in linked["unit_llm_suggestions"]["unit-example"])
    assert any("读取失败" in issue["message"] for issue in linked["llm_unmapped_suggestions"])
    assert linked["unit_llm_suggestions"]["unit-example"][0]["start_line"] == 10
    if with_scan:
        assert result.issues_by_severity == {"warning": [scanner_issue]}
        assert linked["unit_issues"] == {"unit-example": [scanner_issue]}
        assert store.get_scan_result("run").linked == {"unit_issues": {"unit-example": [scanner_issue]}, "mapped_count": 1}
    else:
        assert linked["unit_issues"] == {}
        assert store.get_scan_result("run") is None


def test_scan_endpoint_includes_ai_mapping_when_static_scan_is_disabled(tmp_path):
    store, artifacts = seed_report(tmp_path)
    service = SessionService(store, artifacts)
    app = FastAPI()
    app.include_router(scans_router)

    class Facade:
        get_review_run = service.get_review_run
        get_scan_result = service.get_scan_result

    app.dependency_overrides[get_facade] = lambda: Facade()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v2/scans/run")
        assert response.status_code == 200
        data = response.json()
        assert "status" not in data
        assert data["linked"]["unit_llm_suggestions"]["unit-example"]
        assert data["summary"]["total_issues"] == 0

    asyncio.run(scenario())


def test_scan_arriving_after_report_does_not_remove_ai_mapping(tmp_path):
    store, artifacts = seed_report(tmp_path)
    service = SessionService(store, artifacts)
    before = service.get_scan_result("run").linked["unit_llm_suggestions"]
    store.upsert_scan_result(ScanResult(
        run_id="run", session_id="session", summary={"total_issues": 0},
        issues_by_severity={}, linked={"unit_issues": {}, "diff_units": UNITS},
        created_at="2026-11-16T00:00:00Z",
    ))
    assert service.get_scan_result("run").linked["unit_llm_suggestions"] == before


def test_new_run_and_followup_chat_do_not_replace_the_saved_report(tmp_path):
    store, artifacts = seed_report(tmp_path)
    store.create_run(
        run_id="next-run", session_id="session", prompt="review again", model="auto",
        enable_static_scan=False, diff_mode="working", commit_from=None, commit_to=None,
    )
    store.update_session("session", latest_run_id="next-run")
    store.add_message(
        session_id="session", run_id="next-run", role="assistant",
        content="No findings in this followup chat.", metadata={"channel": "chat"},
    )
    service = SessionService(store, artifacts)
    assert service.get_scan_result("run").linked["llm_mapped_count"] == 2
    assert service.get_scan_result("next-run") is None


def test_report_mapping_appears_when_running_review_completes(tmp_path):
    store, artifacts = seed_report(tmp_path)
    report_id = store.get_run("run").final_report_artifact_id
    store.update_run("run", status="running", final_report_artifact_id="")
    service = SessionService(store, artifacts)
    assert service.get_scan_result("run") is None
    assert service.get_scan_result("missing") is None
    store.update_run("run", status="completed", final_report_artifact_id=report_id)
    assert service.get_scan_result("run").linked["llm_mapped_count"] == 2
