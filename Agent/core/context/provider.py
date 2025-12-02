"""上下文提供者：选择用于审查的文件或片段。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

class ContextProvider:
    """加载上下文片段（如 diff 中挑选的文件）。"""

    def __init__(self, max_bytes: int = 16_000) -> None:
        self.max_bytes = max_bytes

    def load_context(self, files: List[str]) -> Dict[str, str]:
        """返回 file_path -> 片段 的映射，受 max_bytes 限制。"""

        context: Dict[str, str] = {}
        budget = self.max_bytes
        for file_path in files:
            path = Path(file_path)
            if not path.exists() or budget <= 0:
                break # 预算不足时直接退出，避免无效循环
            
            try:
                # 直接读取，不再使用 fallback 包装，简化调用栈
                # 假设文件编码为 utf-8，读取失败则直接抛出或忽略
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                # 简单忽略读取失败的文件，不记录冗余 fallback 日志
                continue

            snippet = text[:budget] # 利用切片自动处理长度越界
            context[file_path] = snippet
            budget -= len(snippet)
            
        return context
