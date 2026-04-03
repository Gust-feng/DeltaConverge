import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { queryClient, setupQueryPersistence } from "./queryClient";
import "../../../legacy/ui_v1/static/workbench.css";
import "../../../legacy/ui_v1/static/css/base.css";
import "../../../legacy/ui_v1/static/css/layout.css";
import "../../../legacy/ui_v1/static/css/ui-header.css";
import "../../../legacy/ui_v1/static/css/workbench-panels.css";
import "../../../legacy/ui_v1/static/css/chat-messages.css";
import "../../../legacy/ui_v1/static/css/canvas-tabs.css";
import "../../../legacy/ui_v1/static/css/report-canvas.css";
import "../../../legacy/ui_v1/static/css/workflow-panel.css";
import "../../../legacy/ui_v1/static/css/planner-visualizer.css";
import "../../../legacy/ui_v1/static/css/modals.css";
import "../../../legacy/ui_v1/static/css/rule-growth.css";
import "../../../legacy/ui_v1/static/css/toast-notifications.css";
import "../../../legacy/ui_v1/static/css/scanner-ui.css";
import "../../../legacy/ui_v1/static/css/git-history.css";
import "./styles.css";

setupQueryPersistence();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
