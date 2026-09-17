from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunUITests(unittest.TestCase):
    def test_run_ui_serves_frontend_and_health(self) -> None:
        port = _free_port()
        env = os.environ.copy()
        env["RUN_UI_NO_BROWSER"] = "1"
        env["RUN_UI_SKIP_FRONTEND_BUILD"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "run_ui.py", "--no-browser", "--no-reload", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            health_url = f"http://127.0.0.1:{port}/api/v2/health"
            root_url = f"http://127.0.0.1:{port}/"
            ready = False
            for _ in range(60):
                if proc.poll() is not None:
                    break
                try:
                    with urlopen(health_url, timeout=2) as response:
                        if response.status == 200:
                            ready = True
                            break
                except URLError:
                    time.sleep(0.5)

            if not ready:
                output = ""
                if proc.stdout is not None and proc.poll() is not None:
                    output = proc.stdout.read()
                self.fail(f"run_ui.py did not become ready on port {port}.\n{output}")

            with urlopen(root_url, timeout=2) as response:
                self.assertEqual(response.status, 200)
            with urlopen(health_url, timeout=2) as response:
                self.assertEqual(response.status, 200)
        finally:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            if proc.stdout is not None:
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
