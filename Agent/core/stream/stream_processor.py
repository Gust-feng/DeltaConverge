"""处理 Moonshot 风格响应的流式增量。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, TypedDict, Union


class NormalizedToolCall(TypedDict):
    id: str
    name: str
    index: int
    arguments: Dict[str, Any]


class NormalizedMessage(TypedDict, total=False):
    type: str
    role: str
    content: str | None
    content_json: Dict[str, Any] | List[Any] | None
    reasoning: str | None
    tool_calls: List[NormalizedToolCall]
    finish_reason: str | None
    raw: Dict[str, Any]
    provider: str
    tool_schemas: List[Union[Dict[str, Any], Any]] | None
    usage: Dict[str, Any] | None


class StreamProcessor:
    """聚合流式增量，生成规范化的助手消息。"""

    _REASONING_KEYS = ("reasoning", "reasoning_content", "reasoning_details", "analysis", "thoughts")
    _MAX_JSON_NESTING = 50
    
    @staticmethod
    def _safe_json_loads(s: str, max_nesting: int = 50) -> Any:
        """安全加载JSON并校验最大嵌套深度。"""
        obj = json.loads(s)
        def _depth(x: Any, d: int = 0) -> int:
            if isinstance(x, dict):
                if not x:
                    return d + 1
                return max(_depth(v, d + 1) for v in x.values())
            if isinstance(x, list):
                if not x:
                    return d + 1
                return max(_depth(v, d + 1) for v in x)
            return d
        if _depth(obj) > max_nesting:
            raise json.JSONDecodeError("JSON nesting too deep", s, 0)
        return obj
    
    @staticmethod
    def _extract_text(delta_val: Any) -> str:
        """规范化提取文本，无论是 list[dict] 还是直接 str。"""
        if isinstance(delta_val, list):
            return "".join(
                piece.get("text", "")
                for piece in delta_val
                if isinstance(piece, dict) and piece.get("type") == "text"
            )
        return delta_val if isinstance(delta_val, str) else ""
    
    @staticmethod
    def _strip_think_tags(content: str, reasoning_parts: list) -> tuple[str, list]:
        """清理 content 中可能混入的 <think>...</think> 标签。
        
        MiniMax 等模型在未启用 reasoning_split 时会将思考过程以 <think> 标签
        包裹混入 content 字段。此方法提取并移除这些标签，防止输出污染。
        
        Returns:
            (cleaned_content, updated_reasoning_parts)
        """
        import re
        # 匹配 <think>...</think> 标签（支持换行）
        pattern = r'<think>(.*?)</think>'
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            # 提取的思考内容加入 reasoning
            for match in matches:
                if match.strip():
                    reasoning_parts.append(match.strip())
            # 从 content 中移除 <think> 标签
            content = re.sub(pattern, '', content, flags=re.DOTALL).strip()
        return content, reasoning_parts

    async def collect(
        self,
        stream: AsyncIterator[Dict[str, Any]],
        observer: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> NormalizedMessage:
        """消费流式迭代器并返回一条规范化消息。"""
        # 初始化收集状态
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        role = "assistant"
        finish_reason: str | None = None
        tool_call_buffer: Dict[int, Dict[str, Any]] = {}
        raw_chunks: List[Dict[str, Any]] = []
        last_usage: Dict[str, Any] | None = None

        # 处理每个流式片段
        async for chunk in stream:
            raw_chunks.append(chunk)
            delta = chunk.get("delta", {})
            
            # 更新基本信息
            if chunk.get("finish_reason") and not finish_reason:
                finish_reason = chunk["finish_reason"]
            if delta.get("role") and role == "assistant":  # 只有默认值时才更新
                role = delta["role"]
            if chunk.get("usage"):
                last_usage = chunk["usage"]

            # 提取内容
            content_text = self._extract_text(delta.get("content"))
            if content_text:
                content_parts.append(content_text)

            # 提取推理内容
            # 优先使用 client 已处理好的顶层 reasoning_content（避免重复解析 MiniMax 列表等格式）
            reasoning_text = ""
            if chunk.get("reasoning_content"):
                reasoning_text = chunk["reasoning_content"]
            else:
                # Fallback: 从 delta 中搜索可能的推理字段
                for key in self._REASONING_KEYS:
                    if key in delta:
                        reasoning_text = self._extract_text(delta[key])
                        break
            if reasoning_text:
                reasoning_parts.append(reasoning_text)

            # 处理工具调用
            calls_raw = delta.get("tool_calls", [])
            tool_call_entries = [calls_raw] if isinstance(calls_raw, dict) else calls_raw if isinstance(calls_raw, list) else []
            
            for call in tool_call_entries:
                if not isinstance(call, dict):
                    continue
                index = call.get("index")
                if index is None:
                    # Some providers might omit index if there's only one call, default to 0
                    index = 0
                
                # 获取或创建工具调用缓冲区
                buffer = tool_call_buffer.setdefault(index, {
                    "id": call.get("id"),
                    "name": None,
                    "arguments_chunks": [],
                })
                
                # 更新缓冲区信息
                if call.get("id"):
                    buffer["id"] = call["id"]
                fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
                if fn.get("name"):
                    buffer["name"] = fn["name"]
                if fn.get("arguments"):
                    buffer["arguments_chunks"].append(fn["arguments"])

            # 通知观察者
            if observer:
                observer({
                    "type": "delta",
                    "content_delta": content_text,
                    "reasoning_delta": reasoning_text,
                    "tool_calls_delta": tool_call_entries,
                    "chunk": chunk,
                    "usage": chunk.get("usage"),
                })

        # 处理工具调用结果
        tool_calls: List[NormalizedToolCall] = []
        for index in sorted(tool_call_buffer.keys()):
            buf = tool_call_buffer[index]
            args_text = "".join(buf["arguments_chunks"])
            
            # 解析工具调用参数
            try:
                arguments = self._safe_json_loads(args_text) if args_text else {}
            except json.JSONDecodeError:
                arguments = {"_raw": args_text, "_error": "invalid_json"}
            
            # 添加规范化的工具调用
            tool_calls.append({
                "id": buf.get("id") or f"call_{index}",
                "name": buf.get("name") or "unknown_tool",
                "index": index,
                "arguments": arguments,
            })

        # 构建最终消息
        content = "".join(content_parts).strip()
        reasoning = "".join(reasoning_parts).strip()
        
        # 清理可能混入 content 的 <think> 标签（MiniMax 兼容）
        if content and '<think>' in content:
            content, extra_reasoning = self._strip_think_tags(content, [])
            if extra_reasoning:
                reasoning = (reasoning + "\n\n" + "\n\n".join(extra_reasoning)).strip() if reasoning else "\n\n".join(extra_reasoning)
        
        # 尝试解析 JSON 内容
        content_json: Dict[str, Any] | List[Any] | None = None
        if content and len(content) < 1024 * 1024:  # 1MB 限制
            try:
                parsed = self._safe_json_loads(content, max_nesting=self._MAX_JSON_NESTING)
                if isinstance(parsed, (dict, list)):
                    content_json = parsed
            except json.JSONDecodeError:
                content_json = None
        
        return {
            "type": "assistant",
            "role": role,
            "content": content or None,
            "content_json": content_json,
            "reasoning": reasoning or None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw": {"chunks": raw_chunks, "source": "stream"},
            "usage": last_usage,
        }
