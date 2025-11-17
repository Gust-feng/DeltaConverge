# 文件接口（/v1/files）

本页总结文件上传、抽取与基于文件的问答流程，以及常见限制与最佳实践。

1. 用途与限制
- 用途：上传文件并抽取文本（OCR 支持图片/PDF），用于文件问答或将文档内容注入 `system` message。
- 限制：单文件 ≤ 100MB；单用户最多 1000 个文件；总量 ≤ 10GB。

2. 常用端点
- `POST /v1/files`：上传（`purpose="file-extract"`）。
- `GET /v1/files`：列出文件。
- `DELETE /v1/files/{file_id}`：删除文件。
- `GET /v1/files/{file_id}/content`：获取抽取后的文本。

3. 上传与问答示例（Python）

```python
from pathlib import Path
from openai import OpenAI

client = OpenAI(api_key="$MOONSHOT_API_KEY", base_url="https://api.moonshot.cn/v1")
file_obj = client.files.create(file=Path('doc.pdf'), purpose='file-extract')
text = client.files.content(file_id=file_obj.id).text
messages = [{"role":"system","content":text}, {"role":"user","content":"请概述该文件"}]
resp = client.chat.completions.create(model=model, messages=messages)
print(resp.choices[0].message.content)
```

4. 多文件问答
- 每个文件单独生成一个 `system` message 并加入 `messages`；避免一次性将大量原始文本直接并入导致 token 超限。

5. 文件管理最佳实践
- 抽取后的文本可本地缓存以避免重复上传/抽取；定期清理旧文件以释放配额。
