from __future__ import annotations

from adapters.web import desktop_window


def test_find_edge_returns_none_off_windows(monkeypatch):
    monkeypatch.setattr(desktop_window.sys, "platform", "linux")
    assert desktop_window.find_edge() is None


def test_open_app_window_uses_edge(monkeypatch):
    calls = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs

    monkeypatch.setattr(desktop_window, "find_edge", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(desktop_window.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        desktop_window.webbrowser, "open", lambda _url: calls.setdefault("browser", True)
    )

    assert desktop_window.open_app_window("http://127.0.0.1:54321/") == "app"
    assert calls["args"][0] == r"C:\Edge\msedge.exe"
    assert calls["args"][1] == "--app=http://127.0.0.1:54321/"
    assert "browser" not in calls


def test_open_app_window_falls_back_to_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(desktop_window, "find_edge", lambda: None)
    monkeypatch.setattr(desktop_window.webbrowser, "open", opened.append)

    assert desktop_window.open_app_window("http://127.0.0.1:54321/") == "browser"
    assert opened == ["http://127.0.0.1:54321/"]


def test_force_browser_skips_edge(monkeypatch):
    opened = []
    monkeypatch.setattr(desktop_window, "find_edge", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(desktop_window.webbrowser, "open", opened.append)

    assert desktop_window.open_app_window("http://127.0.0.1:54321/", force_browser=True) == "browser"
    assert opened == ["http://127.0.0.1:54321/"]
