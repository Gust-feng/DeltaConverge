"""文件处理模块：处理文件读取、编码处理、语言检测等。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional


DOC_EXTENSIONS = {".md", ".rst", ".txt"}


def read_file_lines(path: str) -> List[str]:
    """Read file contents into a list of lines without newline characters.

    设计目标：
    - 对非文本 / 非 UTF-8 文件保持健壮，不让整个审查流程崩溃。
    - 尽量优先按 UTF-8 读取，失败时降级为“忽略错误”的宽松模式。
    """

    file_path = Path(path)
    if not file_path.exists():
        return []

    try:
        # 先判断是否可能是二进制文件：简单检查前 4KB 是否包含 NUL 字节
        head = file_path.read_bytes()[:4096]
        if b"\x00" in head:
            # 对于明显的二进制文件，直接跳过，避免无意义的解码尝试
            print(f"[diff] 跳过二进制文件: {path}")
            return []
    except OSError as exc:
        print(f"[diff] 读取文件失败（跳过）: {path}: {exc}")
        return []

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 对于非 UTF-8 文本，使用宽松模式读取，防止抛错
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            print(f"[diff] 非 UTF-8 文本，已使用 errors='ignore' 读取: {path}")
        except Exception as exc:  # pragma: no cover - 极端情况
            print(f"[diff] 文本读取失败（跳过）: {path}: {exc}")
            return []

    return text.splitlines()


def parse_python_ast(file_lines: List[str]) -> Optional[ast.AST]:
    """预先解析 Python 源码供后续辅助函数复用。"""

    if not file_lines:
        return None
    try:
        return ast.parse("\n".join(file_lines))
    except SyntaxError:
        return None


def guess_language(path: str) -> str:
    """基于文件扩展名猜测编程语言。"""

    ext = Path(path).suffix.lower()
    if ext in DOC_EXTENSIONS:
        return "text"

    # 常见语言映射
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "cpp",
        ".html": "html",
        ".css": "css",
        ".swift": "swift",
        ".kt": "kotlin",
        ".rs": "rust",
        ".sh": "shell",
        ".bash": "shell",
        ".ps1": "powershell",
        ".lua": "lua",
        # 多语言支持，当然后续可以扩展
    }
    return ext_map.get(ext, "unknown")


def _truncate_doc_block(text: str, max_lines: int = 40) -> str:
    """最多返回 max_lines 行，并在末尾放置清晰的占位标记。"""

    lines = text.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    # 保留 max_lines-1 行，再加一个截断标记，不修改原始列表
    truncated_lines = lines[: max_lines - 1] + ["...(truncated)"]
    return "\n".join(truncated_lines)
