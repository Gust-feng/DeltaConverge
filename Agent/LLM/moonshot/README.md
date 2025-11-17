# Kimi / Moonshot API 手册（拆分版）

说明：本仓库下的 API 手册已拆分为若干子文档，便于 LLM 或工程师按主题查阅与使用。

快速入口：

- `tool_calls.md`：详述 `tools` / `tool_calls` 的定义、客户端执行流程、并发与流式处理的伪代码示例。
- `files.md`：文件上传、抽取、问答工作流、限制与最佳实践。
- `formulas.md`：Formula 概念、`/formulas/{uri}/tools` 与 `/formulas/{uri}/fibers` 的调用契约，包含 Formula Chat Client 示例。
- `api端点参考.md`：端点快速参考表格与 curl 示例（已存在）。

使用建议（给 LLM）：

- 将 `README.md` 作为索引，并以 `components` 中的 Schema（ToolCall、Fiber、FileObject）生成 OpenAPI 时引用；
- 保持功能完整性：示例代码可以简洁但不得删减功能描述或关键字段（例如 `tool_call_id` 对齐规则）；
- 若需要可选输出：请求生成完整 OpenAPI v3（YAML）与 `examples/` 目录下的可运行脚本。

请从下列文件开始查阅：

- `tool_calls.md`
- `files.md`
- `formulas.md`
- `api端点参考.md`
