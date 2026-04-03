#!/usr/bin/env python3
"""
DeltaConverge 打包脚本
将整个系统打包成独立的 Windows exe 程序

使用方法:
    1. 安装 PyInstaller: pip install pyinstaller
    2. 运行打包脚本: python build_exe.py
    3. 打包完成后，可执行文件在 dist/DeltaConverge/ 目录中

注意事项:
    - 打包前请确保项目可以正常运行
    - 首次打包可能需要较长时间
    - 打包后的程序需要系统已安装 Git
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_pyinstaller():
    """检查 PyInstaller 是否已安装。"""
    try:
        import PyInstaller
        print(f"✓ PyInstaller 版本: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("✗ PyInstaller 未安装")
        return False


def check_pillow():
    """检查 Pillow 是否已安装（用于图标转换）。"""
    try:
        from PIL import Image
        print("✓ Pillow 已安装")
        return True
    except ImportError:
        print("✗ Pillow 未安装")
        return False


def install_dependencies():
    """安装打包所需依赖。"""
    print("正在安装打包依赖...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0", "Pillow>=10.0.0"])
    print("✓ 依赖安装完成")


def convert_icon(project_root: Path) -> Path | None:
    """将 jpg 图片转换为 ico 格式。"""
    try:
        from PIL import Image
        
        # 源图片路径
        jpg_path = project_root / "UI" / "static" / "resource" / "weixin-410.jpg"
        ico_path = project_root / "deltaconverge.ico"
        
        if not jpg_path.exists():
            print(f"⚠ 图标源文件不存在: {jpg_path}")
            return None
        
        print(f"正在转换图标: {jpg_path}")
        
        # 打开图片并转换为 RGBA
        img = Image.open(jpg_path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        
        # 生成多种尺寸的图标（Windows 图标标准尺寸）
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        # 保存为 ico 格式
        img.save(ico_path, format="ICO", sizes=sizes)
        
        print(f"✓ 图标转换完成: {ico_path}")
        return ico_path
        
    except Exception as e:
        print(f"⚠ 图标转换失败: {e}")
        return None


def install_pyinstaller():
    """安装 PyInstaller。"""
    print("正在安装 PyInstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"])
    print("✓ PyInstaller 安装完成")


def clean_build_dirs(project_root: Path):
    """清理之前的构建目录。"""
    dirs_to_clean = ["build", "dist"]
    for dir_name in dirs_to_clean:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"清理目录: {dir_path}")
            shutil.rmtree(dir_path)


def prepare_clean_diff_dir(project_root: Path) -> Path:
    """准备一个干净的 DIFF 目录副本，排除敏感数据。
    
    Returns:
        干净的 DIFF 目录临时路径
    """
    import fnmatch
    import tempfile
    
    # 创建临时目录
    temp_diff_dir = Path(tempfile.gettempdir()) / "deltaconverge_clean_diff"
    if temp_diff_dir.exists():
        shutil.rmtree(temp_diff_dir)
    
    # 要排除的文件和目录模式
    excluded_patterns = [
        "__pycache__",           # Python 缓存
        "*.pyc",                 # 编译的 Python 文件
        "conflicts",             # 冲突记录目录
        "learned_rules.json",    # 学习到的规则（用户数据）
    ]
    
    def should_exclude(name: str) -> bool:
        for pattern in excluded_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False
    
    def copy_clean_dir(src: Path, dst: Path) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if should_exclude(item.name):
                continue
            if item.is_dir():
                copy_clean_dir(item, dst / item.name)
            else:
                shutil.copy2(item, dst / item.name)
    
    # 复制干净的 DIFF 目录
    diff_src = project_root / "Agent" / "DIFF"
    copy_clean_dir(diff_src, temp_diff_dir)
    
    # 创建空的 learned_rules.json 文件（程序需要这个文件存在）
    learned_rules_path = temp_diff_dir / "rule" / "learned_rules.json"
    learned_rules_path.parent.mkdir(parents=True, exist_ok=True)
    learned_rules_path.write_text(
        '{"learned_rules": [], "version": "1.0", "created_at": null}',
        encoding="utf-8"
    )
    
    # 创建空的 conflicts 目录和 .gitkeep
    conflicts_dir = temp_diff_dir / "issue" / "conflicts"
    conflicts_dir.mkdir(parents=True, exist_ok=True)
    (conflicts_dir / ".gitkeep").write_text(
        "# This directory stores conflict records\n",
        encoding="utf-8"
    )
    
    print(f"✓ 准备干净的 DIFF 目录: {temp_diff_dir}")
    return temp_diff_dir


def create_spec_file(project_root: Path, icon_path: Path | None = None, clean_diff_dir: Path | None = None) -> Path:
    """创建 PyInstaller spec 文件。
    
    Args:
        project_root: 项目根目录
        icon_path: 可选的图标文件路径（.ico 格式）
        clean_diff_dir: 干净的 DIFF 目录路径（排除敏感数据后的副本）
    """
    # 构建图标路径表示
    if icon_path and icon_path.exists():
        icon_repr = f'r"{icon_path}"'
    else:
        icon_repr = "None"
    
    # 构建干净 DIFF 目录路径表示
    if clean_diff_dir and clean_diff_dir.exists():
        clean_diff_dir_str = str(clean_diff_dir)
    else:
        # 回退到原始目录（不推荐）
        clean_diff_dir_str = str(project_root / "Agent" / "DIFF")
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
"""
DeltaConverge PyInstaller 打包配置
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# 项目根目录
project_root = Path(r"{project_root}")

block_cipher = None

# 收集第三方包的数据文件和隐式导入
collected_datas = []
collected_binaries = []
collected_hiddenimports = []

# 收集 unidiff 包的所有内容
for pkg in ['unidiff', 'httpx', 'httpcore', 'anyio', 'sniffio', 'h11', 'certifi', 'pydantic', 'pydantic_core', 'pylint', 'flake8', 'mypy', 'semgrep']:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
        collected_datas.extend(pkg_datas)
        collected_binaries.extend(pkg_binaries)
        collected_hiddenimports.extend(pkg_hiddenimports)
    except Exception:
        pass

# 收集数据文件 - 只打包必要的静态资源，不包含任何用户数据
datas = [
    # UI 静态文件（HTML, CSS, JS）- 必须包含
    (str(project_root / "UI" / "static"), "UI/static"),
    # Agent DIFF 规则配置 - 使用干净的临时副本（排除冲突数据和学习到的规则）
    (r"{clean_diff_dir_str}", "Agent/DIFF"),
    # 环境配置示例
    (str(project_root / ".env.example"), "."),
]

# 注意：以下目录不打包，因为可能包含敏感数据：
# - UI/data (会话数据、密钥配置)
# - Agent/data (分析结果、历史会话)
# - Agent/config (可能包含配置缓存)
# - Agent/DIFF/issue/conflicts (冲突记录) - 已排除
# - Agent/DIFF/rule/learned_rules.json (学习到的规则) - 已清空
# - etc (文档，可选，用户可单独获取)
# 程序启动时会自动创建所需的空目录

# 过滤不存在的路径
datas = [(src, dst) for src, dst in datas if os.path.exists(src)]

# 隐式导入（PyInstaller 可能无法自动检测的模块）
hiddenimports = [
    # FastAPI 和相关依赖
    "fastapi",
    "starlette",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.templating",
    "starlette.middleware",
    "starlette.middleware.cors",
    "uvicorn",
    "uvicorn.config",
    "uvicorn.main",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.logging",
    # HTTP 客户端
    "httpx",
    "httpx._transports",
    "httpx._transports.default",
    "httpcore",
    "h11",
    "anyio",
    "anyio._backends._asyncio",
    "sniffio",
    # OpenAI 客户端
    "openai",
    "openai._client",
    "openai.types",
    # Pydantic
    "pydantic",
    "pydantic.deprecated",
    "pydantic.deprecated.decorator",
    "pydantic_core",
    # 项目模块 - 详细列出所有子模块
    "UI",
    "UI.server",
    "UI.dialogs",
    "Agent",
    "Agent.agents",
    "Agent.agents.analysis_agent",
    "Agent.agents.context_scheduler",
    "Agent.agents.review_kernel",
    "Agent.core",
    "Agent.core.api",
    "Agent.core.api.client",
    "Agent.core.api.provider",
    "Agent.core.context",
    "Agent.core.context.prompts",
    "Agent.core.context.runtime_context",
    "Agent.core.state",
    "Agent.core.state.session",
    "Agent.core.scanner",
    "Agent.core.scanner.scanner",
    "Agent.DIFF",
    "Agent.DIFF.diff_parser",
    "Agent.DIFF.diff_analyzer",
    "Agent.DIFF.rule_engine",
    "Agent.config",
    # 其他依赖 - 详细列出子模块
    "dotenv",
    "python_dotenv",
    "yaml",
    "unidiff",
    "unidiff.constants",
    "unidiff.patch",
    "unidiff.errors",
    "psutil",
    "certifi",
    "email_validator",
    "json",
    "asyncio",
    "concurrent.futures",
    "multiprocessing",
    "ssl",
    "socket",
    "webbrowser",
    "logging",
    "logging.handlers",
    "re",
    "pathlib",
    "datetime",
    "typing",
    "collections",
    "functools",
    "itertools",
    "subprocess",
    "shutil",
    "tempfile",
    "hashlib",
    "base64",
    "urllib",
    "urllib.parse",
    "urllib.request",
]

# 排除不需要的模块（减小体积）
excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "cv2",
    "pygame",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "hypothesis",
    "sphinx",
    "_pytest",
    "doctest",
]

a = Analysis(
    [str(project_root / "run_app.py")],
    pathex=[str(project_root)],
    binaries=collected_binaries,
    datas=datas + collected_datas,
    hiddenimports=hiddenimports + collected_hiddenimports,
    hookspath=[str(project_root / "hooks")],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DeltaConverge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 显示控制台窗口（方便查看日志）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={icon_repr},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DeltaConverge",
)
'''
    
    spec_path = project_root / "deltaconverge.spec"
    with open(spec_path, "w", encoding="utf-8") as f:
        f.write(spec_content)
    
    print(f"✓ 创建 spec 文件: {spec_path}")
    return spec_path


def run_pyinstaller(project_root: Path, spec_path: Path):
    """运行 PyInstaller 打包。"""
    print("\n" + "=" * 60)
    print("开始打包...")
    print("=" * 60 + "\n")
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path),
    ]
    
    subprocess.check_call(cmd, cwd=project_root)


def create_launcher_script(dist_dir: Path):
    """创建启动脚本和说明文件。"""
    # 创建启动批处理文件
    launcher_bat = dist_dir / "启动DeltaConverge.bat"
    bat_content = '''@echo off
chcp 65001 > nul
echo.
echo ========================================
echo    DeltaConverge 代码审查系统
echo ========================================
echo.
echo 正在启动服务...
echo 启动后将自动打开浏览器
echo.
echo 按 Ctrl+C 可停止服务
echo.
cd /d "%~dp0DeltaConverge"
DeltaConverge.exe
pause
'''
    with open(launcher_bat, "w", encoding="utf-8") as f:
        f.write(bat_content)
    
    # 创建不打开浏览器的启动脚本
    launcher_nobrowser = dist_dir / "启动DeltaConverge(无浏览器).bat"
    bat_nobrowser = '''@echo off
chcp 65001 > nul
echo.
echo ========================================
echo    DeltaConverge 代码审查系统
echo ========================================
echo.
echo 正在启动服务 (不自动打开浏览器)...
echo.
echo 服务启动后请手动访问: http://127.0.0.1:54321
echo.
echo 按 Ctrl+C 可停止服务
echo.
cd /d "%~dp0DeltaConverge"
DeltaConverge.exe --no-browser
pause
'''
    with open(launcher_nobrowser, "w", encoding="utf-8") as f:
        f.write(bat_nobrowser)
    
    # 创建使用说明
    readme_path = dist_dir / "使用说明.txt"
    readme_content = '''DeltaConverge - 智能代码审查系统
====================================

【系统要求】
- Windows 10/11 64位系统
- 已安装 Git (用于代码分析)

【启动方法】
1. 双击"启动DeltaConverge.bat"启动服务
2. 服务启动后会自动打开浏览器
3. 如果浏览器未自动打开，请手动访问: http://127.0.0.1:54321

【命令行参数】
在命令行中可以使用以下参数:
  --host 地址      监听地址 (默认: 127.0.0.1)
  --port 端口      监听端口 (默认: 54321)
  --no-browser    不自动打开浏览器
  --no-reload     禁用热重载

示例: DeltaConverge.exe --port 8080 --no-browser

【配置API密钥】
1. 启动服务后，在 Web 界面中配置模型与 API 密钥
2. 或者在程序目录下创建 .env 文件配置密钥

【停止服务】
在控制台窗口按 Ctrl+C 即可停止服务

【常见问题】
Q: 提示端口被占用？
A: 程序会自动查找可用端口，或使用 --port 参数指定其他端口

Q: 无法分析代码？
A: 请确保系统已安装 Git 并可在命令行使用

====================================
更多信息请访问: https://github.com/Gust-feng/DeltaConverge
'''
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print(f"✓ 创建启动脚本: {launcher_bat}")
    print(f"✓ 创建使用说明: {readme_path}")


def copy_env_example(project_root: Path, dist_dir: Path):
    """复制环境变量示例文件。"""
    src = project_root / ".env.example"
    dst = dist_dir / "DeltaConverge" / ".env.example"
    if src.exists():
        shutil.copy2(src, dst)
        print(f"✓ 复制环境变量示例: {dst}")


def main():
    """主函数。"""
    print("=" * 60)
    print("        DeltaConverge 打包工具")
    print("=" * 60)
    print()
    
    project_root = Path(__file__).parent.resolve()
    print(f"项目目录: {project_root}")
    
    # 检查并安装依赖
    needs_install = False
    if not check_pyinstaller():
        needs_install = True
    if not check_pillow():
        needs_install = True
    if needs_install:
        install_dependencies()
    
    # 转换图标
    icon_path = convert_icon(project_root)
    
    # 准备干净的 DIFF 目录（排除冲突数据和学习到的规则）
    clean_diff_dir = prepare_clean_diff_dir(project_root)
    
    # 清理旧的构建目录
    clean_build_dirs(project_root)
    
    # 创建 spec 文件
    spec_path = create_spec_file(project_root, icon_path, clean_diff_dir)
    
    # 运行 PyInstaller
    run_pyinstaller(project_root, spec_path)
    
    # 创建启动脚本和说明
    dist_dir = project_root / "dist"
    create_launcher_script(dist_dir)
    copy_env_example(project_root, dist_dir)
    
    print("\n" + "=" * 60)
    print("        打包完成！")
    print("=" * 60)
    print()
    print(f"输出目录: {dist_dir}")
    print()
    print("文件说明:")
    print("  - DeltaConverge/         程序主目录")
    print("  - 启动DeltaConverge.bat  快速启动脚本")
    print("  - 使用说明.txt           使用说明文档")
    print()
    print("提示: 可以将整个 dist 目录打包分发给用户")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n打包已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n打包失败: {e}")
        sys.exit(1)
