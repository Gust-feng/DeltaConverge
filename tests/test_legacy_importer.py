from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kernel.infrastructure.persistence import FileArtifactStore, SQLiteKernelStore
from legacy.tools.legacy_importer import LegacySessionImporter


class LegacyImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.store = SQLiteKernelStore(root / "kernel.db")
        self.artifacts = FileArtifactStore(root / "artifacts")
        self.importer = LegacySessionImporter(self.store, self.artifacts)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_import_legacy_session_file(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "session_id": "legacy-sess",
                    "metadata": {
                        "name": "Legacy Session",
                        "project_root": "Z:/demo",
                        "status": "completed",
                        "tags": ["legacy"],
                    },
                    "messages": [
                        {"role": "user", "content": "请审查"},
                        {"role": "assistant", "content": "# 审查报告\n\n没有明显问题。"},
                    ],
                    "workflow_events": [
                        {"type": "pipeline_stage_start", "stage": "planner"},
                        {"type": "pipeline_stage_end", "stage": "planner", "summary": {"count": 1}},
                    ],
                    "diff_files": [{"path": "app.py"}],
                    "diff_units": [{"unit_id": "u1", "file_path": "app.py"}],
                    "project_file_tree": {"tree": {"app.py": None}},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        result = self.importer.import_file(legacy_path)
        self.assertEqual(result.session.id, "legacy-sess")
        self.assertEqual(result.imported_messages, 2)
        self.assertEqual(result.imported_events, 2)
        self.assertGreaterEqual(result.imported_artifacts, 2)


if __name__ == "__main__":
    unittest.main()
