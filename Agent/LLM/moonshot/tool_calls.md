# Tools 与 tool_calls（核心交互）

本文件把 `api手册.md` 中有关 `tools` / `tool_calls` 的内容抽取成专题页，聚焦定义、交互约定、处理流程与示例伪代码。

1. 工具定义（示例）

```json
{
  "type":"function",
  "function":{
    "name":"search",
    "description":"通过搜索引擎检索互联网信息，返回标题/URL/摘要",
    "parameters":{
      "type":"object",
      "required":["query"],
      "properties":{
        "query":{"type":"string","description":"搜索关键词"}
      }
    }
  }
}
```

2. 交互要点（必须遵守）
- `tool_calls` 支持一次返回多个调用；客户端必须为每个 `tool_call` 返回对应的 `role="tool"` message，并且 `tool_call_id` 与模型返回的 `id` 一一对齐。
- `function.arguments` 是序列化的 JSON 字符串；客户端需反序列化后执行工具。
- 在流式（`stream`）场景中，`function.arguments` 可能被分片返回，需按 `index` 合并。

3. 处理流程（伪代码）

```python
# messages 初始包含 system+user
while True:
    resp = client.chat.completions.create(model=model, messages=messages, tools=tools)
    choice = resp.choices[0]
    if choice.finish_reason != 'tool_calls':
        print(choice.message.content)
        break
    messages.append(choice.message)  # 必须原封不动添加
    for call in choice.message.tool_calls:
        args = json.loads(call.function.arguments)
        result = run_tool(call.function.name, args)
        messages.append({
            'role':'tool',
            'tool_call_id': call.id,
            'name': call.function.name,
            'content': json.dumps(result)
        })
```

4. 并发与重试策略建议
- 对于相互独立的 `tool_calls`，建议并发执行以降低延迟，但仍需确保所有 `role=tool` messages 最终按任意顺序提交且 `tool_call_id` 对齐。
- 若工具执行可能失败：使用可配置的重试（指数回退），并在最终失败时回传失败描述（`{"error":"..."}`）给模型。

5. 流式（stream）组装要点
- 维护 per-index 的缓冲区来合并 `function.arguments` 的分片；在接收到包含 `id`、`name` 的首片后开始记录，后续 `arguments` 片段追加到该 buffer；完结后进行 JSON 反序列化与执行。

6. 调试提示
- 若遇到 `tool_call_id not found`：检查是否把 `assistant` message 原封不动追加到了 `messages`；检查 `tool_call_id` 字段拼写及类型一致性。
