# UI Snapshot V1

这份目录是当前迁移基线，直接冻结自：

- `legacy/ui_v1/static`

目的只有一个：在 React 迁移过程中，保留你截图里的那一版前端上下文，不再边改边丢参考实现。

## 页面基线

- `index.html`
  - `page-review`
  - `page-dashboard`
  - `page-diff`
  - `page-rule-growth`
  - `page-config`
- `workbench.css`
  - 审查页主布局、hero 动画、右侧进度/日志面板
- `css/layout.css`
  - 左侧窄导航、历史抽屉、主内容区
- `css/ui-header.css`
  - 顶部路径条、模式徽标、模型下拉区
- `css/workbench-panels.css`
  - report/chat/right rail 三栏状态切换
- `css/rule-growth.css`
  - 规则优化三块卡片布局
- `css/scanner-ui.css`
  - diff/file-list/scanner 卡片与问题列表

## 模块映射

- `modules/dashboard.js`
  - 仪表盘四张卡片 + 项目意图分析
- `modules/review.js`
  - 审查启动、hero 首屏、报告/详细信息切换
- `modules/diff.js`
  - 文件列表、代码查看区、模式切换
- `modules/rule-growth.js`
  - 冲突统计、可应用规则、参考提示
- `modules/session.js`
  - 历史抽屉、会话切换、历史回放
- `modules/scanner-ui.js`
  - 右侧扫描区
- `modules/progress.js`
  - 右侧阶段进度
- `modules/model.js`
  - 模型选择
- `modules/folder-picker.js`
  - 项目目录选择

## React 迁移约束

- 活前端继续只调用 `/api/v2`
- 视觉与布局以这份快照为准，不允许再引入新的信息架构
- 每次迁移只动一个页面或一个面板，不整壳重做
- 迁移完成前，这份目录不作为运行入口，只作为参考基线
