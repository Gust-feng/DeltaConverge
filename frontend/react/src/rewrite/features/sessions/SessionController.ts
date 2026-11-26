import {
  deleteSession,
  getEvents,
  getMessages,
  getSessionDetailRaw,
  getSessionStatus,
  renameSession,
} from "../../lib/api";
import { flattenEvents } from "../../lib/events";
import { escapeHtml, getIcon } from "../../lib/html";
import { renderMarkdown } from "../../lib/markdown";
import { showToast } from "../../lib/toast";
import { useAppStore } from "../../state/appStore";
import { renderReportPlaceholder, resetMonitorPanel, resetProgress } from "../review/progress";
import { historyCache } from "./historyCache";

const LAST_SESSION_KEY = "lastSessionId";

function getLastSessionId(): string | null {
  try {
    return localStorage.getItem(LAST_SESSION_KEY);
  } catch {
    return null;
  }
}

function setLastSessionId(id: string | null): void {
  try {
    if (id) localStorage.setItem(LAST_SESSION_KEY, id);
    else localStorage.removeItem(LAST_SESSION_KEY);
  } catch {
    // 忽略
  }
}

function formatSessionDate(value?: string | null): string {
  if (!value) return "刚刚";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return date.toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export class SessionController {
  private listEl: HTMLElement | null;
  private pollTimer: number | null = null;
  private disposed = false;
  private sessionLoadSeq = 0;
  private replayHandler: ((events: Array<Record<string, unknown>>) => void) | null = null;
  private runningSnapshot: { workflowHTML: string; monitorHTML: string; reportHTML: string } | null = null;

  private unsubscribeCache: (() => void) | null = null;
  private unsubscribeStore: (() => void) | null = null;

  private readonly onLoadSessions = () => {
    historyCache.invalidate();
    void this.loadSessions();
  };

  private readonly onListClick = (event: Event) => {
    const target = event.target as HTMLElement;
    if (target.closest('[data-action="retry-sessions"]')) {
      void this.loadSessions(true);
      return;
    }
    const renameBtn = target.closest<HTMLElement>('[data-action="rename-session"]');
    if (renameBtn?.dataset.sessionId) {
      event.stopPropagation();
      void this.rename(renameBtn.dataset.sessionId, renameBtn.dataset.sessionName || "");
      return;
    }
    const deleteBtn = target.closest<HTMLElement>('[data-action="delete-session"]');
    if (deleteBtn?.dataset.sessionId) {
      event.stopPropagation();
      void this.remove(deleteBtn.dataset.sessionId);
      return;
    }
    const item = target.closest<HTMLElement>(".session-item[data-session-id]");
    if (item?.dataset.sessionId) void this.loadSession(item.dataset.sessionId);
  };

  private readonly onLoadSession = (event: Event) => {
    const sid = (event as CustomEvent).detail as string;
    if (sid) void this.loadSession(sid);
  };

  private readonly onReturnNewWorkspace = () => {
    this.returnToNewWorkspace();
  };

  constructor(listEl: HTMLElement | null) {
    this.listEl = listEl;
  }

  setReplayHandler(handler: (events: Array<Record<string, unknown>>) => void): void {
    this.replayHandler = handler;
  }

  init(): void {
    window.addEventListener("dc:load-sessions", this.onLoadSessions);
    window.addEventListener("dc:load-session", this.onLoadSession);
    window.addEventListener("dc:return-new-workspace", this.onReturnNewWorkspace);
    this.listEl?.addEventListener("click", this.onListClick);
    this.unsubscribeCache = historyCache.subscribe(() => this.renderSessions());
    this.unsubscribeStore = useAppStore.subscribe((state, previous) => {
      if (state.projectRoot !== previous.projectRoot) void this.loadSessions();
      else if (state.sessionId !== previous.sessionId || state.runningSessionId !== previous.runningSessionId) this.renderSessions();
    });
    void this.loadSessions();
    void this.showLastSessionReminder();
  }

  dispose(): void {
    this.disposed = true;
    this.stopPolling();
    window.removeEventListener("dc:load-sessions", this.onLoadSessions);
    window.removeEventListener("dc:load-session", this.onLoadSession);
    window.removeEventListener("dc:return-new-workspace", this.onReturnNewWorkspace);
    this.listEl?.removeEventListener("click", this.onListClick);
    this.unsubscribeCache?.();
    this.unsubscribeStore?.();
  }

  async loadSessions(force = false): Promise<void> {
    if (!this.listEl || this.disposed) return;
    const { projectRoot } = useAppStore.getState();
    const pending = historyCache.load(projectRoot, force);
    this.renderSessions();
    await pending;
    if (!this.disposed && useAppStore.getState().projectRoot === projectRoot) this.renderSessions();
  }

  private renderSessions(): void {
    if (!this.listEl || this.disposed) return;
    const { projectRoot, sessionId, runningSessionId } = useAppStore.getState();
    const { sessions, error, pending } = historyCache.snapshot(projectRoot);
    this.listEl.setAttribute("aria-busy", String(Boolean(pending)));
    const retry = '<button type="button" class="btn-secondary btn-small" data-action="retry-sessions">重试</button>';
    const status = error
      ? `<div class="error-state" role="status"><span>${sessions !== null ? "刷新失败，已保留历史记录" : "历史记录加载失败"}</span><div>${retry}</div><small>${escapeHtml(error)}</small></div>`
      : pending && sessions !== null
        ? '<div class="loading-state" role="status">正在刷新历史记录…</div>'
        : "";
    if (sessions === null) {
      this.listEl.innerHTML = status || '<div class="loading-state" role="status">正在加载历史记录…</div>';
      return;
    }
    if (!sessions.length) {
      this.listEl.innerHTML = status + '<div class="empty-state">暂无历史会话</div>';
      return;
    }
    const lastSessionId = getLastSessionId();
    this.listEl.innerHTML = status + sessions
        .map((session) => {
          const isActive = session.session_id === sessionId;
          const isLast = session.session_id === lastSessionId;
          const isRunning = session.session_id === runningSessionId || session.status === "running";
          const classes = ["session-item"];
          if (isActive) classes.push("active");
          if (isLast && !isRunning && !isActive) classes.push("recent");
          if (isRunning) classes.push("running");
          const displayName = session.name || (session.session_id ? session.session_id.replace("sess_", "会话 ") : "未命名会话");
          let badge = "";
          if (isRunning) badge = '<span class="session-badge running">进行中</span>';
          else if (isActive) badge = '<span class="session-badge active">当前</span>';
          else if (isLast) badge = '<span class="session-badge">上次</span>';
          const icon = isRunning
            ? '<div class="spinner-small" style="width:20px;height:20px;border-width:2px;"></div>'
            : getIcon("clock");
          return `<div class="${classes.join(" ")}" data-session-id="${escapeHtml(session.session_id)}">
            <div class="session-icon">${icon}</div>
            <div class="session-info">
              <span class="session-title" title="${escapeHtml(session.name || session.session_id)}">${escapeHtml(displayName)}${badge}</span>
              <span class="session-date">${escapeHtml(formatSessionDate(session.updated_at))}</span>
            </div>
            <div class="session-actions">
              <button class="icon-btn-small rename-btn" title="重命名" data-action="rename-session" data-session-id="${escapeHtml(session.session_id)}" data-session-name="${escapeHtml(session.name || "")}">${getIcon("edit")}</button>
              <button class="icon-btn-small delete-btn" title="删除" data-action="delete-session" data-session-id="${escapeHtml(session.session_id)}">${getIcon("trash")}</button>
            </div>
          </div>`;
        })
        .join("");
  }

  private async showLastSessionReminder(): Promise<void> {
    if (this.disposed) return;
    const messageContainer = document.getElementById("messageContainer");
    if (!messageContainer) return;
    if (useAppStore.getState().sessionId) return;
    if (document.getElementById("lastSessionReminderCard")) return;
    const lastSessionId = getLastSessionId();
    if (!lastSessionId) return;

    try {
      const detail = await getSessionDetailRaw(lastSessionId);
      if (!detail?.summary) {
        setLastSessionId(null);
        return;
      }
      const updatedAt = detail.summary.updated_at;
      if (updatedAt && Date.now() - new Date(updatedAt).getTime() > 48 * 60 * 60 * 1000) {
        setLastSessionId(null);
        return;
      }
      const messages = await getMessages(lastSessionId);
      if (messages.some((message) => message.role === "assistant" && message.content)) {
        setLastSessionId(null);
        return;
      }
      const runId = detail.latest_run?.id ?? detail.summary.latest_run_id ?? null;
      const events = runId ? await getEvents(lastSessionId, runId) : [];
      if (!events.length) return;

      const card = document.createElement("div");
      card.id = "lastSessionReminderCard";
      card.className = "session-reminder-card";
      card.innerHTML = `
        <div class="reminder-icon">${getIcon("clock")}</div>
        <div class="reminder-info">
          <div class="reminder-title">检测到上次未完成的审查</div>
          <div class="reminder-meta">${escapeHtml(detail.summary.name || lastSessionId)}${updatedAt ? ` · ${escapeHtml(formatSessionDate(updatedAt))}` : ""}</div>
        </div>
        <div class="reminder-actions">
          <button class="btn-primary btn-small reminder-continue" type="button">继续</button>
          <button class="btn-secondary btn-small reminder-dismiss" type="button">忽略</button>
        </div>
      `;
      card.querySelector(".reminder-continue")?.addEventListener("click", () => void this.loadSession(lastSessionId));
      card.querySelector(".reminder-dismiss")?.addEventListener("click", () => {
        card.remove();
        setLastSessionId(null);
      });
      messageContainer.prepend(card);
    } catch {
      // 旧版静默
    }
  }

  async loadSession(sessionId: string): Promise<void> {
    if (this.disposed) return;
    const loadSeq = ++this.sessionLoadSeq;
    const store = useAppStore.getState();
    const runningId = store.runningSessionId;
    let expectedRunId = store.runId;
    const isCurrent = () => !this.disposed && loadSeq === this.sessionLoadSeq &&
      useAppStore.getState().sessionId === sessionId && useAppStore.getState().runId === expectedRunId;

    // 点击正在运行的任务会话：恢复运行中的 UI，而不是按历史会话重放。
    if (runningId && runningId === sessionId) {
      this.stopPolling();
      store.setActivePage("review");
      store.setSessionId(sessionId);
      store.setViewingHistory(false);
      store.setLayoutState("completed");
      this.restoreRunningSnapshot();
      showToast("已返回正在进行的审查任务", "info");
      this.startPolling(sessionId);
      return;
    }

    // 运行中切到其它历史会话前，先保存运行中的面板内容。
    if (runningId && runningId !== sessionId) this.saveRunningSnapshot();

    this.stopPolling();
    store.setActivePage("review");
    store.setSessionId(sessionId);
    setLastSessionId(sessionId);
    document.getElementById("lastSessionReminderCard")?.remove();

    try {
      const detail = await getSessionDetailRaw(sessionId);
      if (!isCurrent()) return;
      if (!detail?.summary) throw new Error("session_not_found");
      const projectRoot = detail.summary.project_root ?? null;
      const runId = detail.latest_run?.id ?? detail.summary.latest_run_id ?? null;
      const [messages, events] = await Promise.all([
        getMessages(sessionId),
        runId ? getEvents(sessionId, runId) : Promise.resolve([]),
      ]);
      if (!isCurrent()) return;
      // 数据齐备且仍属于当前选择时，再一起更新项目、运行标识和面板。
      if (projectRoot) store.setProjectRoot(projectRoot);
      expectedRunId = runId;
      store.setRunId(runId);
      const assistantMessages = [...messages].reverse().filter((message) =>
        message.role === "assistant" && message.content && (!runId || !message.run_id || message.run_id === runId)
      );
      const report = assistantMessages.find((message) => message.metadata?.kind === "final_report")
        ?? assistantMessages.find((message) => message.metadata?.channel !== "qa");

      const messageContainer = document.getElementById("messageContainer");
      if (messageContainer) {
        messageContainer.innerHTML = `
          <div class="message system-message">
            <div class="avatar">${getIcon("bot")}</div>
            <div class="content"><p>准备好审查您的代码，请选择一个项目文件夹开始。</p></div>
          </div>
        `;
      }

      const hasEvents = (detail.workflow_events?.length ?? 0) > 0 || events.length > 0;

      // 历史会话只回放 workflow，日志面板保持为空；先清掉上一轮/上一会话残留。
      const workflowEntries = document.getElementById("workflowEntries");
      if (workflowEntries) workflowEntries.innerHTML = "";
      resetMonitorPanel(document);

      const reportContainer = document.getElementById("reportContainer");
      if (report?.content) {
        if (reportContainer) {
          delete (reportContainer as HTMLElement).dataset.reportPlaceholder;
          (reportContainer as HTMLElement).dataset.rawMarkdown = report.content;
          reportContainer.innerHTML = renderMarkdown(report.content);
        }
        store.setLayoutState("completed");
      } else if (hasEvents) {
        // 有 workflow 但没有最终报告：只显示 hero 占位，不残留上一次的报告。
        store.setLayoutState("completed");
        renderReportPlaceholder(reportContainer);
      } else {
        store.setLayoutState("initial");
      }

      if (workflowEntries && events.length > 0) {
        window.dispatchEvent(new CustomEvent("dc:replay-events", { detail: flattenEvents(events) }));
      }
      store.setViewingHistory(detail.latest_run?.status !== "running");
      window.dispatchEvent(new CustomEvent("dc:load-sessions"));
    } catch (error) {
      if (!isCurrent()) return;
      const message = error instanceof Error ? error.message : String(error);
      showToast(`加载会话失败: ${message}`, "error");
    }
  }

  async rename(sessionId: string, oldName: string): Promise<void> {
    const newName = window.prompt("请输入新的会话名称:", oldName);
    if (!newName || newName === oldName) return;
    try {
      await renameSession(sessionId, newName);
      historyCache.invalidate((sessions) => sessions.map((session) => session.session_id === sessionId ? { ...session, name: newName } : session));
      await this.loadSessions();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      showToast(`重命名失败: ${message}`, "error");
    }
  }

  async remove(sessionId: string): Promise<void> {
    if (!window.confirm("确定要删除此会话吗？此操作无法撤销。")) return;
    try {
      await deleteSession(sessionId);
      historyCache.invalidate((sessions) => sessions.filter((session) => session.session_id !== sessionId));
      if (getLastSessionId() === sessionId) {
        setLastSessionId(null);
        document.getElementById("lastSessionReminderCard")?.remove();
      }
      const store = useAppStore.getState();
      // 与旧版 endReviewTask 对齐：删除的正是运行中的会话时结束任务状态。
      if (store.runningSessionId === sessionId) {
        window.dispatchEvent(new CustomEvent("dc:cancel-review", { detail: sessionId }));
        store.setRunningSessionId(null);
      }
      if (store.sessionId === sessionId) {
        this.stopPolling();
        store.setSessionId(null);
        store.setLayoutState("initial");
        store.setViewingHistory(false);
        this.resetWorkspace();
      }
      await this.loadSessions();
      window.setTimeout(() => showToast("会话已删除", "success"), 0);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      showToast(`删除失败: ${message}`, "error");
    }
  }

  returnToNewWorkspace(): void {
    this.sessionLoadSeq += 1;
    const store = useAppStore.getState();
    if (store.runningSessionId) {
      showToast("审查任务继续在后台运行，可从历史记录返回", "info");
    }
    this.stopPolling();
    store.setSessionId(null);
    store.setLayoutState("initial");
    store.setViewingHistory(false);
    this.resetWorkspace();
    store.setHistoryDrawerOpen(false);
    window.dispatchEvent(new CustomEvent("dc:load-sessions"));
  }

  private resetWorkspace(): void {
    const messageContainer = document.getElementById("messageContainer");
    if (messageContainer) {
      messageContainer.innerHTML = `
        <div class="message system-message instant">
          <div class="avatar">${getIcon("bot")}</div>
          <div class="content"><p>准备好审查您的代码，请选择一个项目文件夹开始。</p></div>
        </div>
      `;
    }
    // 与旧版 clearReviewPanels + resetProgress 对齐：报告区回 hero，进度回 pending。
    resetProgress(document);
    const scanner = document.getElementById("scannerWorkflowSection");
    if (scanner) scanner.style.display = "none";
  }

  private saveRunningSnapshot(): void {
    const workflowEntries = document.getElementById("workflowEntries");
    const monitorContent = document.getElementById("monitorContent");
    const reportContainer = document.getElementById("reportContainer");
    this.runningSnapshot = {
      workflowHTML: workflowEntries ? workflowEntries.innerHTML : "",
      monitorHTML: monitorContent ? monitorContent.innerHTML : "",
      reportHTML: reportContainer ? reportContainer.innerHTML : "",
    };
  }

  private restoreRunningSnapshot(): void {
    if (!this.runningSnapshot) return;
    const workflowEntries = document.getElementById("workflowEntries");
    const monitorContent = document.getElementById("monitorContent");
    const reportContainer = document.getElementById("reportContainer");
    if (workflowEntries && this.runningSnapshot.workflowHTML) {
      workflowEntries.innerHTML = this.runningSnapshot.workflowHTML;
    }
    if (monitorContent && this.runningSnapshot.monitorHTML) {
      monitorContent.innerHTML = this.runningSnapshot.monitorHTML;
    }
    if (reportContainer && this.runningSnapshot.reportHTML) {
      delete (reportContainer as HTMLElement).dataset.reportPlaceholder;
      reportContainer.innerHTML = this.runningSnapshot.reportHTML;
    }
  }

  private startPolling(sessionId: string): void {
    this.stopPolling();
    this.pollTimer = window.setInterval(async () => {
      try {
        const status = await getSessionStatus(sessionId);
        if (status.completed) {
          this.stopPolling();
          await this.loadSession(sessionId);
        }
      } catch {
        this.stopPolling();
      }
    }, 3000);
  }

  private stopPolling(): void {
    if (this.pollTimer) window.clearInterval(this.pollTimer);
    this.pollTimer = null;
  }
}
