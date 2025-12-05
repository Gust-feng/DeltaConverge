"""意图/业务摘要 Agent：根据项目概览生成简短的 Markdown 摘要。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.state.conversation import ConversationState
from Agent.agents.prompts import SYSTEM_PROMPT_INTENT


class IntentAgent:
    """轻量意图分析 Agent，输出短 Markdown 摘要。"""

    def __init__(
        self,
        adapter: LLMAdapter,
        state: ConversationState | None = None,
    ) -> None:
        self.adapter = adapter
        self.state = state or ConversationState()
        self.last_usage: Optional[Dict[str, Any]] = None

    async def run(
        self,
        intent_input: Dict[str, Any],
        *,
        stream: bool = True,
        observer=None,
    ) -> str:
        """生成意图摘要 Markdown。

        Args:
            intent_input: 预先收集的项目概览数据（文件列表/README 摘要/提交概览等）。
            stream: 是否流式。
            observer: 可选流式观察者。
        """
        if not self.state.messages:
            self.state.add_system_message(SYSTEM_PROMPT_INTENT)

        # 控制输入体积，转为紧凑 JSON 供模型参考
        payload_preview = json.dumps(intent_input, ensure_ascii=False, indent=2)
        user_content = (
            "下面是项目的概览信息，请根据系统提示的要求，生成贴合业务意图的Markdown格式概要。\n\n"
            f"project_overview:\n```json\n{payload_preview}\n```"
        )
        self.state.add_user_message(user_content)

        assistant_msg = await self.adapter.complete(
            self.state.messages,
            stream=stream,
            observer=observer,
            temperature=0.7,
            top_p=0.95,
        )
        self.last_usage = assistant_msg.get("usage")
        content_text = assistant_msg.get("content", "") or ""
        # 不在意工具调用，直接返回内容
        self.state.add_assistant_message(content_text, [], assistant_msg.get("reasoning"))
        return content_text


__all__ = ["IntentAgent"]
