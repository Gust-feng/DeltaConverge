# API 端点参考 — Kimi / Moonshot

说明：本文件为快速查阅表格，列出常用端点、方法、用途、关键请求字段与响应要点，以及简短示例（curl）。认证：所有请求需在 Header 中包含 `Authorization: Bearer <MOONSHOT_API_KEY>`。

---

| Endpoint | Method | 作用 | 关键请求字段 / Body | 关键响应字段 | 备注 / 示例 |
|---|---:|---|---|---|---|
| `/v1/chat/completions` | POST | 发起对话，获取模型回复 或 触发 tool_calls | JSON body: `model` (string), `messages` (array of {role, content, name?}), `tools` (array, optional), `temperature`, `max_tokens`, `stream` (bool), `n` (int) | `choices[]` -> `message` (可能包含 `content` 或 `tool_calls`)，`choices[].finish_reason` (`stop` / `tool_calls`) | 注意 tool_calls 流程：当 `finish_reason=tool_calls` 时，读取 `message.tool_calls` 并按流程执行工具；示例：见下方 curl。 |
| `/v1/files` | POST | 上传文件并抽取（purpose=`file-extract`） | multipart/form-data: `file`，`purpose="file-extract"` | FileObject: `id`, `bytes`, `filename`, `status` | 限制：单文件 ≤100MB，单用户 ≤1000 文件。上传后调用 `/v1/files/{id}/content` 获取抽取文本。 |
| `/v1/files` | GET | 列出用户已上传文件 | 无 | 列表对象：`data[]` 每项为 FileObject | 可用于定期清理。 |
| `/v1/files/{file_id}` | GET | 获取文件元信息 | path param `file_id` | FileObject（含 `status`） | 检查 `status` 字段（`ok` / `error`）。 |
| `/v1/files/{file_id}/content` | GET | 获取抽取后的文本内容 | path param `file_id` | 返回 `.text`（抽取后的字符串） | 建议将抽取文本作为 `system` message 放入 chat 请求中。 |
| `/v1/files/{file_id}` | DELETE | 删除文件 | path param `file_id` | 删除结果 / 204 | 用于释放存储配额。 |
| `/formulas/{formula_uri}/tools` | GET | 查询 Formula 暴露的工具（tools 描述） | path param `formula_uri` (如 `moonshot/web-search:latest`) | JSON: `tools` 数组（每项为 type/function/parameters） | 用于把公式的 tools 追加到 chat 请求的 `tools` 列表中。|
| `/formulas/{formula_uri}/fibers` | POST | 执行 Formula（创建 Fiber） | JSON body: `name` (函数名), `arguments` (字符串化 JSON) | Fiber 对象：`id`, `status`, `context` (含 `output` 或 `encrypted_output`) | 若 `status=succeeded`，从 `context` 取结果；若返回 `encrypted_output`，按平台指引处理。 |

---

## 关键示例

Chat（触发工具调用）curl 示例：

```bash
curl -X POST "https://api.moonshot.cn/v1/chat/completions" \
  -H "Authorization: Bearer $MOONSHOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"kimi-k2-turbo-preview",
    "messages":[{"role":"system","content":"你是 Kimi。"},{"role":"user","content":"请联网搜索 Context Caching"}],
    "tools":[
      {"type":"function","function":{"name":"search","description":"网络搜索","parameters":{"type":"object","required":["query"],"properties":{"query":{"type":"string"}}}}}
    ]
  }'
```

文件上传（curl）示例：

```bash
curl -X POST "https://api.moonshot.cn/v1/files" \
  -H "Authorization: Bearer $MOONSHOT_API_KEY" \
  -F "file=@./xlnet.pdf" \
  -F "purpose=file-extract"
```

调用 Formula（fiber）示例（curl）：

```bash
curl -X POST "${MOONSHOT_BASE_URL}/formulas/moonshot/web-search:latest/fibers" \
  -H "Authorization: Bearer $MOONSHOT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"web_search","arguments":"{\"query\": \"天蓝色 RGB\"}"}'
```

---

## 使用说明要点（快速参考）
- 所有 chat 请求可带 `tools` 定义；若模型返回 `tool_calls`，需按文档流程在客户端执行工具并把结果以 `role=tool` 的消息回传。
- `function.arguments` 在模型返回中通常为字符串化的 JSON，请用 `json.loads` / 等价解析方法反序列化。
- Stream 模式下 `tool_calls` 可能分片返回，需按 `index` 合并 `arguments` 字段。
- 在多 formula 场景中，务必保证 `function.name` 在单次请求内唯一，或维护 `function.name -> formula_uri` 映射以便执行对应 fiber。

---

如果需要，我可以把上表再导出为更详细的“端点—参数—示例”分页（每个端点一个小节），或把这些端点以 Markdown 表格形式插入现有 `api手册.md` 的首部/末尾。