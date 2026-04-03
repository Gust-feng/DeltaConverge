from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_TSX = ROOT / "frontend" / "react" / "src" / "App.tsx"
UI_SNAPSHOT_DIR = ROOT / "frontend" / "reference" / "ui_snapshot_v1"


class FrontendLayoutContractTests(unittest.TestCase):
    def test_react_app_preserves_legacy_workbench_shell(self) -> None:
        text = APP_TSX.read_text(encoding="utf-8")

        required_tokens = [
            'id="historyDrawer"',
            'id="page-dashboard"',
            'id="page-diff"',
            'id="page-rule-growth"',
            'id="page-review"',
            'id="reportPanel"',
            'id="rightPanel"',
            'id="pickFolderBtn"',
            'id="startReviewBtn"',
            'id="diff-status-hint"',
            'id="toolListContainer"',
        ]

        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_ui_snapshot_baseline_is_preserved(self) -> None:
        self.assertTrue(UI_SNAPSHOT_DIR.exists())
        self.assertTrue((UI_SNAPSHOT_DIR / "README.md").exists())
        self.assertTrue((UI_SNAPSHOT_DIR / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
