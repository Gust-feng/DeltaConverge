"""使用当前工作区构建 Windows 目录式程序，不复制本机运行数据。"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.metadata
import hashlib
import json
from pathlib import Path
import shutil
import site
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="新建构建目录，不覆盖已有目录")
    parser.add_argument("--skip-frontend-build", action="store_true", help="使用已有前端产物")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows EXE 需要在 Windows 上构建")
    output = (args.output or ROOT / "dist" / f"windows-{datetime.now():%Y%m%d-%H%M%S}").resolve()
    if output.exists():
        parser.error(f"输出目录已存在: {output}")
    importlib.metadata.version("pyinstaller")
    if not args.skip_frontend_build:
        npm = shutil.which("npm")
        if not npm:
            parser.error("前端构建需要 npm；使用 --skip-frontend-build 可复用已验证产物")
        subprocess.run([npm, "--prefix", str(ROOT / "frontend/react"), "run", "build"], check=True, cwd=ROOT)
    if not (ROOT / "frontend/react/dist/index.html").is_file():
        parser.error("缺少前端构建产物")
    source_files = [ROOT / "scripts/windows_entry.py", ROOT / "legacy/ui_v1/dialogs.py"]
    for directory in ("Agent", "kernel", "adapters", "UI"):
        source_files.extend(path for path in (ROOT / directory).rglob("*.py") if "__pycache__" not in path.parts and "data" not in path.relative_to(ROOT).parts)
    source_hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source_files)}
    output.mkdir(parents=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--console", "--contents-directory", ".", "--name", "DeltaConverge",
        "--icon", str(ROOT / "scripts/assets/DeltaConverge.ico"),
        "--paths", str(ROOT), "--distpath", str(output),
        "--workpath", str(output / "build"), "--specpath", str(output / "build"),
    ]
    for source, destination in [
        (ROOT / "frontend/react/dist", "frontend/react/dist"),
        (ROOT / "Agent/core/api/models_config.json", "Agent/core/api"),
        (ROOT / "Agent/core/llm/catalog", "Agent/core/llm/catalog"),
        (ROOT / ".env.example", "."),
        (ROOT / "LICENSE", "."),
    ]:
        command.extend(["--add-data", f"{source};{destination}"])
    # 项目按文件名收集，避免为发现模块而执行旧示例或开发工具。
    for directory in ("Agent", "kernel", "adapters", "UI"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            if any(part in {"data", "__pycache__", "examples"} for part in path.relative_to(ROOT).parts):
                continue
            parts = list(path.relative_to(ROOT).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            command.extend(["--hidden-import", ".".join(parts)])
    command.extend(["--hidden-import", "legacy.ui_v1.dialogs"])
    for package in ("uvicorn", "unidiff", "pylint", "flake8", "mypy", "semgrep"):
        command.extend(["--collect-all", package])
    for package in ("pytest", "IPython", "notebook", "matplotlib"):
        command.extend(["--exclude-module", package])
    command.append(str(ROOT / "scripts/windows_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    changed = [name for name, digest in source_hashes.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    if changed:
        raise RuntimeError(f"构建期间源码发生变化，请重新构建: {changed}")
    runtime = output / "DeltaConverge"
    # Mypyc 的顶层共享扩展由编译模块动态导入，静态分析无法发现。
    for directory in site.getsitepackages():
        for extension in Path(directory).glob("*__mypyc*.pyd"):
            shutil.copy2(extension, runtime / extension.name)
    versions = {}
    for name in ("pyinstaller", "fastapi", "uvicorn", "openai", "httpx", "pydantic", "pylint", "flake8", "mypy", "semgrep"):
        versions[name] = importlib.metadata.version(name)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.version,
        "layout": "onedir-flat",
        "entry": "DeltaConverge.exe",
        "versions": versions,
        "source_sha256": source_hashes,
        "notes": "不包含本机 .env、数据库、历史会话、日志或学习规则；Git 和非 Python 扫描器需另装。",
    }
    (runtime / "BUILD-INFO.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runtime": str(runtime), "exe": str(runtime / "DeltaConverge.exe")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
