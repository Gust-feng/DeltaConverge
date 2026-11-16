import { useEffect, useRef } from "react";

import { SessionController } from "../features/sessions/SessionController";
import { useAppStore } from "../state/appStore";
import { Icon } from "./Icon";

export function HistoryDrawer() {
  const open = useAppStore((s) => s.historyDrawerOpen);
  const setOpen = useAppStore((s) => s.setHistoryDrawerOpen);
  const listRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<SessionController | null>(null);

  useEffect(() => {
    const controller = new SessionController(listRef.current);
    controllerRef.current = controller;
    controller.init();
    return () => {
      controllerRef.current = null;
      controller.dispose();
    };
  }, []);

  useEffect(() => {
    if (open) void controllerRef.current?.loadSessions();
  }, [open]);

  return (
    <aside id="historyDrawer" className={`history-drawer ${open ? "open" : ""}`}>
      <div className="drawer-header">
        <h3>历史记录</h3>
        <div className="header-actions">
          <button id="closeHistoryBtn" type="button" className="icon-btn-small" onClick={() => setOpen(false)}>
            <Icon name="x" plain />
          </button>
        </div>
      </div>
      <div id="sessionList" ref={listRef} className="session-list" />
    </aside>
  );
}
