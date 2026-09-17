# Legacy Assets

本目录保存本轮硬切重构后退出主线的旧资产，仅作冷备参考：

- `ui_v1/`: 旧版原生脚本 Web UI
- `support/`: Docker、PyInstaller、打包入口与相关辅助文件
- `examples/`: 早期 GUI/命令行示例与旧接口说明
- `tools/`: 离线冷工具，例如历史 JSON 会话导入器

当前受支持的主线只有：

- `python run_ui.py`
- `/api/v2`
- `deltaconverge review|qa|sessions`

旧资产不再参与默认启动、文档说明或回归验证。
