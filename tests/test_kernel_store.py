from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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

    def _create_event_run(self) -> None:
        self.store.create_session(session_id="sess-1", name="Session 1", project_root="Z:/repo")
        self.store.create_run(
            run_id="run-1",
            session_id="sess-1",
            prompt="review this",
            model="auto",
            enable_static_scan=False,
            diff_mode="working",
            commit_from=None,
            commit_to=None,
        )

    def test_append_event_touches_session_in_one_transaction(self) -> None:
        self._create_event_run()
        before = self.store.update_session(
            "sess-1", status="completed", tags=["pinned"], last_error="preserve error"
        )
        statements = []
        original_connect = self.store._connect

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        timestamps = ["2030-01-01T00:00:00+00:00", "2030-01-01T00:00:01+00:00"]
        events = []
        with patch.object(self.store, "_connect", side_effect=traced_connect) as connect:
            for index, timestamp in enumerate(timestamps):
                with patch("kernel.infrastructure.persistence.utc_now", return_value=timestamp):
                    events.append(self.store.append_event(
                        run_id="run-1",
                        session_id="sess-1",
                        event_type="review.delta",
                        stage="review",
                        payload={"content_delta": str(index)},
                    ))
            self.assertEqual(connect.call_count, 2)

        transaction_steps = [
            statement.strip().split()[0].upper()
            for statement in statements
            if statement.strip().split()[0].upper() in {"BEGIN", "INSERT", "UPDATE", "COMMIT"}
        ]
        self.assertEqual(transaction_steps, ["BEGIN", "INSERT", "UPDATE", "COMMIT"] * 2)
        self.assertEqual(self.store.get_session_summary("sess-1"), replace(before, updated_at=timestamps[-1]))
        self.assertEqual(self.store.list_events("run-1"), events)
        self.assertEqual([event.seq for event in events], [1, 2])
        self.assertEqual([event.created_at for event in events], timestamps)
        self.assertEqual([event.payload for event in events], [{"content_delta": "0"}, {"content_delta": "1"}])
        self.assertTrue(all(event.id > 0 for event in events))
        self.assertTrue(all(event.type == "review.delta" and event.stage == "review" for event in events))

    def test_append_event_rolls_back_if_session_touch_fails(self) -> None:
        self._create_event_run()
        before = self.store.get_session_summary("sess-1")
        with self.store._connect() as conn:
            conn.execute(
                """
                CREATE TRIGGER reject_session_touch BEFORE UPDATE OF updated_at ON sessions
                BEGIN
                    SELECT RAISE(ABORT, 'session touch rejected');
                END
                """
            )

        with self.assertRaisesRegex(sqlite3.IntegrityError, "session touch rejected"):
            self.store.append_event(
                run_id="run-1", session_id="sess-1", event_type="review.delta",
                stage="review", payload={"content_delta": "rolled back"},
            )

        self.assertEqual(self.store.list_events("run-1"), [])
        self.assertEqual(self.store.get_session_summary("sess-1"), before)
        with self.store._connect() as conn:
            conn.execute("DROP TRIGGER reject_session_touch")
        event = self.store.append_event(
            run_id="run-1", session_id="sess-1", event_type="review.delta",
            stage="review", payload={"content_delta": "persisted"},
        )
        self.assertEqual(event.seq, 1)
        self.assertEqual(self.store.list_events("run-1"), [event])

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
