import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { queryClient, setupQueryPersistence } from "./queryClient";
// 样式已随前端一并纳入 src/styles/，不再依赖 legacy/ 目录，
// 以保证前端可独立构建（Docker 构建阶段只复制 frontend/）。
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
import "./styles.css";

setupQueryPersistence();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
