from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = ROOT / "frontend" / "react" / "src"


class FrontendContractTests(unittest.TestCase):
    def test_frontend_only_references_api_v2(self) -> None:
        pattern = re.compile(r"['\"](/api[^'\"]*)['\"]")
        violations: list[str] = []

        for path in FRONTEND_SRC.rglob("*.ts*"):
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                value = match.group(1)
                if value.startswith("/api/v2"):
                    continue
                violations.append(f"{path.relative_to(ROOT)} -> {value}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
