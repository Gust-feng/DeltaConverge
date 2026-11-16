"""Windows 目录式发行程序入口。"""

from __future__ import annotations

import argparse
import multiprocessing
import os
from pathlib import Path
import runpy
import socket
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

# 源码方式运行本脚本时，sys.path[0] 是 scripts/，需要把项目根目录补进来。
if not getattr(sys, "frozen", False):
    _project_root = Path(__file__).resolve().parents[1]
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

from adapters.web.desktop_window import open_app_window


SCANNER_MODULES = {"pylint", "flake8", "mypy", "semgrep"}


def run_scanner() -> bool:
    # 扫描适配器使用 sys.executable -m；冻结后仍在独立子进程运行工具。
    if len(sys.argv) < 3 or sys.argv[1] != "-m":
        return False
    module = sys.argv[2]
    if module not in SCANNER_MODULES:
        raise SystemExit(f"不支持的内置工具: {module}")
    sys.argv = [module, *sys.argv[3:]]
    if module == "semgrep":
        # Python CLI 直接调用内置引擎，避免原生包装器回退到外部 pysemgrep。
        from semgrep.console_scripts.pysemgrep import main as semgrep_main
        raise SystemExit(semgrep_main())
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return True


def find_port(host: str, start: int) -> int:
    for port in range(start, min(start + 100, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            try:
                connection.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("未找到可用端口，请通过 --port 指定其他端口")


def open_when_ready(url: str, force_browser: bool = False) -> None:
    for _ in range(120):
        try:
            with urlopen(url + "api/v2/health", timeout=1) as response:
                if response.status == 200:
                    open_app_window(url, force_browser=force_browser)
                    return
        except (OSError, URLError):
            time.sleep(0.25)


def main() -> None:
    multiprocessing.freeze_support()
    if run_scanner():
        return
    parser = argparse.ArgumentParser(description="DeltaConverge 本地代码审查工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=54321)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--browser", action="store_true", help="使用系统默认浏览器，不使用 Edge 应用窗口")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 至 65535 之间")

    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    os.chdir(root)
    if not (root / "frontend/react/dist/index.html").is_file():
        raise SystemExit("缺少界面资源，请完整解压 Windows 程序目录后运行。")
    if not (root / "Agent/core/api/models_config.json").is_file():
        raise SystemExit("缺少模型配置，请重新完整解压程序目录。")
    probe = root / ".write-check"
    try:
        with probe.open("x", encoding="utf-8") as stream:
            stream.write("")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(f"程序目录不可写，请移动到自己的可写目录: {root}\n{exc}") from exc

    port = find_port(args.host, args.port)
    browser_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{browser_host}:{port}/"
    print(f"DeltaConverge\n程序与数据目录: {root}\n服务地址: {url}\n按 Ctrl+C 停止服务；关闭浏览器不会停止服务。", flush=True)
    if not args.no_browser and not os.environ.get("RUN_UI_NO_BROWSER"):
        threading.Thread(target=open_when_ready, args=(url, args.browser), daemon=True).start()

    import uvicorn
    from adapters.web.app import app

    uvicorn.run(app, host=args.host, port=port, reload=False, loop="asyncio", http="h11", ws="none")


if __name__ == "__main__":
    main()
