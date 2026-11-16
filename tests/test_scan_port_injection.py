from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from Agent.DIFF.rule.scanner_lang_python import Flake8Scanner, MypyScanner, PylintScanner
from Agent.DIFF.static_scan_service import _execute_file_scan_sync, run_static_scan
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


def _scanner_process(scanner_name: str, target: Path) -> Mock:
    outputs = {
        "flake8": f"{target}:1:1: F821 undefined name 'missing_name'\n",
        "pylint": json.dumps([{
            "type": "error", "line": 1, "column": 0,
            "message": "Undefined variable 'missing_name'", "message-id": "E0602",
        }]),
        "mypy": f'{target}:1:1: error: Name "missing_name" is not defined [name-defined]\n',
    }
    process = Mock(returncode=1)
    process.communicate.return_value = (outputs[scanner_name].encode("utf-8"), b"")
    process.poll.return_value = 1
    return process


@pytest.mark.parametrize("scanner_class", [Flake8Scanner, PylintScanner, MypyScanner])
@pytest.mark.parametrize("with_content", [False, True])
@pytest.mark.parametrize("path_mode", [
    "absolute_root", "relative_root", "absolute_file", "no_root", "no_root_relative",
])
def test_scanners_use_target_project_file(scanner_class, with_content, path_mode) -> None:
    service_cwd = Path.cwd()
    # Keep this temporary directory on the service's drive so relative roots also
    # work on Windows. The repository contains spaces and a nested target file.
    with tempfile.TemporaryDirectory(dir=service_cwd) as td:
        root = Path(td) / "target repo"
        target = root / "src" / "demo.py"
        target.parent.mkdir(parents=True)
        disk_content = "print(missing_name)\n"
        target.write_text(disk_content, encoding="utf-8")
        supplied_content = "# supplied content\n"
        file_path = "src/demo.py"
        project_root = str(root)
        if path_mode == "relative_root":
            project_root = os.path.relpath(root, service_cwd)
        elif path_mode == "absolute_file":
            file_path = str(target)
            project_root = str(Path(td) / "unrelated repo")
        elif path_mode == "no_root":
            file_path = str(target)
            project_root = None
        elif path_mode == "no_root_relative":
            file_path = os.path.relpath(target, service_cwd)
            project_root = None

        scanner = scanner_class(config={"enabled": True})
        with patch.object(scanner, "is_available", return_value=True), \
             patch.object(scanner, "scan", wraps=scanner.scan) as scan, \
             patch("Agent.DIFF.rule.scanner_performance.AvailabilityCache.check", return_value=(True, 0)), \
             patch("Agent.DIFF.rule.scanner_base.subprocess.Popen",
                   return_value=_scanner_process(scanner.name, target)) as popen, \
             patch("os.chdir", side_effect=AssertionError("Scanning must not change process cwd")):
            issues, _ = _execute_file_scan_sync(
                file_path, supplied_content if with_content else None, [scanner], project_root,
            )

        popen.assert_called_once()
        command = popen.call_args.args[0]
        assert command[1:3] == ["-m", scanner.name]
        assert Path(command[-1]).is_absolute()
        assert Path(command[-1]) == target.resolve()
        assert Path(command[-1]).read_text(encoding="utf-8") == disk_content
        scan.assert_called_once_with(
            str(target.resolve()), supplied_content if with_content else disk_content,
        )
        assert len(issues) == 1
        assert issues[0]["scanner"] == scanner.name
        assert "missing_name" in issues[0]["message"]
        assert Path.cwd() == service_cwd


def test_static_scan_keeps_relative_result_and_event_paths(tmp_path) -> None:
    root = tmp_path / "external repo"
    root.mkdir()
    target = root / "demo.py"
    target.write_text("print(missing_name)\n", encoding="utf-8")
    scanner = Flake8Scanner(config={"enabled": True})
    events = []
    with patch.object(scanner, "is_available", return_value=True), \
         patch("Agent.DIFF.static_scan_service.ScannerRegistry.get_available_scanners", return_value=[scanner]), \
         patch("Agent.DIFF.rule.scanner_performance.AvailabilityCache.check", return_value=(True, 0)), \
         patch("Agent.DIFF.rule.scanner_base.subprocess.Popen",
               return_value=_scanner_process(scanner.name, target)) as popen:
        result = asyncio.run(run_static_scan(
            files=["demo.py"], units=[], project_root=str(root), callback=events.append,
        ))

    assert Path(popen.call_args.args[0][-1]) == target.resolve()
    assert result.files_scanned == result.files_total == 1
    assert result.total_issues == result.error_count == 1
    assert set(result.issues_by_file) == {"demo.py"}
    assert result.issues_by_file["demo.py"][0]["rule_id"] == "F821"
    file_events = [event for event in events if event["type"] in {
        "static_scan_file_start", "static_scan_file_done",
    }]
    assert len(file_events) == 2
    assert all(event["file"] == "demo.py" for event in file_events)


if __name__ == "__main__":
    unittest.main()

