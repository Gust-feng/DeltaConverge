# Formula 与 Fiber（/formulas/{uri}/tools 与 /formulas/{uri}/fibers）

本页包含 Formula 概念、如何获取工具、如何发起 Fiber 执行的调用契约以及示例客户端实现。

1. 概念
- Formula：平台提供的可复用工具集合（例如 `moonshot/web-search:latest`），包含工具声明与实现。通过 `tools` 列表可将 Formula 的 function 引入到 Chat 请求中。

2. 获取工具
- `GET /formulas/{formula_uri}/tools`：返回 formula 内声明的工具列表，结构为 `[{"type":"function","function":{...}}]`。

3. 发起执行（Fiber）
- 若模型返回的 `tool_calls` 中 `function.name` 对应某 Formula 的工具，请将该 `function` 对象作为 body 发起 `POST /formulas/{formula_uri}/fibers`。
- `arguments` 是序列化的 JSON 字符串，可以直接传入 body，无需额外转义。

示例（curl）:

```bash
curl -X POST "${MOONSHOT_BASE_URL}/formulas/moonshot/web-search:latest/fibers" \
  -H "Authorization: Bearer $MOONSHOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"web_search","arguments":"{\"query\": \"天蓝色 RGB\"}"}'
```

4. Fiber 返回说明
- 返回对象包含 `id, status, context, formula` 等字段。成功时结果可能在 `context.output` 或 `context.encrypted_output`。

5. Formula Chat Client（示例概览）
- 见 `api手册.md` 中的 `FormulaChatClient` 异步示例（已保留于原文）。建议将示例提取为 `examples/formula_client.py` 并做静态语法检查（如需我可以生成）。
