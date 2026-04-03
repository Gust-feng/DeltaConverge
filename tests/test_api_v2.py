from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from adapters.web.app import create_app
from adapters.web.dependencies import get_facade
from kernel.application import KernelFacade, ReviewOrchestrator, RunEventBus
from kernel.application.services.config_service import ConfigService
from kernel.application.services.project_service import ProjectService
from kernel.application.services.review_service import ReviewService
from kernel.application.services.rule_service import RuleService
from kernel.application.services.session_service import SessionService
from kernel.application.services.system_service import SystemService
from kernel.infrastructure import FileArtifactStore, SQLiteKernelStore


class APIV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        store = SQLiteKernelStore(root / "kernel.db")
        artifacts = FileArtifactStore(root / "artifacts")
        event_bus = RunEventBus()
        orchestrator = ReviewOrchestrator(store, artifacts, event_bus)
        review_service = ReviewService(store, artifacts, event_bus, orchestrator)
        session_service = SessionService(store, artifacts)
        config_service = ConfigService()
        project_service = ProjectService()
        rule_service = RuleService()
        system_service = SystemService()
        self.facade = KernelFacade(
            store=store,
            artifact_store=artifacts,
            event_bus=event_bus,
            orchestrator=orchestrator,
            review_service=review_service,
            session_service=session_service,
            config_service=config_service,
            project_service=project_service,
            rule_service=rule_service,
            system_service=system_service,
        )

        session = store.create_session(session_id="sess-api", name="API Session", project_root="Z:/repo")
        run = store.create_run(
            run_id="run-api",
            session_id=session.id,
            prompt="prompt",
            model="auto",
            enable_static_scan=False,
            diff_mode="working",
            commit_from=None,
            commit_to=None,
        )
        store.add_message(session_id=session.id, run_id=run.id, role="user", content="hello")
        store.append_event(run_id=run.id, session_id=session.id, event_type="review.started", stage=None, payload={})

        app = create_app()
        app.dependency_overrides[get_facade] = lambda: self.facade
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_health_and_sessions_endpoints(self) -> None:
        health = self.client.get("/api/v2/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        sessions = self.client.get("/api/v2/sessions")
        self.assertEqual(sessions.status_code, 200)
        self.assertEqual(sessions.json()["count"], 1)

        detail = self.client.get("/api/v2/sessions/sess-api")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["summary"]["id"], "sess-api")

        events = self.client.get("/api/v2/sessions/sess-api/events?run_id=run-api")
        self.assertEqual(events.status_code, 200)
        self.assertEqual(events.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
