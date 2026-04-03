from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HardCutStructureTests(unittest.TestCase):
    def test_legacy_assets_are_moved_out_of_active_paths(self) -> None:
        self.assertFalse((ROOT / "UI" / "static").exists())
        self.assertFalse((ROOT / "run_app.py").exists())
        self.assertTrue((ROOT / "legacy" / "ui_v1" / "static" / "index.html").exists())
        self.assertTrue((ROOT / "legacy" / "support" / "Dockerfile").exists())
        self.assertTrue((ROOT / "legacy" / "support" / "run_app.py").exists())


if __name__ == "__main__":
    unittest.main()
