from Agent.agents.prompts import USER_MESSAGE_TEMPLATE


def build_review_prompt(
    review_index_md: str,
    context_bundle_json: str,
    intent_md: str,
) -> str:
    """构建审查阶段的用户消息（仅包含数据，不包含指令）。
    
    系统提示词 SYSTEM_PROMPT_REVIEWER 已在 CodeReviewAgent 中设置，
    这里只需要构建用户消息，包含项目意图、审查索引和上下文包。
    
    Args:
        review_index_md: 审查索引（Markdown 格式）
        context_bundle_json: 上下文包（JSON 格式）
        intent_md: 项目意图摘要（来自 IntentAgent）
    
    Returns:
        用户消息内容
    """
    return USER_MESSAGE_TEMPLATE.format(
        intent_md=intent_md,
        review_index_md=review_index_md,
        context_bundle_json=context_bundle_json,
    )

