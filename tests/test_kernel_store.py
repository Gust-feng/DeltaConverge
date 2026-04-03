from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kernel.domain.models import ScanResult
from kernel.infrastructure.persistence import FileArtifactStore, SQLiteKernelStore


class KernelStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteKernelStore(root / "kernel.db")
        self.artifacts = FileArtifactStore(root / "artifacts")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_session_run_event_and_artifact_roundtrip(self) -> None:
        session = self.store.create_session(session_id="sess-1", name="Session 1", project_root="Z:/repo")
        run = self.store.create_run(
            run_id="run-1",
            session_id=session.id,
            prompt="review this",
            model="auto",
            enable_static_scan=True,
            diff_mode="working",
            commit_from=None,
            commit_to=None,
        )
        message = self.store.add_message(session_id=session.id, run_id=run.id, role="user", content="hello")
        event = self.store.append_event(
            run_id=run.id,
            session_id=session.id,
            event_type="review.started",
            stage=None,
            payload={"prompt": "review this"},
        )
        artifact = self.artifacts.save_json(
            session_id=session.id,
            run_id=run.id,
            kind="review_diff_snapshot",
            payload={"diff_files": [{"path": "a.py"}], "diff_units": []},
        )
        self.store.register_artifact(artifact)
        self.store.upsert_scan_result(
            ScanResult(
                run_id=run.id,
                session_id=session.id,
                summary={"files_scanned": 1},
                issues_by_severity={"error": []},
                linked={"diff_units": []},
                created_at=artifact.created_at,
                artifact_id=artifact.id,
            )
        )

        detail = self.store.get_session_detail(session.id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.summary.id, session.id)
        self.assertEqual(len(self.store.list_messages(session.id)), 1)
        self.assertEqual(len(self.store.list_events(run.id)), 1)
        self.assertEqual(self.store.get_scan_result(run.id).summary["files_scanned"], 1)
        self.assertEqual(self.artifacts.read_json(artifact)["diff_files"][0]["path"], "a.py")
        self.assertEqual(message.role, "user")
        self.assertEqual(event.seq, 1)


if __name__ == "__main__":
    unittest.main()
