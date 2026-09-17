import type { ReactNode } from "react";

type Props = {
  viewMode: "review" | "config";
  statusText: string;
  sidebar: ReactNode;
  children: ReactNode;
  onChangeView: (viewMode: "review" | "config") => void;
};

export function WorkspaceShell({ viewMode, statusText, sidebar, children, onChangeView }: Props) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Kernel First</p>
          <h1>DeltaConverge</h1>
          <p className="topbar-copy">Hard-cut web workspace on top of a single Python kernel and `/api/v2` adapter.</p>
        </div>
        <div className="topbar-actions">
          <span className="status-chip">{statusText}</span>
          <button className={viewMode === "review" ? "active" : ""} onClick={() => onChangeView("review")}>
            Review Workspace
          </button>
          <button className={viewMode === "config" ? "active" : ""} onClick={() => onChangeView("config")}>
            Kernel Config
          </button>
        </div>
      </header>

      <main className="layout">
        {sidebar}
        <section className="main-stage">{children}</section>
      </main>
    </div>
  );
}
