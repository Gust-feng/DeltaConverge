from Agent.agents.prompts import DEFAULT_USER_PROMPT


def build_review_prompt(review_index_md: str, context_bundle_json: str, user_prompt: str, intent_md: str | None = None) -> str:
    """构建发送给审查 Agent 的用户提示。

    始终使用内置的 DEFAULT_USER_PROMPT 作为基础提示词；
    如果前端额外提供了用户指令且不是占位符，则追加到提示尾部。
    """

    base_prompt = DEFAULT_USER_PROMPT

    # 附加可信的用户额外要求，但过滤默认占位内容
    if user_prompt:
        extra = user_prompt.strip()
        if extra and extra != "开始代码审查":
            base_prompt = f"{base_prompt}\n\n用户额外要求：{extra}"

    intent_section = ""
    if intent_md and intent_md.strip():
        intent_section = f"项目意图摘要：\n{intent_md.strip()}\n\n"

    return (
        f"{base_prompt}\n\n"
        f"{intent_section}"
        f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
        f"上下文包（按规划抽取的片段）：\n```json\n{context_bundle_json}\n```"
    )


