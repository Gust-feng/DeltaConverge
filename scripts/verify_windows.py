"""复制 Windows 发行目录，在隔离配置和精简 PATH 下验证程序；不调用真实模型。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--skip-scanner-versions", action="store_true", help="仅排查服务，不作为完整发行验收")
    args = parser.parse_args()
    source = args.runtime.resolve()
    if not (source / "DeltaConverge.exe").is_file():
        parser.error("目录缺少 DeltaConverge.exe")
    results = []
    with tempfile.TemporaryDirectory(prefix="DeltaConverge-交接验收-") as temporary:
        base = Path(temporary)
        runtime = base / "中文 空格 Windows"
        shutil.copytree(source, runtime)
        assert not (runtime / ".env").exists()
        assert not (runtime / "data/kernel/kernel.db").exists()
        env = dict(os.environ)
        for name in list(env):
            if any(marker in name.upper() for marker in ("API_KEY", "API_TOKEN", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")):
                env.pop(name)
        env.pop("DEFAULT_PROJECT_ROOT", None)
        git = shutil.which("git")
        env["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")
        if git:
            env["PATH"] += os.pathsep + str(Path(git).parent)
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "RUN_UI_NO_BROWSER": "1", "SEMGREP_ENABLE_VERSION_CHECK": "0", "SEMGREP_SEND_METRICS": "off"})
        executable = runtime / "DeltaConverge.exe"
        for module in (() if args.skip_scanner_versions else ("pylint", "flake8", "mypy", "semgrep")):
            result = subprocess.run([str(executable), "-m", module, "--version"], cwd=base, env=env, capture_output=True, timeout=45)
            output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            assert result.returncode == 0 and result.stdout.strip(), (module, result.returncode, output)
            results.append(f"scanner {module} --version: passed")
            print(results[-1], flush=True)
        sample = base / "sample.py"
        sample.write_text("print(undefined_variable)\n", encoding="utf-8")
        result = subprocess.run([str(executable), "-m", "pylint", "--output-format=json", "--disable=all", "--enable=undefined-variable", str(sample)], cwd=base, env=env, capture_output=True, timeout=45)
        issues = json.loads(result.stdout.decode("utf-8"))
        assert any(issue.get("symbol") == "undefined-variable" for issue in issues), (result.returncode, result.stderr.decode("utf-8", errors="replace"))
        results.append("bundled pylint detects sample error: passed")
        print(results[-1], flush=True)
        if not args.skip_scanner_versions:
            result = subprocess.run([str(executable), "-m", "flake8", "--select=F821", str(sample)], cwd=base, env=env, capture_output=True, timeout=45)
            assert result.returncode == 1 and b"F821" in result.stdout, (result.returncode, result.stdout, result.stderr)
            result = subprocess.run([str(executable), "-m", "mypy", "--no-incremental", "--cache-dir", str(base / "mypy-cache"), str(sample)], cwd=base, env=env, capture_output=True, timeout=60)
            assert result.returncode == 1 and b"name-defined" in result.stdout, (result.returncode, result.stdout, result.stderr)
            rule = base / "sample-rule.yml"
            rule.write_text("rules:\n  - id: verification-print\n    pattern: print($X)\n    message: Package verification\n    languages: [python]\n    severity: WARNING\n", encoding="utf-8")
            result = subprocess.run([str(executable), "-m", "semgrep", "scan", "--config", str(rule), "--json", "--metrics=off", "--disable-version-check", "--no-git-ignore", str(sample)], cwd=base, env=env, capture_output=True, timeout=60)
            scanned = json.loads(result.stdout.decode("utf-8"))
            assert result.returncode == 0 and scanned.get("results"), (result.returncode, scanned, result.stderr.decode("utf-8", errors="replace"))
            results.append("bundled flake8, mypy and Semgrep local-rule sample scans: passed")
            print(results[-1], flush=True)

        project = base / "git project"
        project.mkdir()
        if git:
            def git_run(*arguments: str) -> None:
                subprocess.run([git, "-C", str(project), *arguments], env=env, check=True, capture_output=True)
            git_run("init")
            git_run("config", "user.name", "Package verification")
            git_run("config", "user.email", "verification@example.invalid")
            (project / "sample.py").write_text("value = 1\n", encoding="utf-8")
            git_run("add", "sample.py")
            git_run("commit", "-m", "verification baseline")
            (project / "sample.py").write_text("value = 2\n", encoding="utf-8")
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            port = connection.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        log_path = base / "service.log"
        def request(path: str, payload=None, method="GET"):
            data = None if payload is None else json.dumps(payload).encode("utf-8")
            with urlopen(Request(url + path, data=data, method=method, headers={"Content-Type": "application/json"}), timeout=30) as response:
                content = response.read()
                if "application/json" in response.headers.get("Content-Type", ""):
                    return json.loads(content)
                return content.decode("utf-8")
        with log_path.open("wb") as log:
            process = None
            def start():
                instance = subprocess.Popen([str(executable), "--no-browser", "--port", str(port)], cwd=base, env=env, stdout=log, stderr=subprocess.STDOUT)
                for _ in range(200):
                    if instance.poll() is not None:
                        raise AssertionError(log_path.read_text(encoding="utf-8", errors="replace"))
                    try:
                        if request("/api/v2/health") == {"status": "ok"}:
                            return instance
                    except (URLError, TimeoutError, OSError):
                        time.sleep(0.1)
                instance.terminate()
                instance.wait(timeout=10)
                raise AssertionError("EXE startup timed out")
            try:
                process = start()
                page = request("/")
                assert 'id="root"' in page
                for resource in set(re.findall(r'(?:src|href)=["\'](/[^"\']+)', page)):
                    with urlopen(url + resource, timeout=30) as response:
                        assert response.status == 200 and "text/html" not in response.headers.get("Content-Type", ""), resource
                        assert response.read(), resource
                providers = request("/api/v2/models/providers")
                assert providers
                assert request("/api/v2/sessions")["count"] == 0
                session = request("/api/v2/sessions", {"name": "isolated exe verification"}, "POST")
                assert session["status"] == "ok"
                request("/api/v2/providers/keys", {"provider": "deepseek", "value": "package-verification-placeholder"}, "POST")
                assert (runtime / ".env").is_file()
                if git:
                    checked = request("/api/v2/git/check", {"path": str(project)}, "POST")
                    assert checked.get("is_git_repo") or checked.get("is_git"), checked
                    from urllib.parse import urlencode
                    diff = request("/api/v2/diff/files?" + urlencode({"project_root": str(project), "mode": "working"}))
                    assert "sample.py" in json.dumps(diff), diff
                results.append("EXE HTTP API, React assets, fresh sessions, key persistence and Git diff: passed")
                print(results[-1], flush=True)
                process.terminate()
                process.wait(timeout=15)
                process = start()
                assert request("/api/v2/sessions")["count"] == 1
                keys = request("/api/v2/providers/keys")
                deepseek = next(item for item in keys["providers"] if item["provider"] == "deepseek")
                assert deepseek["configured"] is True
                results.append("EXE session and dummy-key persistence after restart: passed")
                print(results[-1], flush=True)
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        assert "预热导入失败" not in log_text, log_text
        assert "Traceback (most recent call last)" not in log_text, log_text
        results.append("No prewarm import failures; launched without Python/Node on PATH from another cwd: passed")
    report = {"created_at": datetime.now().isoformat(timespec="seconds"), "runtime": "windows/DeltaConverge/", "checks": results, "scanner_checks_skipped": args.skip_scanner_versions, "external_model_calls": False, "limits": ["Same Windows host with isolated PATH/config, not a second clean Windows installation", "Native folder dialog and actual remote model calls not exercised", "Docker daemon unavailable on build host"]}
    if args.report:
        with args.report.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
