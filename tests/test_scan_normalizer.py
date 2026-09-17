from __future__ import annotations

import unittest

from kernel.infrastructure.scan import LegacyScanCacheSnapshot, build_scan_artifact_payload, build_scan_result, build_scan_summary


class ScanNormalizerTests(unittest.TestCase):
    def test_build_scan_result_from_snapshot(self) -> None:
        snapshot = LegacyScanCacheSnapshot(
            issues_cache={
                "files_total": 3,
                "files_scanned": 2,
                "duration_ms": 14.5,
                "scanners_used": ["ruff", "semgrep"],
                "issues_by_severity": {
                    "error": [{"rule_id": "E1"}],
                    "warning": [{"rule_id": "W1"}],
                },
            },
            linked_cache={"diff_units": [{"unit_id": "u1"}]},
        )

        summary = build_scan_summary(snapshot)
        payload = build_scan_artifact_payload(snapshot)
        result = build_scan_result("run-1", "sess-1", snapshot, created_at="2026-04-02T00:00:00+00:00", artifact_id="art-1")

        self.assertEqual(summary["files_total"], 3)
        self.assertEqual(payload["linked_cache"]["diff_units"][0]["unit_id"], "u1")
        self.assertEqual(result.summary["files_scanned"], 2)
        self.assertEqual(result.issues_by_severity["error"][0]["rule_id"], "E1")
        self.assertEqual(result.linked["diff_units"][0]["unit_id"], "u1")
        self.assertEqual(result.artifact_id, "art-1")


if __name__ == "__main__":
    unittest.main()
