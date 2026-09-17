from __future__ import annotations

import unittest

from kernel.application.stages.diff_stage import DiffStage
from kernel.infrastructure.persistence import FileArtifactStore, SQLiteKernelStore
from kernel.infrastructure.scan.legacy_adapter import LegacyScanServiceAdapter


class ScanPortInjectionTests(unittest.TestCase):
    def test_diff_stage_accepts_scan_service_port(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SQLiteKernelStore(root / "kernel.db")
            artifacts = FileArtifactStore(root / "artifacts")
            adapter = LegacyScanServiceAdapter()
            stage = DiffStage(store=store, artifact_store=artifacts, scan_service=adapter)
            self.assertIs(stage.scan_service, adapter)


if __name__ == "__main__":
    unittest.main()

