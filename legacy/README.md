# Legacy Assets

本目录主要保存重构后退出主线的历史资产，另有少量模块仍被当前代码调用：

- `ui_v1/`: 旧版原生脚本 Web UI
- `support/`: Docker、PyInstaller、打包入口与相关辅助文件
- `examples/`: 早期 GUI/命令行示例与旧接口说明
- `tools/`: 离线冷工具，例如历史 JSON 会话导入器

当前受支持的主线只有：

- `python run_ui.py`
- `/api/v2`
- `deltaconverge review|qa|sessions`

`ui_v1/dialogs.py` 仍由当前原生选目录能力调用，不能随旧 UI 静态资源一起删除。其余资产主要用于追溯，不作为当前运行和发布步骤。

`support/` 下的旧打包脚本尚未适配当前 React 与完整文档交付；新版 EXE 需另行构建和验收。当前文档入口见 [docs/README.md](../docs/README.md)，交付状态见[发布说明](../docs/部署/发布说明.md)。
