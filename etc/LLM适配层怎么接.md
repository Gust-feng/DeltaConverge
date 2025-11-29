# LLM 适配层怎么接：厂商各显神通，系统只认一种格式

> 需求背景：Moonshot/Kimi、GLM、百炼甚至 Mock，都要塞进同一套审查链路；核心 Agent 不想了解“厂商癖好”，只消费自家的 `NormalizedMessage`/工具调用格式。

## 谁在干活
- `BaseLLMClient` (`Agent/core/llm/client.py`): 只定义一个 `stream_chat`（可选 `create_chat_completion`）。真正的 HTTP 细节、headers、超时都在各自子类里处理。
- 具体客户端：`MoonshotLLMClient`/`GLMLLMClient`/`BailianLLMClient`/`MockMoonshotClient`，统一输出 Moonshot/OpenAI 风格的流式片段（`choices[*].delta.*`），顺带把 usage、tool 调用增量塞进 chunk。
- `StreamProcessor` (`Agent/core/stream/stream_processor.py`): 把流式 chunk 组装成一条 **私有标准消息**，拼文本、合并多段 tool arguments，兜底 JSON 解析失败也会返回 `_raw`。
- `LLMAdapter` (`Agent/core/adapter/llm_adapter.py`): 默认走流式，直接把 `client.stream_chat` 喂给 `StreamProcessor.collect`，并补充 `provider`、`tool_schemas`、`raw`。
- `KimiAdapter`: 在上面加了“流式/非流式开关”，非流式时用 `_normalize_non_stream_response` 手动把 `choices[0].message` 转成同样的私有格式。
- 会话层：`ConversationState` 只接收规范化的 assistant/tool 消息，工具 runtime 不用关心是哪家模型给的调用。

## 私有统一格式长什么样
```text
NormalizedMessage = {
  type: "assistant",
  role: "assistant",                  # 兼容 delta 里的 role
  content: "最终文本" | None,          # 流式拼接后再去首尾空白
  tool_calls: [                       # 解析后的工具调用
    { id, name, index, arguments: Dict }
  ],
  finish_reason: "stop" | "tool_calls" | None,
  usage: {...} | None,                # 流式 usage 捕获不到时会从 raw.chunks 兜底
  tool_schemas: 原始 tools 参数,
  provider: "moonshot" | "glm" | ...,
  raw: {chunks: [...]} | 原始响应     # 调试留痕，不参与业务逻辑
}
```
- `StreamProcessor` 会把 `delta.content` 里的 text 数组拼起来；`delta.tool_calls[*].function.arguments` 会按 index 聚合多段字符串再尝试 `json.loads`。
- `_safe_parse_arguments`（非流式路径）同样会兜底，把无法解析的内容放进 `{"_raw": "...", "_error": "invalid_json"}`。

## 链路怎么跑
1. 服务层 `create_llm_client` 选厂商 → `KimiAdapter` 包装 → 给 planner/reviewer 复用同一接口。
2. Agent 往 `adapter.complete` 塞 `messages`/`tools`，拿回上面的 `NormalizedMessage`。
3. 如果携带 `tool_calls`，`CodeReviewAgent` 直接把标准化调用送进 `ToolRuntime.execute`；执行结果再回写 `ConversationState`，下一轮对话继续。
4. 任何阶段的流式增量都会通过 `observer` 往前端/UI 推，日志里也有 `provider` 维度可查。

## 如果要再接一个新厂商
- 首先实现一个 `BaseLLMClient` 子类，保证 `stream_chat` yield 的 chunk 至少包含 `choices[0].delta`、`finish_reason`、可选 `usage`；tool 调用请按 `delta.tool_calls[].function.arguments`（字符串）返回。
- 如果厂商非流式接口丰富，可以模仿 `KimiAdapter._normalize_non_stream_response` 路线；如果 chunk 结构完全不是 Moonshot 风格，就新建一个适配器子类，把厂商字段翻译成 `StreamProcessor` 能吃的 `{delta: {...}, finish_reason: ...}` 形态。
- 别忘了在 `Agent/ui/service.py`（和 demo GUI）里注册创建逻辑，不然外层永远拿不到你的 client。
- usage 字段名不统一没关系，`CodeReviewAgent._extract_usage` 会尝试从最终消息或原始 chunks 兜底，但最好让客户端直接把 tokens 写进 chunk 的 `usage`。

## 还欠的坑
- 目前假设所有厂商的流式都是“追加文本 + 完整 tool 调用 JSON 字符串”的模式；如果出现“先发 YAML、再补 JSON”的奇葩流，需要在适配层拆分/重组。
- 会话裁剪还比较粗糙，适配层已经把 `raw` 留好，后续可以按 provider 精细化统计 tokens、调优窗口。

## 要按字段决定“流不流”怎么搞？
- 模型前提：厂商 chunk 里得有可分的字段（例如 `delta.content`、`delta.reasoning_content`、`delta.tool_calls`）。如果只有一坨 content，无法拆分。
- 建议改造路径：
  1. **StreamProcessor 扩展**：把 chunk 中的额外字段（思考/分析/草稿等）按统一 key 抽出来，并在 `observer` 事件里带上 `{"fields": {"content": "...", "reasoning": "...", ...}}`，最终 `NormalizedMessage` 也可保留这些字段。
  2. **Adapter 增加白名单**：给 `LLMAdapter.complete`/`KimiAdapter.complete` 增加 `stream_fields` 或 `stream_policy={"stream": [...], "buffer": [...]}`，`observer` 只转发白名单字段，其他字段仅累积，等收尾一次性返回。
  3. **客户端层翻译**：若厂商字段命名不一（如有的叫 `delta.thoughts`），在对应的 client/adapter 子类把它映射成内部统一 key（如 `reasoning`），再交给 StreamProcessor。
- 这样应用层就能配置：比如“思考字段流式推送，正式 content 等到结束”，而适配层保证不同厂商都被翻译成统一的字段集合。
