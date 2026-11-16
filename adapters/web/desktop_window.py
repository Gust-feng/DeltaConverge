"""用 Windows 自带的 Edge/WebView2 内核打开独立应用窗口。

优先调用 msedge.exe 的 --app 模式：没有地址栏和标签页，行为接近桌面应用窗口。
找不到 Edge 时回退到系统默认浏览器，保证源码运行和 Windows 发行版都能启动。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

_EDGE_ENV = "DELTACONVERGE_EDGE_EXE"


def _edge_candidates() -> list[Path]:
    roots = {
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.environ.get("LOCALAPPDATA"),
    }
    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return candidates


def _edge_from_registry() -> str | None:
    try:
        import winreg
    except ImportError:
        return None

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(
                hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
            ) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value and Path(value).is_file():
                    return str(value)
        except OSError:
            continue
    return None


def find_edge() -> str | None:
    """返回可用的 Edge 可执行文件路径；非 Windows 或未安装时返回 None。"""
    if sys.platform != "win32":
        return None

    override = os.environ.get(_EDGE_ENV)
    if override and Path(override).is_file():
        return override

    found = shutil.which("msedge")
    if found:
        return found

    for candidate in _edge_candidates():
        if candidate.is_file():
            return str(candidate)

    return _edge_from_registry()


def open_app_window(url: str, *, force_browser: bool = False) -> str:
    """打开界面，返回 ``app``（Edge 应用窗口）或 ``browser``（默认浏览器）。"""
    edge = None if force_browser else find_edge()
    if edge:
        try:
            subprocess.Popen(
                [
                    edge,
                    f"--app={url}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1440,900",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "app"
        except OSError:
            pass

    webbrowser.open(url)
    return "browser"
