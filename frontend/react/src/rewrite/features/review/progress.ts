import { escapeHtml } from "../../lib/html";

export type StepName = "init" | "analysis" | "planning" | "reviewing" | "reporting";
export type StepStatus = "pending" | "active" | "completed" | "error";

export const HERO_HTML = `
  <div class="empty-state">
    <div class="hero-animation" style="display:flex;">
      <svg class="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
        <path class="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" stroke-width="0.8"></path>
        <path class="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" stroke-width="1.2"></path>
        <circle class="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" stroke-width="1.5"></circle>
        <line class="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" stroke-width="1"></line>
        <line class="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" stroke-width="1"></line>
      </svg>
      <div class="hero-project-name" data-text="DeltaConverge">DeltaConverge</div>
    </div>
  </div>
`;

export function renderReportPlaceholder(container: HTMLElement | null): void {
  if (!container) return;
  if (container.dataset.reportPlaceholder === "hero") return;
  container.dataset.reportPlaceholder = "hero";
  container.innerHTML = HERO_HTML;
}

export function updateStepData(stepElement: HTMLElement, data: unknown): void {
  const dataEl = stepElement.querySelector(".step-data") as HTMLElement | null;
  if (!dataEl) return;
  if (typeof data === "string") {
    dataEl.textContent = data;
    return;
  }
  if (data && typeof data === "object") {
    let html = "";
    for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
      html += `<span class="data-item"><span class="data-key">${escapeHtml(key)}:</span> ${escapeHtml(String(value))}</span>`;
    }
    dataEl.innerHTML = html;
  }
}

export function setProgressStep(root: ParentNode, stepName: StepName, status: StepStatus, data?: unknown): void {
  const stepEl = root.querySelector<HTMLElement>(`.step-item[data-step="${stepName}"]`);
  if (!stepEl) return;
  if (!stepEl.classList.contains(status)) {
    stepEl.classList.remove("pending", "active", "completed", "error");
    stepEl.classList.add(status);
  }
  if (data !== undefined && data !== null) updateStepData(stepEl, data);
}

export function resetProgressSteps(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>(".step-item").forEach((step) => {
    step.classList.remove("active", "completed", "error");
    step.classList.add("pending");
  });
}

export function markAllStepsCompleted(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>(".step-item").forEach((step) => {
    step.classList.remove("pending", "active", "error");
    step.classList.add("completed");
  });
}

export function resetMonitorPanel(root: ParentNode): void {
  const monitorPanel = root.querySelector<HTMLElement>("#monitorPanel");
  if (monitorPanel) {
    monitorPanel.classList.remove("ok", "error");
    const titleEl = monitorPanel.querySelector<HTMLElement>(".panel-title");
    if (titleEl) titleEl.textContent = "日志";
  }
  const monitorContent = root.querySelector<HTMLElement>("#monitorContent");
  if (monitorContent) monitorContent.innerHTML = "";
  // 停掉并清空上一轮的计时，避免新会话/历史会话沿用旧用时。
  const timerEl = root.querySelector<HTMLElement>("#reviewTimer");
  if (timerEl) {
    const timerId = timerEl.dataset.timerId;
    if (timerId) window.clearInterval(Number(timerId));
    delete timerEl.dataset.timerId;
    delete timerEl.dataset.startedAt;
    timerEl.textContent = "";
  }
}

export function resetProgress(root: ParentNode): void {
  resetProgressSteps(root);
  const workflowEntries = root.querySelector<HTMLElement>("#workflowEntries");
  if (workflowEntries) workflowEntries.innerHTML = "";
  // 与旧版 handleSSEResponse 初始化对齐：清空日志内容并复位 ok/error 与标题。
  resetMonitorPanel(root);
  const reportContainer = root.querySelector<HTMLElement>("#reportContainer");
  if (reportContainer) renderReportPlaceholder(reportContainer);
}

export function startReviewTimer(root: ParentNode): void {
  stopReviewTimer(root);
  const timerEl = root.querySelector<HTMLElement>("#reviewTimer");
  if (!timerEl) return;
  const startedAt = Date.now();
  timerEl.dataset.startedAt = String(startedAt);
  timerEl.textContent = "00:00";
  const interval = window.setInterval(() => {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    timerEl.textContent = `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }, 1000);
  timerEl.dataset.timerId = String(interval);
}

export function stopReviewTimer(root: ParentNode): void {
  const timerEl = root.querySelector<HTMLElement>("#reviewTimer");
  if (!timerEl) return;
  const timerId = timerEl.dataset.timerId;
  if (timerId) window.clearInterval(Number(timerId));
  delete timerEl.dataset.timerId;
  const startedAt = Number(timerEl.dataset.startedAt || 0);
  if (startedAt) {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    timerEl.textContent = `总用时 ${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
}

export function toggleMonitorPanel(root: ParentNode): void {
  root.querySelector("#monitorPanel")?.classList.toggle("collapsed");
}

export function triggerCompletionTransition(root: ParentNode, jobAlreadySwitched: boolean): void {
  markAllStepsCompleted(root);
  if (!jobAlreadySwitched) {
    // 布局切换由控制器负责，这里只保留步骤完成
  }
}
