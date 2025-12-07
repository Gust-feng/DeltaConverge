#!/usr/bin/env python3
"""一键启动 Web UI 并自动拉起浏览器。"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from urllib.request import urlopen
from urllib.error import URLError


def is_port_in_use(host: str, port: int) -> bool:
    """检查端口是否被占用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def find_free_port(host: str, start_port: int, max_attempts: int = 100) -> int:
    """寻找可用端口。"""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(host, port):
            return port
    raise RuntimeError(f"在 {start_port}-{start_port + max_attempts} 范围内未找到可用端口")


def wait_for_server(url: str, retries: int = 40, interval: float = 0.25) -> bool:
    """轮询等待服务就绪。"""
    try:
        for _ in range(retries):
            try:
                with urlopen(url, timeout=2):
                    return True
            except URLError:
                time.sleep(interval)
    except KeyboardInterrupt:
        return False
    return False


def is_docker() -> bool:
    """检测是否运行在 Docker 环境。
    通过多重信号检测：环境变量、/.dockerenv 文件、cgroup 关键字。
    """
    try:
        # 常见环境变量标记
        env_flags = (
            os.environ.get("RUNNING_IN_DOCKER"),
            os.environ.get("DOCKER"),
            os.environ.get("IS_DOCKER"),
        )
        if any(flag for flag in env_flags if str(flag).lower() in ("1", "true", "yes")):
            return True

        # /.dockerenv 文件
        if os.path.exists("/.dockerenv"):
            return True

        # cgroup 关键字
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
                content = f.read().lower()
                if "docker" in content or "kubepods" in content or "containerd" in content:
                    return True
        except Exception:
            pass
    except Exception:
        pass
    return False

def main() -> None:
    # 确保当前目录在 PYTHONPATH 中
    project_root = os.path.dirname(os.path.abspath(__file__))
    # 将当前目录添加到 PYTHONPATH，确保可以导入 UI 和 Agent 模块
    current_pythonpath = os.environ.get("PYTHONPATH", "")
    if project_root not in current_pythonpath:
        os.environ["PYTHONPATH"] = project_root + os.pathsep + current_pythonpath

    parser = argparse.ArgumentParser(description="启动审查内核 Web UI 并打开浏览器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", default=54321, type=int, help="起始端口 (默认: 54321)")
    parser.add_argument("--no-reload", action="store_true", help="禁用 uvicorn 热重载")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    host = args.host
    if host == "127.0.0.1" and is_docker():
        host = "0.0.0.0"
    try:
        port = find_free_port(host, args.port)
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)

    if port != args.port:
        print(f"注意: 端口 {args.port} 已被占用，自动切换到 {port}")

    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "UI.server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if not args.no_reload:
        uvicorn_cmd.append("--reload")

    print(f"启动服务: {' '.join(uvicorn_cmd)}")
    print(f"工作目录: {project_root}")
    
    # 使用当前环境变量（包含更新后的 PYTHONPATH）
    proc = subprocess.Popen(uvicorn_cmd, env=os.environ, cwd=project_root)

    try:
        url = f"http://{host}:{port}/"
        print(f"等待服务就在 {url} ...")
        ready = wait_for_server(url)
        if ready:
            print(f"服务已就绪: {url}")
            no_browser_env = os.environ.get("RUN_UI_NO_BROWSER")
            if not args.no_browser and not no_browser_env and not is_docker():
                print(f"正在打开浏览器: {url}")
                webbrowser.open(url)
        else:
            print("等待服务就绪超时或被中断，稍后可手动访问。")

        print("服务运行中。按 Ctrl+C 停止服务。")
        proc.wait()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("强制终止服务进程...")
                proc.kill()
        print("服务已停止。")


if __name__ == "__main__":
    main()
