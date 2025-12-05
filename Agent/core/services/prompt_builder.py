def build_review_prompt(review_index_md: str, context_bundle_json: str, user_prompt: str) -> str:
    return (
        f"{user_prompt}\n\n"
        f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
        f"上下文包（按规划抽取的片段）：\n```json\n{context_bundle_json}\n```"
    )

