import ReactDOM from "react-dom/client";

import App from "./rewrite/App";

// 与 legacy/ui_v1/static/index.html 完全相同的样式加载顺序
import "./styles/workbench.css";
import "./styles/base.css";
import "./styles/layout.css";
import "./styles/ui-header.css";
import "./styles/workbench-panels.css";
import "./styles/chat-messages.css";
import "./styles/canvas-tabs.css";
import "./styles/report-canvas.css";
import "./styles/workflow-panel.css";
import "./styles/planner-visualizer.css";
import "./styles/modals.css";
import "./styles/rule-growth.css";
import "./styles/toast-notifications.css";
import "./styles/scanner-ui.css";
import "./styles/git-history.css";
import "./styles/settings.css";
// 旧版 index.html 中 diff2html.min.css 位于全部业务样式之后，用于覆盖 .d2h-* 规则；
// 作为模块在最后引入，保证 dev 注入与 build 打包的层叠顺序都与旧版一致。
import "./styles/diff2html.min.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
