from Agent.agents.prompts import DEFAULT_USER_PROMPT


def build_review_prompt(review_index_md: str, context_bundle_json: str, user_prompt: str) -> str:
    """构建发送给审查 Agent 的用户提示。
    
    始终使用内置的 DEFAULT_USER_PROMPT 作为基础提示词，忽略前端传入的 user_prompt。
    """
    return (
        f"{DEFAULT_USER_PROMPT}\n\n"
        f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
        f"上下文包（按规划抽取的片段）：\n```json\n{context_bundle_json}\n```"
    )


