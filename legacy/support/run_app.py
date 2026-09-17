#!/usr/bin/env python3
"""DeltaConverge 打包入口脚本 - 专为 PyInstaller 打包优化。

此脚本作为打包后程序的入口点，直接在当前进程中启动 uvicorn 服务器，
而不是通过子进程启动，以确保在打包环境中正常工作。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser


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


def is_docker() -> bool:
    """检测是否运行在 Docker 环境。"""
    try:
        env_flags = (
            os.environ.get("RUNNING_IN_DOCKER"),
            os.environ.get("DOCKER"),
            os.environ.get("IS_DOCKER"),
        )
        if any(flag for flag in env_flags if str(flag).lower() in ("1", "true", "yes")):
            return True
        if os.path.exists("/.dockerenv"):
            return True
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


def is_frozen() -> bool:
    """检测是否在 PyInstaller 打包环境中运行。"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_base_path() -> str:
    """获取应用程序基础路径。
    
    在打包环境中返回 _MEIPASS 目录，否则返回脚本所在目录。
    """
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def setup_environment():
    """设置运行环境。"""
    base_path = get_base_path()
    
    # 将基础路径添加到 Python 路径
    if base_path not in sys.path:
        sys.path.insert(0, base_path)
    
    # 设置 PYTHONPATH 环境变量
    current_pythonpath = os.environ.get("PYTHONPATH", "")
    if base_path not in current_pythonpath:
        os.environ["PYTHONPATH"] = base_path + os.pathsep + current_pythonpath
    
    # 切换工作目录
    os.chdir(base_path)
    
    # 创建必要的数据目录（打包时不包含这些目录以保持干净环境）
    required_dirs = [
        os.path.join(base_path, "UI", "data"),
        os.path.join(base_path, "UI", "data", "sessions"),
        os.path.join(base_path, "Agent", "data"),
        os.path.join(base_path, "Agent", "data", "sessions"),
        os.path.join(base_path, "Agent", "data", "Analysis"),
        os.path.join(base_path, "Agent", "config"),
    ]
    
    for dir_path in required_dirs:
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except Exception:
                pass  # 忽略创建失败的情况
    
    return base_path


def open_browser_delayed(url: str, delay: float = 2.0):
    """延迟打开浏览器。"""
    def _open():
        time.sleep(delay)
        print(f"正在打开浏览器: {url}")
        webbrowser.open(url)
    
    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main() -> None:
    """主函数。"""
    parser = argparse.ArgumentParser(description="DeltaConverge 代码审查系统")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", default=54321, type=int, help="起始端口 (默认: 54321)")
    parser.add_argument("--no-reload", action="store_true", help="禁用热重载（打包版自动禁用）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()
    
    # 设置环境
    base_path = setup_environment()
    print(f"工作目录: {base_path}")
    print(f"运行模式: {'打包版' if is_frozen() else '开发版'}")
    
    # 确定监听地址
    host = args.host
    if host == "127.0.0.1" and is_docker():
        host = "0.0.0.0"
        print("检测到 Docker 环境，自动切换到 0.0.0.0")
    
    # 寻找可用端口
    try:
        port = find_free_port(host, args.port)
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)
    
    if port != args.port:
        print(f"注意: 端口 {args.port} 已被占用，自动切换到 {port}")
    
    url = f"http://{host}:{port}/"
    print(f"服务地址: {url}")
    
    # 判断是否自动打开浏览器
    no_browser_env = os.environ.get("RUN_UI_NO_BROWSER")
    should_open_browser = (
        not args.no_browser and 
        not no_browser_env and 
        not is_docker()
    )
    
    if should_open_browser:
        open_browser_delayed(url)
    
    print("按 Ctrl+C 停止服务")
    print("-" * 50)
    
    # 导入并启动 uvicorn
    try:
        import uvicorn
        from UI.server import app
        
        # 在打包环境中禁用 reload
        use_reload = not args.no_reload and not is_frozen()
        
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=use_reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n服务已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
