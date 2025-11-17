# 一个简单调用工具的示例

> 注：已拆分为主题子文档。请优先查阅仓库根目录下的 `README.md`（`Agent/LLM/moonshot/README.md`），然后根据主题打开：

- `tool_calls.md`（工具调用、伪代码、流式与并发处理）
- `files.md`（文件上传、抽取与文件问答）
- `formulas.md`（Formula 与 Fiber 的调用契约与示例）
- `api端点参考.md`（端点速查表）

下面为原文剩余内容（保留以便查阅）：

其中在 tools 字段，我们可以增加一组可选的工具列表。

每个工具列表必须包括一个类型，在 function 结构体中我们需要包括 name（它的需要遵守这样的正则表达式作为规范: ^[a-zA-Z_][a-zA-Z0-9-_]63$），这个名字如果是一个容易理解的英文可能会更加被模型所接受。以及一段 description 或者 enum，其中 description 部分介绍它能做什么功能，方便模型来判断和选择。 function 结构体中必须要有个 parameters 字段，parameters 的 root 必须是一个 object，内容是一个 json schema 的子集（之后我们会给出具体文档介绍相关技术细节）。 tools 的 function 个数目前不得超过 128 个。
# Kimi API（Moonshot）使用手册
# Kimi / Moonshot API 参考（以 API 功能为主）

本文档为面向开发者的 API 参考，重点说明关键端点、请求字段、返回格式与示例代码，便于快速集成 Kimi（Moonshot）对话、工具调用与 Formula 执行能力。

**版本与基础**
- Base URL: `https://api.moonshot.cn/v1`
- 鉴权: HTTP Header `Authorization: Bearer <MOONSHOT_API_KEY>`。
- 推荐 SDK: 官方兼容 OpenAI 的 `openai` 包（示例使用 `from openai import OpenAI`）。

---

## 1. 常用约定
- `messages`：数组，支持 `system` / `user` / `assistant` / `tool` 四类 role。
- `tools`：数组，可在请求中声明可用工具（JSON Schema 描述）。模型会基于上下文选择调用工具并返回 `tool_calls`。
- Token：`tools` 与 `messages` 均计入 token 限额，请避免超长上下文。

---

## 2. Chat：/v1/chat/completions

用途：发送对话上下文，获取模型回复、或触发工具调用（tool_calls）。

请求要点（JSON body）：
- `model` (string)：例如 `kimi-k2-turbo-preview`。
- `messages` (array)：对话上下文（按时间顺序）。
- `tools` (array，可选)：工具定义数组（参见 Tools 部分）。
- `temperature`, `max_tokens`, `stream` 等标准参数。

典型 Python 示例（同步 SDK）：

```python
from openai import OpenAI
client = OpenAI(api_key="$MOONSHOT_API_KEY", base_url="https://api.moonshot.cn/v1")
resp = client.chat.completions.create(
        model="kimi-k2-turbo-preview",
        messages=[
                {"role":"system","content":"你是 Kimi，专业中英文助手。"},
                {"role":"user","content":"请解释什么是 Context Caching。"}
        ],
)
print(resp.choices[0].message)
```

响应要点：
- `choices[0].finish_reason`：若为 `tool_calls`，表示模型请求执行工具；若为 `stop`，表示直接生成最终回复。
- `choices[0].message.tool_calls`（存在时）：每个元素包含 `id`、`type`（function）、`function.name` 与 `function.arguments`（序列化 JSON 字符串）。

---

## 3. Tools 与 tool_calls（核心交互）

目的：允许模型在对话中选择外部工具执行动作（例如搜索、抓取、执行代码），并通过客户端执行后将结果回传模型完成最终回复。

工具定义示例（加入 `tools` 参数）：

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

处理流程（实现要点）：
1. 向 chat/completions 提交 `messages` + `tools`。
2. 若返回 `finish_reason == "tool_calls"`，读取并追加模型返回的 assistant message（原封不动）到 `messages` 列表中。
3. 对 `choice.message.tool_calls` 中的每个 tool_call：
     - 反序列化 `function.arguments`（JSON string）。
     - 在客户端执行对应工具实现（可并发）。
     - 将工具执行结果以 `role="tool"` 的 message 添加到 `messages`，并包含 `tool_call_id` 與 `name`（必须与 tool_calls 中的 id 对齐）。
4. 再次调用 chat 接口，模型将基于工具结果继续推理并返回最终回复（finish_reason=stop）。

伪代码：

```python
# messages 初始包含 system+user
while True:
        resp = client.chat.completions.create(model=model, messages=messages, tools=tools)
        choice = resp.choices[0]
        if choice.finish_reason != 'tool_calls':
                print(choice.message.content)
                break
        # append assistant message (contains tool_calls)
        messages.append(choice.message)
        for call in choice.message.tool_calls:
                args = json.loads(call.function.arguments)
                result = run_tool(call.function.name, args)
                messages.append({
                        'role':'tool', 'tool_call_id':call.id, 'name':call.function.name, 'content':json.dumps(result)
                })
```

注意：必须为每个 `tool_call` 返回对应的 `role=tool` message，且 `tool_call_id` 对齐，否则会报错（例如 `tool_call_id not found`）。

---

## 4. 文件接口（/v1/files）

用途：上传文件并抽取文本（OCR 支持图片/PDF），用于基于文件的问答。

限制：单文件 ≤ 100MB，单用户最多 1000 个文件，总量 ≤ 10GB。

主要端点：
- `POST /v1/files`：上传（`purpose="file-extract"`）。
- `GET /v1/files`：列出文件。
- `DELETE /v1/files/{file_id}`：删除文件。
- `GET /v1/files/{file_id}/content`：获取抽取后的文本（将其作为 `system` message 提交给模型）。

上传与问答示例：

```python
from pathlib import Path
file_obj = client.files.create(file=Path('doc.pdf'), purpose='file-extract')
text = client.files.content(file_id=file_obj.id).text
messages = [{"role":"system","content":text}, {"role":"user","content":"请概述该文件"}]
resp = client.chat.completions.create(model=model, messages=messages)
print(resp.choices[0].message.content)
```

建议：将抽取后的文本（而非 file_id）放入 `system` message；若多文件并入上下文，每个文件单独一条 `system` message。

---

## 5. Formula 与 Fiber（/formulas/{uri}/tools 与 /formulas/{uri}/fibers）

概念：Formula 是 Moonshot 提供的工具集合（例如 `moonshot/web-search:latest`）。通过 Formula 可获得工具定义并执行（生成 Fiber）。

流程：
1. 获取工具列表：`GET /formulas/{formula_uri}/tools`。
2. 模型返回 `tool_calls` 且 `function.name` 对应某 formula 时，向 `/formulas/{formula_uri}/fibers` 发起执行（body 可直接使用模型返回的 `function` 对象）。
3. Fiber 返回 `status`（例如 `succeeded`），结果可能在 `context.output` 或 `context.encrypted_output`。将其作为 `role=tool` message 返回给模型继续推理。

示例（curl）：

```bash
curl -X POST "${MOONSHOT_BASE_URL}/formulas/moonshot/web-search:latest/fibers" \
    -H "Authorization: Bearer $MOONSHOT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"web_search", "arguments":"{\\"query\\": \\\"天蓝色 RGB\\\"}"}'
```

---

## 6. 流式（stream）与并发注意点
- Stream 模式：tool_calls 可能分片出现，使用 `delta.tool_calls` 并按 `index` 合并 `function.arguments`。
- 并发：当模型返回多个无依赖的 tool_calls 时，建议并行执行以降低延迟，但仍需保证最终按每个 tool_call 返回对应的 role=tool 消息。

---

## 7. 错误码与排错要点
- `tool_call_id not found`：常见原因是未把模型返回的 assistant message 添加到 `messages` 中，或 `tool_call_id` 对齐错误。解决：原封不动 append assistant message，然后按 tool_calls 添加 role=tool 消息并校验 id。
- Token 超限：裁剪历史或将早期内容摘要后再加入 `system`。
- Fiber 执行失败：检查 Fiber 返回的 `status` 与 `context.error`。

---

## 8. 快速示例（curl & Python）

Chat（curl）：

```bash
curl -X POST "https://api.moonshot.cn/v1/chat/completions" \
    -H "Authorization: Bearer $MOONSHOT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"model":"kimi-k2-turbo-preview","messages":[{"role":"user","content":"什么是 Context Caching？"}] }'
```

工具调用处理（伪代码见第 3 节）。

---

## 9. 后续工作建议（可选）
- 将每个端点整理为表格：方法、路径、参数、响应字段、示例。
- 提取关键示例为可运行脚本放入 `Agent/LLM/moonshot/examples/` 并做语法检查。

请选择要继续的下一步：
1) 生成端点参考表格（Markdown 表格）；
2) 创建 `examples/` 并把示例转换为可运行脚本（我会校验语法）；
3) 继续在当前文件补充更详细示例。

---

## 附加：完整功能清单与行为说明（确保不遗漏）

下面列出并说明所有与 API 功能相关的重要特性和行为，便于在集成时不遗漏任何能力。

1) Partial Mode / Prefill
- 作用：在最后一个 `assistant` 消息中设置 `"partial": true`，预先填充模型回复的一部分，以控制输出格式或语气（例如开始一个 JSON 对象或角色前缀）。
- 注意：Partial Mode 与 `response_format=json_object` 可能冲突；若使用 leading_text（前缀），API 返回可能只包含后续内容，客户端需拼接完整回复。

示例：JSON prefill

```json
{"role":"assistant","content":"{\"name\": ","partial":true}
```

2) Json Mode
- 通过 Partial Mode 或明确的输出约束，要求模型输出严格对齐的 JSON 格式，适用于机器可解析的场景。
- 建议：提供 JSON Schema 或示例输出，降低解析失败风险。

3) 角色与 name 字段
- 在 `assistant` 消息中可使用 `name` 字段（例如 `{"role":"assistant","name":"凯尔希","content":"","partial":true}`）来帮助模型保持角色一致性。该字段被视为输出前缀的一部分。

4) 多候选（n）与并发回复
- 若请求参数中设置 `n>1`，模型会尝试生成多条回复（或多组 tool_calls），客户端需为每个候选维护独立的消息聚合。流式模式下需分别组装每个 index 的消息。

5) 流式（stream）tool_calls 详细组装
- 在 stream 模式下，`delta` 片段会逐步包含 `content` 与 `tool_calls`，其中 `tool_calls` 的 `function.arguments` 可能分片返回，需要按 `index` 合并。
- 实现要点：维护 per-index 字符串缓冲区，遇到 `tool_call.id`、`function.name` 等元数据时记录，遇到 `function.arguments` 片段时追加，直到该 tool_call 的 arguments 完整。

6) tool_calls 与 function_call 的区别
- `tool_calls` 是更通用的工具调用机制，支持一次返回多个工具调用（并行场景），并在消息流中用于描述模型希望外部执行的动作。OpenAI 旧的 `function_call` 与之概念相近但已被标记为废弃，推荐使用 `tool_calls`。

7) 官方工具（Formula）汇总
- Moonshot 提供一系列官方 Formula（可在 platform 或 `/formulas/{uri}/tools` 查询）：
    - `convert`：单位换算
    - `web-search`：联网搜索
    - `rethink`：智能整理想法
    - `random-choice`：随机选择
    - `mew`：趣味猫叫工具
    - `memory`：保存/检索记忆
    - `excel`：Excel/CSV 分析
    - `date`：日期时间处理
    - `base64`：base64 编解码
    - `fetch`：URL 内容提取并 Markdown 化
    - `quickjs`：QuickJS 沙箱执行 JavaScript
    - `code_runner`：Python 代码执行
- 使用建议：将所需 formula 加入 tools 列表时，注意 function.name 在单次请求内唯一；多 formula 场景下维护 function.name -> formula_uri 的映射表以便调用对应 fiber。

8) Formula Fiber 执行细节
- 调用 `/formulas/{uri}/fibers` 发起执行后返回 Fiber 对象，检查 `status` 字段（succeeded / error）。成功时结果位于 `context.output` 或 `context.encrypted_output`。
- 若返回 `encrypted_output`，该内容通常为平台加密格式，可直接作为 tool message 内容回传模型或按平台指引解密。

9) 文件管理端点补充
- 列表：`GET /v1/files`（或 `client.files.list()`），返回 file 元信息列表。
- 删除：`DELETE /v1/files/{file_id}`（或 `client.files.delete(file_id=...)`）。
- 获取元信息：`GET /v1/files/{file_id}`（或 `client.files.retrieve(file_id=...)`），检查 `status` 字段（`ok` / `error`）。
- 获取抽取内容：`GET /v1/files/{file_id}/content`（或 `client.files.content(file_id=...).text`）。

10) 常见返回与监控
- Chat 接口返回中常见字段：`choices[].message`（message 包含 role/tool_calls/content）、`choices[].finish_reason`。
- Formula Fiber 返回中常见字段：`id, status, context, formula, created_at`。

11) 安全与合规
- 在将外部工具或 formula 纳入时，请注意对返回内容进行安全过滤，避免直接将不可信内容用于执行（例如 shell、eval 等）。

---

如果你确认需要保持“功能完整、示例简洁”的策略，我可以继续：
- 选项 A：把上面每个端点/特性整理成一页式 Markdown 表格（便于快速查阅）；
- 选项 B：在 `Agent/LLM/moonshot/examples/` 下生成三个示例脚本（chat_tool_calls.py、file_qa.py、formula_client.py），我会做语法检查并提交；
- 选项 C：把文档以 README + 子文件（tool_calls.md, files.md, formulas.md）拆分并建立目录索引。

请选择 A / B / C 或告诉我你更具体的偏好。

			"description": """ 
				通过搜索引擎搜索互联网上的内容。
 
				当你的知识无法回答用户提出的问题，或用户请求你进行联网搜索时，调用此工具。请从与用户的对话中提取用户想要搜索的内容作为 query 参数的值。
				搜索结果包含网站的标题、网站的地址（URL）以及网站简介。
			""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
			"parameters": { # 使用 parameters 字段来定义函数接收的参数
				"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
				"required": ["query"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
				"properties": { # properties 中是具体的参数定义，你可以定义多个参数
					"query": { # 在这里，key 是参数名称，value 是参数的具体定义
						"type": "string", # 使用 type 定义参数类型
						"description": """
							用户搜索的内容，请从用户的提问或聊天上下文中提取。
						""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
					}
				}
			}
		}
	},
	{
		"type": "function", # 约定的字段 type，目前支持 function 作为值
		"function": { # 当 type 为 function 时，使用 function 字段定义具体的函数内容
			"name": "crawl", # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
			"description": """
				根据网站地址（URL）获取网页内容。
			""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
			"parameters": { # 使用 parameters 字段来定义函数接收的参数
				"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
				"required": ["url"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
				"properties": { # properties 中是具体的参数定义，你可以定义多个参数
					"url": { # 在这里，key 是参数名称，value 是参数的具体定义
						"type": "string", # 使用 type 定义参数类型
						"description": """
							需要获取内容的网站地址（URL），通常情况下从搜索结果中可以获取网站的地址。
						""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
					}
				}
			}
		}
	}
]

在使用 JSON Schema 定义工具时，我们使用以下固定的格式来定义一个工具：

{
	"type": "function",
	"function": {
		"name": "NAME",
		"description": "DESCRIPTION",
		"parameters": {
			"type": "object",
			"properties": {
				
			}
		}
	}
}

其中，name、description、parameters.properties 由工具提供方定义，其中 description 描述了工具的具体作用、以及在什么场合需要使用工具，parameters 描述了成功调用工具所需要的具体参数，包括参数类型、参数介绍等；最终，Kimi 大模型会根据 JSON Schema 的定义，生成一个满足定义要求的 JSON Object 作为工具调用的参数（arguments）。

注册工具
让我们试试把 search 这个工具提交给 Kimi 大模型，看看 Kimi 大模型能否正确调用工具：

from openai import OpenAI
 
 
client = OpenAI(
    api_key="MOONSHOT_API_KEY", # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
    base_url="https://api.moonshot.cn/v1",
)
 
tools = [
	{
		"type": "function", # 约定的字段 type，目前支持 function 作为值
		"function": { # 当 type 为 function 时，使用 function 字段定义具体的函数内容
			"name": "search", # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
			"description": """ 
				通过搜索引擎搜索互联网上的内容。
 
				当你的知识无法回答用户提出的问题，或用户请求你进行联网搜索时，调用此工具。请从与用户的对话中提取用户想要搜索的内容作为 query 参数的值。
				搜索结果包含网站的标题、网站的地址（URL）以及网站简介。
			""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
			"parameters": { # 使用 parameters 字段来定义函数接收的参数
				"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
				"required": ["query"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
				"properties": { # properties 中是具体的参数定义，你可以定义多个参数
					"query": { # 在这里，key 是参数名称，value 是参数的具体定义
						"type": "string", # 使用 type 定义参数类型
						"description": """
							用户搜索的内容，请从用户的提问或聊天上下文中提取。
						""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
					}
				}
			}
		}
	},
	# {
	# 	"type": "function", # 约定的字段 type，目前支持 function 作为值
	# 	"function": { # 当 type 为 function 时，使用 function 字段定义具体的函数内容
	# 		"name": "crawl", # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
	# 		"description": """
	# 			根据网站地址（URL）获取网页内容。
	# 		""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
	# 		"parameters": { # 使用 parameters 字段来定义函数接收的参数
	# 			"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
	# 			"required": ["url"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
	# 			"properties": { # properties 中是具体的参数定义，你可以定义多个参数
	# 				"url": { # 在这里，key 是参数名称，value 是参数的具体定义
	# 					"type": "string", # 使用 type 定义参数类型
	# 					"description": """
	# 						需要获取内容的网站地址（URL），通常情况下从搜索结果中可以获取网站的地址。
	# 					""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
	# 				}
	# 			}
	# 		}
	# 	}
	# }
]
 
completion = client.chat.completions.create(
    model="kimi-k2-turbo-preview",
    messages=[
        {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。"},
        {"role": "user", "content": "请联网搜索 Context Caching，并告诉我它是什么。"} # 在提问中要求 Kimi 大模型联网搜索
    ],
    temperature=0.6,
    tools=tools, # <-- 我们通过 tools 参数，将定义好的 tools 提交给 Kimi 大模型
)
 
print(completion.choices[0].model_dump_json(indent=4))

当上述代码运行成功时，我们获得 Kimi 大模型的返回内容：

{
    "finish_reason": "tool_calls",
    "message": {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": "search:0",
                "function": {
                    "arguments": "{\n    \"query\": \"Context Caching\"\n}",
                    "name": "search"
                },
                "type": "function",
            }
        ]
    }
}

注意看，在这次的回复中，finish_reason 的值为 tool_calls，这意味着本次请求返回的并不是 Kimi 大模型的回复，而是 Kimi 大模型选择执行工具。你可以通过 finish_reason 的值来判断当前 Kimi 大模型的回复是否是一次工具调用 tool_calls。

在 meessage 部分，content 字段是空值，这是因为当前正在执行 tool_calls，模型并没有生成面向用户的回复；同时新增了 tool_calls 字段，tool_calls 字段是一个列表，其中包含了本次需要调用的所有工具调用信息，这同时也表明了 tool_calls 的另一个特性，即：模型可以一次性选择多个工具进行调用，可以是多个不同的工具，也可以是相同工具使用不同参数进行调用。tool_calls 中的每个元素都代表了一次工具调用，Kimi 大模型会为每次工具调用生成一个唯一的 id，通过 function.name 字段表明当前执行的工具函数名称，并把执行的参数放置在 function.arguments 中，arguments 参数是一个合法的被序列化的 JSON Obejct（额外的，type 参数在目前是固定值 function）。

接下来，我们应该使用 Kimi 大模型生成的工具调用参数去执行具体的工具。

执行工具
Kimi 大模型并不会帮我们执行工具，需要由我们在接收到 Kimi 大模型生成的参数后自行执行参数，在讲述如何执行工具之前，让我们先解答之前提到的问题：

为什么 Kimi 大模型自己不能执行工具，还要我们根据 Kimi 大模型生成的工具参数“帮” Kimi 大模型执行工具？既然是我们在执行工具调用，还要 Kimi 大模型干什么？

让我们设想一下我们使用 Kimi 大模型的应用场景： 我们向用户提供一个基于 Kimi 大模型的智能机器人，在这个场景有三个角色：用户、机器人、Kimi 大模型。用户向机器人提问，机器人调用 Kimi 大模型 API，并将 API 的结果返回给用户。当使用 tool_calls 时，用户向机器人提问，机器人带着 tools 调用 Kimi API，Kimi 大模型返回 tool_calls 参数，机器人执行完 tool_calls，将结果再次提交给 Kimi API，Kimi 大模型生成返回给用户的消息（finish_reason=stop），此时机器人才会把消息返回给用户。 在这个过程中，tool_calls 的全过程对用户而言都是透明的、隐式的。

回到上述问题，作为用户的我们其实并没有在执行工具调用，也不会直接“看到”工具调用，而是给我们提供服务的机器人在完成工具调用，并将最终 Kimi 大模型生成的回复内容呈现给我们。

让我们以“机器人”的视角来讲解如何执行 Kimi 大模型返回的 tool_calls：

from typing import *
 
import json
 
from openai import OpenAI
 
 
client = OpenAI(
    api_key="MOONSHOT_API_KEY", # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
    base_url="https://api.moonshot.cn/v1",
)
 
tools = [
	{
		"type": "function", # 约定的字段 type，目前支持 function 作为值
		"function": { # 当 type 为 function 时，使用 function 字段定义具体的函数内容
			"name": "search", # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
			"description": """ 
				通过搜索引擎搜索互联网上的内容。
 
				当你的知识无法回答用户提出的问题，或用户请求你进行联网搜索时，调用此工具。请从与用户的对话中提取用户想要搜索的内容作为 query 参数的值。
				搜索结果包含网站的标题、网站的地址（URL）以及网站简介。
			""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
			"parameters": { # 使用 parameters 字段来定义函数接收的参数
				"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
				"required": ["query"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
				"properties": { # properties 中是具体的参数定义，你可以定义多个参数
					"query": { # 在这里，key 是参数名称，value 是参数的具体定义
						"type": "string", # 使用 type 定义参数类型
						"description": """
							用户搜索的内容，请从用户的提问或聊天上下文中提取。
						""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
					}
				}
			}
		}
	},
	{
		"type": "function", # 约定的字段 type，目前支持 function 作为值
		"function": { # 当 type 为 function 时，使用 function 字段定义具体的函数内容
			"name": "crawl", # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
			"description": """
				根据网站地址（URL）获取网页内容。
			""", # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
			"parameters": { # 使用 parameters 字段来定义函数接收的参数
				"type": "object", # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
				"required": ["url"], # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
				"properties": { # properties 中是具体的参数定义，你可以定义多个参数
					"url": { # 在这里，key 是参数名称，value 是参数的具体定义
						"type": "string", # 使用 type 定义参数类型
						"description": """
							需要获取内容的网站地址（URL），通常情况下从搜索结果中可以获取网站的地址。
						""" # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
					}
				}
			}
		}
	}
]
 
 
def search_impl(query: str) -> List[Dict[str, Any]]:
    """
    search_impl 使用搜索引擎对 query 进行搜索，目前主流的搜索引擎（例如 Bing）都提供了 API 调用方式，你可以自行选择
    你喜欢的搜索引擎 API 进行调用，并将返回结果中的网站标题、网站链接、网站简介信息放置在一个 dict 中返回。
 
    这里只是一个简单的示例，你可能需要编写一些鉴权、校验、解析的代码。
    """
    r = httpx.get("https://your.search.api", params={"query": query})
    return r.json()
 
 
def search(arguments: Dict[str, Any]) -> Any:
    query = arguments["query"]
    result = search_impl(query)
    return {"result": result}
 
 
def crawl_impl(url: str) -> str:
    """
    crawl_url 根据 url 获取网页上的内容。
 
    这里只是一个简单的示例，在实际的网页抓取过程中，你可能需要编写更多的代码来适配复杂的情况，例如异步加载的数据等；同时，在获取
    网页内容后，你可以根据自己的需要对网页内容进行清洗，只保留文本或移除不必要的内容（例如广告信息等）。
    """
    r = httpx.get(url)
    return r.text
 
 
def crawl(arguments: dict) -> str:
    url = arguments["url"]
    content = crawl_impl(url)
    return {"content": content}
 
 
# 通过 tool_map 将每个工具名称及其对应的函数进行映射，以便在 Kimi 大模型返回 tool_calls 时能快速找到应该执行的函数
tool_map = {
    "search": search,
    "crawl": crawl,
}
 
messages = [
    {"role": "system",
     "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。"},
    {"role": "user", "content": "请联网搜索 Context Caching，并告诉我它是什么。"}  # 在提问中要求 Kimi 大模型联网搜索
]
 
finish_reason = None
 
# 我们的基本流程是，带着用户的问题和 tools 向 Kimi 大模型提问，如果 Kimi 大模型返回了 finish_reason: tool_calls，则我们执行对应的 tool_calls，
# 将执行结果以 role=tool 的 message 的形式重新提交给 Kimi 大模型，Kimi 大模型根据 tool_calls 结果进行下一步内容的生成：
#
#   1. 如果 Kimi 大模型认为当前的工具调用结果已经可以回答用户问题，则返回 finish_reason: stop，我们会跳出循环，打印出 message.content；
#   2. 如果 Kimi 大模型认为当前的工具调用结果无法回答用户问题，需要再次调用工具，我们会继续在循环中执行接下来的 tool_calls，直到 finish_reason 不再是 tool_calls；
#
# 在这个过程中，只有当 finish_reason 为 stop 时，我们才会将结果返回给用户。
 
while finish_reason is None or finish_reason == "tool_calls":
    completion = client.chat.completions.create(
        model="kimi-k2-turbo-preview",
        messages=messages,
        temperature=0.6,
        tools=tools,  # <-- 我们通过 tools 参数，将定义好的 tools 提交给 Kimi 大模型
    )
    choice = completion.choices[0]
    finish_reason = choice.finish_reason
    if finish_reason == "tool_calls": # <-- 判断当前返回内容是否包含 tool_calls
        messages.append(choice.message) # <-- 我们将 Kimi 大模型返回给我们的 assistant 消息也添加到上下文中，以便于下次请求时 Kimi 大模型能理解我们的诉求
        for tool_call in choice.message.tool_calls: # <-- tool_calls 可能是多个，因此我们使用循环逐个执行
            tool_call_name = tool_call.function.name
            tool_call_arguments = json.loads(tool_call.function.arguments) # <-- arguments 是序列化后的 JSON Object，我们需要使用 json.loads 反序列化一下
            tool_function = tool_map[tool_call_name] # <-- 通过 tool_map 快速找到需要执行哪个函数
            tool_result = tool_function(tool_call_arguments)
 
            # 使用函数执行结果构造一个 role=tool 的 message，以此来向模型展示工具调用的结果；
            # 注意，我们需要在 message 中提供 tool_call_id 和 name 字段，以便 Kimi 大模型
            # 能正确匹配到对应的 tool_call。
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call_name,
                "content": json.dumps(tool_result), # <-- 我们约定使用字符串格式向 Kimi 大模型提交工具调用结果，因此在这里使用 json.dumps 将执行结果序列化成字符串
            })
 
print(choice.message.content) # <-- 在这里，我们才将模型生成的回复返回给用户

我们使用 while 循环来执行包含工具调用在内的代码逻辑，这是因为 Kimi 大模型通常不会只执行一次工具调用，尤其是在联网搜索这个场景，通常，Kimi 大模型会先选择调用 search 工具，通过 search 工具获取搜索结果后，再调用 crawl 工具将搜索结果中的 url 转换为具体的网页内容，整体的 messages 结构如下所示：

system: prompt                                                                                               # 系统提示词
user: prompt                                                                                                 # 用户提问
assistant: tool_call(name=search, arguments={query: query})                                                  # Kimi 大模型返回 tool_call 调用（单个）                            
tool: search_result(tool_call_id=tool_call.id, name=search)                                                  # 提交 tool_call 执行结果
assistant: tool_call_1(name=crawl, arguments={url: url_1}), tool_call_2(name=crawl, arguments={url: url_2})  # Kimi 大模型继续返回 tool_calls 调用（多个）
tool: crawl_content(tool_call_id=tool_call_1.id, name=crawl)                                                 # 提交 tool_call_1 执行结果
tool: crawl_content(tool_call_id=tool_call_2.id, name=crawl)                                                 # 提交 tool_call_2 执行结果
assistant: message_content(finish_reason=stop)                                                               # Kimi 大模型生成面向用户的回复消息，本轮对话结束

至此，我们完成了“联网查询”工具调用的全过程，如果你实现了自己的 search 和 crawl 方法，那么当你向 Kimi 大模型要求联网查询时，它会调用 search 和 crawl 两个工具，并根据工具调用结果给予你正确的回复。

常见问题及注意事项
关于流式输出
在流式输出模式（stream）下，tool_calls 同样适用，但有一些需要额外注意的地方，列举如下：

在流式输出的过程中，由于 finish_reason 将会在最后的数据块中出现，因此建议使用 delta.tool_calls 字段是否存在来判断当前回复是否包含工具调用；
在流式输出的过程中，会先输出 delta.content，再输出 delta.tool_calls，因此你必须等待 delta.content 输出完成后，才能判断和识别 tool_calls；
在流式输出的过程中，我们会在最初的数据块中，指明当前调用 tool_calls 的 tool_call.id 和 tool_call.function.name，在后续的数据块中将只输出 tool_call.function.arguments；
在流式输出的过程中，如果 Kimi 大模型一次性返回多个 tool_calls，那么我们会额外使用一个名为 index 的字段来标识当前 tool_call 的索引，以便于你能正确拼接 tool_call.function.arguments 参数，我们使用流式输出章节中的代码例子（不使用 SDK 的场合）来说明如何操作：
import os
import json
import httpx  # 我们使用 httpx 库来执行我们的 HTTP 请求
 
tools = [
    {
        "type": "function",  # 约定的字段 type，目前支持 function 作为值
        "function": {  # 当 type 为 function 时，使用 function 字段定义具体的函数内容
            "name": "search",  # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
            "description": """ 
				通过搜索引擎搜索互联网上的内容。
 
				当你的知识无法回答用户提出的问题，或用户请求你进行联网搜索时，调用此工具。请从与用户的对话中提取用户想要搜索的内容作为 query 参数的值。
				搜索结果包含网站的标题、网站的地址（URL）以及网站简介。
			""",  # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
            "parameters": {  # 使用 parameters 字段来定义函数接收的参数
                "type": "object",  # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
                "required": ["query"],  # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
                "properties": {  # properties 中是具体的参数定义，你可以定义多个参数
                    "query": {  # 在这里，key 是参数名称，value 是参数的具体定义
                        "type": "string",  # 使用 type 定义参数类型
                        "description": """
							用户搜索的内容，请从用户的提问或聊天上下文中提取。
						"""  # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
                    }
                }
            }
        }
    },
]
 
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {os.environ.get('MOONSHOT_API_KEY')}",
}
 
data = {
    "model": "kimi-k2-turbo-preview",
    "messages": [
        {"role": "user", "content": "请联网搜索 Context Caching 技术。"}
    ],
    "temperature": 0.6,
    "stream": True,
    "n": 2,  # <-- 注意这里，我们要求 Kimi 大模型输出 2 个回复
    "tools": tools,  # <-- 添加工具调用
}
 
# 使用 httpx 向 Kimi 大模型发出 chat 请求，并获得响应 r
r = httpx.post("https://api.moonshot.cn/v1/chat/completions",
               headers=header,
               json=data)
if r.status_code != 200:
    raise Exception(r.text)
 
data: str
 
# 在这里，我们预先构建一个 List，用于存放不同的回复消息，由于我们设置了 n=2，因此我们将 List 初始化为 2 个元素
messages = [{}, {}]
 
# 在这里，我们使用了 iter_lines 方法来逐行读取响应体
for line in r.iter_lines():
    # 去除每一行收尾的空格，以便更好地处理数据块
    line = line.strip()
 
    # 接下来我们要处理三种不同的情况：
    #   1. 如果当前行是空行，则表明前一个数据块已接收完毕（即前文提到的，通过两个换行符结束数据块传输），我们可以对该数据块进行反序列化，并打印出对应的 content 内容；
    #   2. 如果当前行为非空行，且以 data: 开头，则表明这是一个数据块传输的开始，我们去除 data: 前缀后，首先判断是否是结束符 [DONE]，如果不是，将数据内容保存到 data 变量；
    #   3. 如果当前行为非空行，但不以 data: 开头，则表明当前行仍然归属上一个正在传输的数据块，我们将当前行的内容追加到 data 变量尾部；
 
    if len(line) == 0:
        chunk = json.loads(data)
 
        # 通过循环获取每个数据块中所有的 choice，并获取 index 对应的 message 对象
        for choice in chunk["choices"]:
            index = choice["index"]
            message = messages[index]
            usage = choice.get("usage")
            if usage:
                message["usage"] = usage
            delta = choice["delta"]
            role = delta.get("role")
            if role:
                message["role"] = role
            content = delta.get("content")
            if content:
            	if "content" not in message:
            		message["content"] = content
            	else:
                	message["content"] = message["content"] + content
 
            # 从这里，我们开始处理 tool_calls
            tool_calls = delta.get("tool_calls")  # <-- 先判断数据块中是否包含 tool_calls
            if tool_calls:
                if "tool_calls" not in message:
                    message["tool_calls"] = []  # <-- 如果包含 tool_calls，我们初始化一个列表来保存这些 tool_calls，注意此时的列表中没有任何元素，长度为 0
                for tool_call in tool_calls:
                    tool_call_index = tool_call["index"]  # <-- 获取当前 tool_call 的 index 索引
                    if len(message["tool_calls"]) < (
                            tool_call_index + 1):  # <-- 根据 index 索引扩充 tool_calls 列表，以便于我们能通过下标访问到对应的 tool_call
                        message["tool_calls"].extend([{}] * (tool_call_index + 1 - len(message["tool_calls"])))
                    tool_call_object = message["tool_calls"][tool_call_index]  # <-- 根据下标访问对应的 tool_call
                    tool_call_object["index"] = tool_call_index
 
                    # 下面的步骤，是根据数据块中的信息填充每个 tool_call 的 id、type、function 字段
                    # 在 function 字段中，又包括 name 和 arguments 字段，arguments 字段会由每个数据块
                    # 依次补充，如同 delta.content 字段一般。
 
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        tool_call_object["id"] = tool_call_id
                    tool_call_type = tool_call.get("type")
                    if tool_call_type:
                        tool_call_object["type"] = tool_call_type
                    tool_call_function = tool_call.get("function")
                    if tool_call_function:
                        if "function" not in tool_call_object:
                            tool_call_object["function"] = {}
                        tool_call_function_name = tool_call_function.get("name")
                        if tool_call_function_name:
                            tool_call_object["function"]["name"] = tool_call_function_name
                        tool_call_function_arguments = tool_call_function.get("arguments")
                        if tool_call_function_arguments:
                            if "arguments" not in tool_call_object["function"]:
                                tool_call_object["function"]["arguments"] = tool_call_function_arguments
                            else:
                                tool_call_object["function"]["arguments"] = tool_call_object["function"][
                                                                            "arguments"] + tool_call_function_arguments  # <-- 依次补充 function.arguments 字段的值
                    message["tool_calls"][tool_call_index] = tool_call_object
 
            data = ""  # 重置 data
    elif line.startswith("data: "):
        data = line.lstrip("data: ")
 
        # 当数据块内容为 [DONE] 时，则表明所有数据块已发送完毕，可断开网络连接
        if data == "[DONE]":
            break
    else:
        data = data + "\n" + line  # 我们仍然在追加内容时，为其添加一个换行符，因为这可能是该数据块有意将数据分行展示
 
# 在组装完所有 messages 后，我们分别打印其内容
for index, message in enumerate(messages):
    print("index:", index)
    print("message:", json.dumps(message, ensure_ascii=False))
    print("")

以下是使用 openai SDK 处理流式输出中的 tool_calls 的代码示例：

import os
import json
 
from openai import OpenAI
 
client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY"),
    base_url="https://api.moonshot.cn/v1",
)
 
tools = [
    {
        "type": "function",  # 约定的字段 type，目前支持 function 作为值
        "function": {  # 当 type 为 function 时，使用 function 字段定义具体的函数内容
            "name": "search",  # 函数的名称，请使用英文大小写字母、数据加上减号和下划线作为函数名称
            "description": """ 
				通过搜索引擎搜索互联网上的内容。
 
				当你的知识无法回答用户提出的问题，或用户请求你进行联网搜索时，调用此工具。请从与用户的对话中提取用户想要搜索的内容作为 query 参数的值。
				搜索结果包含网站的标题、网站的地址（URL）以及网站简介。
			""",  # 函数的介绍，在这里写上函数的具体作用以及使用场景，以便 Kimi 大模型能正确地选择使用哪些函数
            "parameters": {  # 使用 parameters 字段来定义函数接收的参数
                "type": "object",  # 固定使用 type: object 来使 Kimi 大模型生成一个 JSON Object 参数
                "required": ["query"],  # 使用 required 字段告诉 Kimi 大模型哪些参数是必填项
                "properties": {  # properties 中是具体的参数定义，你可以定义多个参数
                    "query": {  # 在这里，key 是参数名称，value 是参数的具体定义
                        "type": "string",  # 使用 type 定义参数类型
                        "description": """
							用户搜索的内容，请从用户的提问或聊天上下文中提取。
						"""  # 使用 description 描述参数以便 Kimi 大模型更好地生成参数
                    }
                }
            }
        }
    },
]
 
completion = client.chat.completions.create(
    model="kimi-k2-turbo-preview",
    messages=[
        {"role": "user", "content": "请联网搜索 Context Caching 技术。"}
    ],
    temperature=0.6,
    stream=True,
    n=2,  # <-- 注意这里，我们要求 Kimi 大模型输出 2 个回复
    tools=tools,  # <-- 添加工具调用
)
 
# 在这里，我们预先构建一个 List，用于存放不同的回复消息，由于我们设置了 n=2，因此我们将 List 初始化为 2 个元素
messages = [{}, {}]
 
for chunk in completion:
    # 通过循环获取每个数据块中所有的 choice，并获取 index 对应的 message 对象
    for choice in chunk.choices:
        index = choice.index
        message = messages[index]
        delta = choice.delta
        role = delta.role
        if role:
            message["role"] = role
        content = delta.content
        if content:
        	if "content" not in message:
        		message["content"] = content
        	else:
            	message["content"] = message["content"] + content
 
        # 从这里，我们开始处理 tool_calls
        tool_calls = delta.tool_calls  # <-- 先判断数据块中是否包含 tool_calls
        if tool_calls:
            if "tool_calls" not in message:
                message["tool_calls"] = []  # <-- 如果包含 tool_calls，我们初始化一个列表来保存这些 tool_calls，注意此时的列表中没有任何元素，长度为 0
            for tool_call in tool_calls:
                tool_call_index = tool_call.index  # <-- 获取当前 tool_call 的 index 索引
                if len(message["tool_calls"]) < (
                        tool_call_index + 1):  # <-- 根据 index 索引扩充 tool_calls 列表，以便于我们能通过下标访问到对应的 tool_call
                    message["tool_calls"].extend([{}] * (tool_call_index + 1 - len(message["tool_calls"])))
                tool_call_object = message["tool_calls"][tool_call_index]  # <-- 根据下标访问对应的 tool_call
                tool_call_object["index"] = tool_call_index
 
                # 下面的步骤，是根据数据块中的信息填充每个 tool_call 的 id、type、function 字段
                # 在 function 字段中，又包括 name 和 arguments 字段，arguments 字段会由每个数据块
                # 依次补充，如同 delta.content 字段一般。
 
                tool_call_id = tool_call.id
                if tool_call_id:
                    tool_call_object["id"] = tool_call_id
                tool_call_type = tool_call.type
                if tool_call_type:
                    tool_call_object["type"] = tool_call_type
                tool_call_function = tool_call.function
                if tool_call_function:
                    if "function" not in tool_call_object:
                        tool_call_object["function"] = {}
                    tool_call_function_name = tool_call_function.name
                    if tool_call_function_name:
                        tool_call_object["function"]["name"] = tool_call_function_name
                    tool_call_function_arguments = tool_call_function.arguments
                    if tool_call_function_arguments:
                        if "arguments" not in tool_call_object["function"]:
                            tool_call_object["function"]["arguments"] = tool_call_function_arguments
                        else:
                            tool_call_object["function"]["arguments"] = tool_call_object["function"][
                                                                            "arguments"] + tool_call_function_arguments  # <-- 依次补充 function.arguments 字段的值
                message["tool_calls"][tool_call_index] = tool_call_object
 
# 在组装完所有 messages 后，我们分别打印其内容
for index, message in enumerate(messages):
    print("index:", index)
    print("message:", json.dumps(message, ensure_ascii=False))
    print("")

关于 tool_calls 和 function_call
tool_calls 是 function_call 的进阶版，由于 openai 已将 function_call 等参数（例如 functions）标记为“已废弃”，因此我们的 API 将不再支持 function_call。你可以考虑用 tool_calls 代替 function_call，相比于 function_call，tool_calls 有以下几个优点：

支持并行调用，Kimi 大模型可以一次返回多个 tool_calls，你可以在代码中使用并发的方式同时调用这些 tool_call 以减少时间消耗；
对于没有依赖关系的 tool_calls，Kimi 大模型也会倾向于并行调用，这相比于原顺序调用的 function_call，在一定程度上降低了 Tokens 消耗；
关于 content
在使用工具调用 tool_calls 的过程中，你可能会发现，在 finish_reason=tool_calls 的情况下，偶尔会出现 message.content 字段不为空的情况，通常这里的 content 内容是 Kimi 大模型在解释当前需要调用哪些工具和为什么需要调用这些工具。它的意义在于，如果你的工具调用过程耗时很长，或是完成一轮对话需要串行调用多次工具，那么在调用工具前给予用户一段描述性的语句，能减少用户因为等待而产生的焦虑或不满情绪，同时，向用户说明当前调用了哪些工具和为什么调用工具，也有助于用户理解整个工具调用的流程，并及时给予干预和矫正（例如用户认为当前工具选择错误，可以及时终止工具调用，或是在下轮对话中通过提示词矫正模型的工具选择）。

关于 Tokens
tools 参数中的内容也会被计算在总 Tokens 中，请确保 tools、messages 中的 Tokens 总数合计不超过模型的上下文窗口大小。

关于消息布局
在使用工具调用的场景下，我们的消息不再是：

system: ...
user: ...
assistant: ...
user: ...
assistant: ...

这样排布，而是会变成形似

system: ...
user: ...
assistant: ...
tool: ...
tool: ...
assistant: ...

这样的排布，需要注意的是，当 Kimi 大模型生成了 tool_calls 时，请确保每一个 tool_call 都有对应的 role=tool 的 message，并且这条 message 设置了正确的 tool_call_id，如果 role=tool 的 messages 消息数量与 tool_calls 的数量不一致会导致错误；如果 role=tool 的 messages 中的 tool_call_id 与 tool_calls 中的 tool_call.id 无法对应也会导致错误。

如果你遇到 tool_call_id not found 错误
如果你遇到 tool_call_id not found 错误，可能是由于你未将 Kimi API 返回的 role=assistant 消息添加到 messages 列表中，正确的消息序列应该看起来像这样：

system: ...
user: ...
assistant: ...  # <-- 也许你并未将这一条 assistant message 添加到 messages 列表中
tool: ...
tool: ...
assistant: ...

你可以在每次收到 Kimi API 的返回值后，都执行 messages.append(message) 来将 Kimi API 返回的消息添加到消息列表中，以避免出现 tool_call_id not found 错误。

注意：添加到 messages 列表中位于 role=tool 的 message 之前的 assistant messages，必须完整包含 Kimi API 返回的 tool_calls 字段及字段值。我们推荐直接将 Kimi API 返回的 choice.message “原封不动”地添加到 messages 列表中，以避免可能产生的错误。

Prompt 最佳实践
System Prompt最佳实践：system prompt（系统提示）指的是模型在生成文本或响应之前所接收的初始输入或指令，这个提示对于模型的运作至关重要

编写清晰的说明
为什么需要向模型输出清晰的说明？
模型无法读懂你的想法，如果输出内容太长，可要求模型简短回复。如果输出内容太简单，可要求模型进行专家级写作。如果你不喜欢输出的格式，请向模型展示你希望看到的格式。模型越少猜测你的需求，你越有可能得到满意的结果。

在请求中包含更多细节，可以获得更相关的回答
为了获得高度相关的输出，请保证在输入请求中提供所有重要细节和背景。

一般的请求	更好的请求
如何在Excel中增加数字？	我如何在Excel表对一行数字求和？我想自动为整张表的每一行进行求和，并将所有总计放在名为"总数"的最右列中。
工作汇报总结	将2023年工作记录总结为500字以内的段落。以序列形式列出每个月的工作亮点，并做出2023年全年工作总结。
在请求中要求模型扮演一个角色，可以获得更准确的输出
在 API 请求的'messages' 字段中增加指定模型在回复中使用的角色。

{
  "messages": [
    {"role": "system", "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。"},
    {"role": "user", "content": "你好，我叫李雷，1+1等于多少？"}
  ]
}

在请求中使用分隔符来明确指出输入的不同部分
例如使用三重引号/XML标签/章节标题等定界符可以帮助区分需要不同处理的文本部分。

{
  "messages": [
    {"role": "system", "content": "你将收到两篇相同类别的文章，文章用XML标签分割。首先概括每篇文章的论点，然后指出哪篇文章提出了更好的论点，并解释原因。"},
    {"role": "user", "content": "<article>在这里插入文章</article><article>在这里插入文章</article>"}
  ]
}

{
  "messages": [
    {"role": "system", "content": "你将收到一篇论文的摘要和论文的题目。论文的题目应该让读者对论文主题有清晰的概念，同时也应该引人注目。如果你收到的标题不符合这些标准，请提出5个可选的替代方案"},
    {"role": "user", "content": "摘要:在这里插入摘要。\n\n标题:在这里插入标题"}
  ]
}

明确完成任务所需的步骤
任务建议明确一系列步骤。明确写出这些步骤可以使模型更容易遵循并获得更好的输出。

{
  "messages": [
    {"role": "system", "content": "使用以下步骤来回应用户输入。\n步骤一：用户将用三重引号提供文本。用前缀“摘要：”将这段文本概括成一句话。\n步骤二：将第一步的摘要翻译成英语，并加上前缀 "Translation: "。"},
    {"role": "user", "content": "\"\"\"在此处插入文本\"\"\""}
  ]
}

向模型提供输出示例
向模型提供一般指导的示例描述，通常比展示任务的所有排列让模型的输出更加高效。例如，如果你打算让模型复制一种难以明确描述的风格，来回应用户查询。这被称为“few-shot”提示。

{
  "messages": [
    {"role": "system", "content": "以一致的风格回答"},
    {"role": "user", "content": "在此处插入文本"}
  ]
}

指定期望模型输出的长度
你可以要求模型生成特定目标长度的输出。目标输出长度可以用文数、句子数、段落数、项目符号等来指定。但请注意，指示模型生成特定数量的文字并不具有高精度。模型更擅长生成特定数量的段落或项目符号的输出。

{
  "messages": [
    {"role": "user", "content": "用两句话概括三引号内的文本，50字以内。\"\"\"在此处插入文本\"\"\""}
  ]
}

提供参考文本
指导模型使用参考文本来回答问题
如果您可以提供一个包含与当前查询相关的可信信息的模型，那么就可以指导模型使用所提供的信息来回答问题

{
  "messages": [
    {"role": "system", "content": "使用提供的文章（用三引号分隔）回答问题。如果答案在文章中找不到，请写"我找不到答案。" "},
    {"role": "user", "content": "<请插入文章，每篇文章用三引号分隔>"}
  ]
}

拆分复杂的任务
通过分类来识别用户查询相关的指令
对于需要大量独立指令集来处理不同情况的任务来说，对查询类型进行分类，并使用该分类来明确需要哪些指令可能会帮助输出。

# 根据客户查询的分类，可以提供一组更具体的指示给模型，以便它处理后续步骤。例如，假设客户需要“故障排除”方面的帮助。
{
  "messages": [
    {"role": "system", "content": "你将收到需要技术支持的用户服务咨询。可以通过以下方式帮助用户：\n\n-请他们检查***是否配置完成。\n如果所有***都配置完成，但问题依然存在，请询问他们使用的设备型号\n-现在你需要告诉他们如何重启设备：\n=设备型号是A，请操作***。\n-如果设备型号是B，建议他们操作***。"}
  ]
}

对于轮次较长的对话应用程序，总结或过滤之前的对话
由于模型有固定的上下文长度显示，所以用户与模型助手之间的对话不能无限期地继续。

针对这个问题，一种解决方案是总结对话中的前几个回合。一旦输入的大小达到预定的阈值，就会触发一个查询来总结先前的对话部分，先前对话的摘要同样可以作为系统消息的一部分包含在内。或者，整个对话过程中的先前对话可以被异步总结。

分块概括长文档，并递归构建完整摘要
要总结一本书的内容，我们可以使用一系列的查询来总结文档的每个章节。部分摘要可以汇总并总结，产生摘要的摘要。这个过程可以递归进行，直到整本书都被总结完毕。如果需要使用前面的章节来理解后面的部分，那么可以在总结书中给定点的内容时，包括对给定点之前的章节的摘要。

如何在 Kimi API 中使用官方工具
Kimi 开放平台特别推出官方工具，您可以将 Kimi 官方工具免费集成到您自己的应用程序中，打造属于您的智能化商业产品！（目前 Kimi 开放平台官方工具执行限时免费，当工具负载达到容量上限时，可能会采取临时的限流措施）

本章节将为您详细介绍如何在您的应用中轻松调用和执行这些官方工具。

Kimi 官方工具列表
工具名称	工具描述
convert	单位转换工具，支持长度、质量、体积、温度、面积、时间、能量、压力、速度和货币的单位换算
web-search	实时信息及互联网检索工具。联网搜索目前收费，详情请见 联网搜索价格
rethink	智能整理想法工具
random-choice	随机选择工具
mew	随机产生猫的叫声和祝福的工具
memory	记忆存储和检索系统工具，支持对话历史、用户偏好等数据的持久化
excel	Excel 和 CSV 文件的分析工具
date	日期时间处理工具
base64	base64 编码与解码工具
fetch	URL 内容提取 markdown 格式化工具
quickjs	使用 QuickJS 引擎安全执行 JavaScript 代码的工具
code_runner	Python代码执行工具
调用 web_search 官方工具的示例
以下是一个 python 示例，以 web_search 官方工具为例，展示了如何通过 Kimi API 调用官方工具：

您也可以通过 Kimi 开发工作台来交互式体验 Kimi 模型和工具的能力，前往开发工作台

这里是您可以使用的 Kimi 官方 Formula 工具，您可以将 formula URI 增加到下方 demo 示例中体验：moonshot/convert:latest, moonshot/web-search:latest, moonshot/rethink:latest, moonshot/random-choice:latest, moonshot/mew:latest, moonshot/memory:latest, moonshot/excel:latest, moonshot/date:latest, moonshot/base64:latest, moonshot/fetch:latest, moonshot/quickjs:latest, moonshot/code_runner:latest

# Formula Chat Client - OpenAI chat with official tools
# Uses MOONSHOT_BASE_URL and MOONSHOT_API_KEY for OpenAI client
 
import os
import json
import asyncio
import argparse
import httpx
from openai import AsyncOpenAI
 
 
class FormulaChatClient:
    def __init__(self, moonshot_base_url: str, api_key: str):
        self.openai = AsyncOpenAI(base_url=moonshot_base_url, api_key=api_key)
        self.httpx = httpx.AsyncClient(
            base_url=moonshot_base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        self.model = "kimi-k2-turbo-preview"
 
    async def get_tools(self, formula_uri: str):
        response = await self.httpx.get(f"/formulas/{formula_uri}/tools")
        return response.json().get("tools", [])
 
    async def call_tool(self, formula_uri: str, function: str, args: dict):
        response = await self.httpx.post(
            f"/formulas/{formula_uri}/fibers",
            json={"name": function, "arguments": json.dumps(args)},
        )
        fiber = response.json()
 
        if fiber.get("status", "") == "succeeded":
            return fiber["context"].get("output") or fiber["context"].get(
                "encrypted_output"
            )
 
        if "error" in fiber:
            return f"Error: {fiber['error']}"
        if "error" in fiber.get("context", {}):
            return f"Error: {fiber['context']['error']}"
        if "output" in fiber.get("context", {}):
            return f"Error: {fiber['context']['output']}"
        return "Error: Unknown error"
 
    async def handle_response(self, response, messages, all_tools, tool_to_uri):
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            print(f"\nAI Response: {message.content}")
            return
 
        print(f"\nAI decided to use {len(message.tool_calls)} tool(s):")
 
        for call in message.tool_calls:
            func_name = call.function.name
            args = json.loads(call.function.arguments)
 
            print(f"\nCalling tool: {func_name}")
            print(f"Arguments: {json.dumps(args, ensure_ascii=False, indent=2)}")
 
            uri = tool_to_uri.get(func_name)
            if not uri:
                raise ValueError(f"No URI found for tool {func_name}")
 
            result = await self.call_tool(uri, func_name, args)
            if len(result) > 100:
                print(f"Tool result: {result[:100]}...")  # limit the output length
            else:
                print(f"Tool result: {result}")
 
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
 
        next_response = await self.openai.chat.completions.create(
            model=self.model, messages=messages, tools=all_tools
        )
        await self.handle_response(next_response, messages, all_tools, tool_to_uri)
 
    async def chat(self, question, messages, all_tools, tool_to_uri):
        messages.append({"role": "user", "content": question})
        response = await self.openai.chat.completions.create(
            model=self.model, messages=messages, tools=all_tools
        )
        await self.handle_response(response, messages, all_tools, tool_to_uri)
 
    async def close(self):
        await self.httpx.aclose()
 
 
def normalize_formula_uri(uri: str) -> str:
    """Normalize formula URI with default namespace and tag"""
    if "/" not in uri:
        uri = f"moonshot/{uri}"
    if ":" not in uri:
        uri = f"{uri}:latest"
    return uri
 
 
async def main():
    parser = argparse.ArgumentParser(description="Chat with formula tools")
    parser.add_argument(
        "--formula",
        action="append",
        default=["moonshot/web-search:latest"],
        help="Formula URIs",
    )
    parser.add_argument("--question", help="Question to ask")
 
    args = parser.parse_args()
 
    # Process and deduplicate formula URIs
    raw_formulas = args.formula or ["moonshot/web-search:latest"]
    normalized_formulas = [normalize_formula_uri(uri) for uri in raw_formulas]
    unique_formulas = list(
        dict.fromkeys(normalized_formulas)
    )  # Preserve order while deduping
 
    print(f"Initialized formulas: {unique_formulas}")
 
    moonshot_base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    api_key = os.getenv("MOONSHOT_API_KEY")
 
 
    if not api_key:
        print("MOONSHOT_API_KEY required")
        return
 
    client = FormulaChatClient(moonshot_base_url, api_key)
 
    # Load and validate tools
    print("\nLoading tools from all formulas...")
    all_tools = []
    function_names = set()
    tool_to_uri = {}  # inverted index to the tool name
 
    for uri in unique_formulas:
        tools = await client.get_tools(uri)
        print(f"\nTools from {uri}:")
 
        for tool in tools:
            func = tool.get("function", None)
            if not func:
                print(f"Skipping tool using type: {tool.get('type', 'unknown')}")
                continue
            func_name = func.get("name")
            assert func_name, f"Tool missing name: {tool}"
            assert (
                func_name not in tool_to_uri
            ), f"ERROR: Tool '{func_name}' conflicts between {tool_to_uri.get(func_name)} and {uri}"
 
            if func_name in function_names:
                print(
                    f"ERROR: Duplicate function name '{func_name}' found across formulas"
                )
                print(f"Function {func_name} already exists in another formula")
                await client.close()
                return
 
            function_names.add(func_name)
            all_tools.append(tool)
            tool_to_uri[func_name] = uri
            print(f"  - {func_name}: {func.get('description', 'N/A')}")
 
    print(f"\nTotal unique tools loaded: {len(all_tools)}")
    if not all_tools:
        print("Warning: No tools found in any formula")
        return
 
    try:
        messages = [
            {
                "role": "system",
                "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。",
            }
        ]
        if args.question:
            print(f"\nUser: {args.question}")
            await client.chat(args.question, messages, all_tools, tool_to_uri)
        else:
            print("Chat mode (type 'q' to quit)")
            while True:
                question = input("\nQ: ").strip()
                if question.lower() == "q":
                    break
                if question:
                    await client.chat(question, messages, all_tools, tool_to_uri)
 
    finally:
        await client.close()
 
 
if __name__ == "__main__":
    asyncio.run(main())
 

相关概念和接口说明
Formula 概念
理解 Kimi 官方工具之前，需要学习一个概念 ‘Formula’。Formula 是一个轻量脚本引擎集合。它可以将 Python 脚本转化为"可被 AI 一键触发的瞬态算力"，让开发者只需专注于代码编写，其余的启动、调度、隔离、计费、回收等工作都由平台负责。

Formula 通过语义化的 URI（如 moonshot/web-search:latest）来调用，每个 formula 包含声明（告诉 AI 能干什么）和实现（Python 代码），平台会自动处理所有底层细节（启动、隔离、回收等），让工具可以在社区中轻松分享和复用。您可以在 Kimi Playground 中体验和调试这些工具，也可以通过 API 在应用中调用它们。

调用官方工具的方法
对 formula uri， 一般它由 3 个部分组成，比如 moonshot/web-search:latest。其中 web-search 部分是它的 name，namespace 目前我们只支持 moonshot, latest 会是默认的 tag。

一个典型的用法是如果我们需要调用 web search，可以发一个这样的 http request:

export FORMULA_URI="moonshot/web-search:latest"
export MOONSHOT_BASE_URL="https://api.moonshot.cn/v1"
 
curl -X POST ${MOONSHOT_BASE_URL}/formulas/${FORMULA_URI}/fibers \
-H "Content-Type: application/json" \
-H "Authorization: Bearer $MOONSHOT_API_KEY" \
-d '{
  "name": "web_search",
  "arguments": "{\"query\": \"月之暗面最近有什么消息\"}"
}'

对 web-search，由于创建的时候设置为了 protected，它的结果会在 context.encrypted_output 字段出现。格式类似 ----MOONSHOT ENCRYPTED BEGIN----... ----MOONSHOT ENCRYPTED END----，这个内容可以塞到 tool 里面直接调用。

和 Chat Completions 的交互说明
如 3214567是素数吗? 一个 Tool Calls 的调用案例介绍，这儿有几个关键的信息我们需要让 Formula API 和模型对齐。

tools 字段怎么设置？
现在给定 formula uri 比如 moonshot/web-search:latest ，我们可以直接把它拼接到 url 里面

curl ${MOONSHOT_BASE_URL}/formulas/${FORMULA_URI}/tools \
    -H "Authorization: Bearer $MOONSHOT_API_KEY"

一个样例输出是这样的:

{
  "object": "list",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "web_search",
        "description": "Search the web for information",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "description": "What to search for",
              "type": "string"
            }
          },
          "required": [ "query" ]
        }
      }
    }
  ]
}

我们可以简单取 tools 字段 ( 总是一个 array of dict ) 追加到你请求的 tools 列表中。我们总是保证这个 list 是 API 兼容的。

不过你可能需要注意下这儿如果 type=function ， 那么你可能需要保证function.name 在一个 API 的请求中是唯一的，不然这个 chat completion request 会被视为非法请求而立即被 401 返回。

此外，如果你同时使用了多个 formula，你需要自己维护一个 function.name -> formula_uri 的这个映射，以备后用。

模型请求返回的处理
如果这个 chat completion 的返回 finish_reason=tool_calls，说明模型认为触发了工具调用的中断。这时候它内容可能类似是这样的:

{
  "id": "chatcmpl-1234567890",
  "object": "chat.completion",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "tool_calls": [
          {
            "id": "web_search:0",
            "type": "function",
            "function": {
              "name": "web_search",
              "arguments": "{\"query\": \"天蓝色的 RGB 是什么？\" }"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}

我们通过 choices[0].message.tool_calls[0].function.name 发现需要调用 web_search，然后发现 web_search 对应的 formula_uri 是 moonshot/web-search:latest。

我们可以完整复制返回中 choices[0].message.tool_calls[0].function 作为 body，向 ${MOONSHOT_BASE_URL}/formulas/${FORMULA_URI}/fibers 发出请求。特别的，因为模型输出的 function.arguments 虽然内容是一个合法的 json，但是在格式上仍然是一个 encoded string。你不需要转义，直接作为调用的 body 就可以了。

Fiber 请求返回的处理
Fiber 是一次具体执行的“进程快照”，含日志、Tracing、资源用量，方便调试与审计。

POST 的结果一般是 status 可能是 succeeded 或者各种类型的错误，当 succeeded 后，结果可能类似如下：

{
  "id": "fiber-f43p7sby7ny111houyq1",
  "object": "fiber",
  "created_at": 1753440997,
  "lambda_id": "lambda-f3w8y6qcoqgi11h8q7ui",
  "status": "succeeded",
  "context": {
    "input": "{\"name\":\"web_search\",\"arguments\":\"{\\\"query\\\": \\\"天蓝色的 RGB 是什么？\\\" }\"}",
    "encrypted_output": "----MOONSHOT ENCRYPTED BEGIN----+nf6...DSM=----MOONSHOT ENCRYPTED END----"
  },
  "formula": "moonshot/web-search:latest",
  "organization_id": "staff",
  "project_id": "proj-88a5894a985646b5902b70909748ba16"
}

特别的，如果是搜索，可能会返回的是 encrypted_output，而一般情况下我们可能返回 output 。这个 output 就是你的下一轮输入。

一般继续请求的时候 messages 排列如下:

messages = [
{ 
  /* other messages */
  { /* 上一轮模型的返回内容 */
    "role": "assistant",
    tool_calls": [
      {
        "id": "web_search:0",
        "type": "function",
        "function": {
          "name": "web_search",
          "arguments": "{\"query\": \"天蓝色的 RGB 是什么？\" }"
        }
      }
    ]
  },
  { /* 你需要补充的信息 */
    "role": "tool",
    "tool_call_id": "web_search:0",  /* 注意这儿的 id 需要和前面的 tool_calls[].id 对齐 */
    "content": "----MOONSHOT ENCRYPTED BEGIN----+nf6...DSM=----MOONSHOT ENCRYPTED END----"
  }
]

接下来模型就可以做进一步的推理了。

注意要点：

模型可能会返回超过一个 tool_calls，因此你必须对所有 tool_calls 都给出返回模型才会继续，否则会认为请求不合法而拒绝请求

assistant 如果带 tool_calls，接下来必定是和 tool_calls 完全一致的几个 role=tool 的 message，并且 tool_call_id 要求和前面的 tool_calls.id 一一对齐。

如果有多个 tool_calls 顺序不敏感

我们模型输出的 tool_calls 的几个 id 一定是唯一的，后面 role=tool 时候 id 也必须对齐

仅在当轮这个 tool_calls - response 的局部有唯一性要求，对整个 conversation 或者全局这个唯一性不敏感

使用 Kimi API 进行文件问答
Kimi 智能助手提供了上传文件、并基于文件进行问答的能力，Kimi API 也提供了相同的实现，下面我们用一个实际例子来讲述如何通过 Kimi API 完成文件上传和文件问答：

from pathlib import Path
from openai import OpenAI
 
client = OpenAI(
    api_key="MOONSHOT_API_KEY", # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
    base_url="https://api.moonshot.cn/v1",
)
 
# moonshot.pdf 是一个示例文件, 我们支持文本文件和图片文件，对于图片文件，我们提供了 OCR 的能力
# 上传文件时，我们可以直接使用 openai 库的文件上传 API，使用标准库 pathlib 中的 Path 构造文件
# 对象，并将其传入 file 参数即可，同时将 purpose 参数设置为 file-extract；注意，目前文件上传
# 接口仅支持 file-extract 一种 purpose 值。
file_object = client.files.create(file=Path("moonshot.pdf"), purpose="file-extract")
 
# 获取结果
# file_content = client.files.retrieve_content(file_id=file_object.id)
# 注意，某些旧版本示例中的 retrieve_content API 在最新版本标记了 warning, 可以用下面这行代替
# （如果使用旧版本的 SDK，可以继续延用 retrieve_content API）
file_content = client.files.content(file_id=file_object.id).text
 
# 把文件内容通过系统提示词 system prompt 放进请求中
messages = [
    {
        "role": "system",
        "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不可翻译成其他语言。",
    },
    {
        "role": "system",
        "content": file_content, # <-- 这里，我们将抽取后的文件内容（注意是文件内容，而不是文件 ID）放置在请求中
    },
    {"role": "user", "content": "请简单介绍 moonshot.pdf 的具体内容"},
]
 
# 然后调用 chat-completion, 获取 Kimi 的回答
completion = client.chat.completions.create(
  model="kimi-k2-turbo-preview",
  messages=messages,
  temperature=0.6,
)
 
print(completion.choices[0].message)

让我们回顾一下文件问答的基本步骤及注意事项：

通过文件上传接口 /v1/files 或 SDK 中的 files.create API 将文件上传至 Kimi 服务器；
通过文件抽取接口 /v1/files/{file_id} 或 SDK 中的 files.content API 获取文件内容，此时获取的文件内容已经对齐了我们推荐的模型易于理解的格式；
将文件抽取后（已经对齐格式的）文件内容（而不是文件 id），以系统提示词 system prompt 的形式放置在 messages 列表中；
开始你对文件内容的提问；
再次注意，请将文件内容放置在 prompt 中，而不是文件的 file_id。

针对多个文件的问答
如果你想针对多个文件内容进行提问，实现方式也非常简单，将每个文件单独放置在一个系统提示词 system prompt 中即可，用代码演示如下：

from typing import *
 
import os
import json
from pathlib import Path
 
from openai import OpenAI
 
client = OpenAI(
    api_key="MOONSHOT_API_KEY", # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
    base_url="https://api.moonshot.cn/v1",
)
 
 
def upload_files(files: List[str]) -> List[Dict[str, Any]]:
    """
    upload_files 会将传入的文件（路径）全部通过文件上传接口 '/v1/files' 上传，并获取上传后的
    文件内容生成文件 messages。每个文件会是一个独立的 message，这些 message 的 role 均为
    system，Kimi 大模型会正确识别这些 system messages 中的文件内容。
 
    :param files: 一个包含要上传文件的路径的列表，路径可以是绝对路径也可以是相对路径，请使用字符串
        的形式传递文件路径。
    :return: 一个包含了文件内容的 messages 列表，请将这些 messages 加入到 Context 中，
        即请求 `/v1/chat/completions` 接口时的 messages 参数中。
    """
    messages = []
 
    # 对每个文件路径，我们都会上传文件并抽取文件内容，最后生成一个 role 为 system 的 message，并加入
    # 到最终返回的 messages 列表中。
    for file in files:
        file_object = client.files.create(file=Path(file), purpose="file-extract")
        file_content = client.files.content(file_id=file_object.id).text
        messages.append({
            "role": "system",
            "content": file_content,
        })
 
    return messages
 
 
def main():
    file_messages = upload_files(files=["upload_files.py"])
 
    messages = [
        # 我们使用 * 语法，来解构 file_messages 消息，使其成为 messages 列表的前 N 条 messages。
        *file_messages,
        {
            "role": "system",
            "content": "你是 Kimi，由 Moonshot AI 提供的人工智能助手，你更擅长中文和英文的对话。你会为用户提供安全，有帮助，"
                       "准确的回答。同时，你会拒绝一切涉及恐怖主义，种族歧视，黄色暴力等问题的回答。Moonshot AI 为专有名词，不"
                       "可翻译成其他语言。",
        },
        {
            "role": "user",
            "content": "总结一下这些文件的内容。",
        },
    ]
 
    print(json.dumps(messages, indent=2, ensure_ascii=False))
 
    completion = client.chat.completions.create(
        model="kimi-k2-turbo-preview",
        messages=messages,
    )
 
    print(completion.choices[0].message.content)
 
 
if __name__ == '__main__':
    main()

文件管理最佳实践
通常而言，文件上传和文件抽取功能旨在将不同格式的文件提取成对齐了我们推荐的模型易于理解的格式，在完成文件上传和文件抽取步骤后，抽取后的内容可以进行在本地进行存储，在下一次基于文件的问答请求中，不必再次进行上传和抽取动作。

同时，由于我们对单用户的文件上传数量进行了限制（每个用户最多上传 1000 个文件），因此我们建议你在文件抽取过程进行完毕后，定期清理已上传的文件，你可以定期执行下面的代码，以清理已上传的文件：

from openai import OpenAI
 
client = OpenAI(
    api_key="MOONSHOT_API_KEY", # 在这里将 MOONSHOT_API_KEY 替换为你从 Kimi 开放平台申请的 API Key
    base_url="https://api.moonshot.cn/v1",
)
 
file_list = client.files.list()
 
for file in file_list.data:
	client.files.delete(file_id=file.id)

在上述代码中，我们先通过 files.list API 列出所有的文件明细，并逐一通过 files.delete API 删除文件，定期执行这样的操作，以确保释放文件存储空间，以便后续文件上传和抽取动作能成功执行。

