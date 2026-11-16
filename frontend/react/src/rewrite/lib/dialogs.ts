import type { ConfirmDialogOptions } from "../types";
import { escapeHtml } from "./html";

/**
 * 1:1 复刻 legacy/rule-growth.js:showConfirmDialog。
 * 旧版直接创建 body 级 DOM，这里保持同样做法，避免 React Portal 改变层级。
 */
export function showConfirmDialog(options: ConfirmDialogOptions): void {
  const existingDialog = document.getElementById("confirmDialog");
  if (existingDialog) existingDialog.remove();

  const dialog = document.createElement("div");
  dialog.id = "confirmDialog";
  dialog.className = "modal-overlay";

  const showCloseBtn = options.showCloseButton !== false;
  const showCancelBtn = options.showCancel !== false;

  dialog.innerHTML = `
    <div class="modal-container confirm-dialog-container">
      <div class="modal-header">
        <h3>${escapeHtml(options.title || "确认")}</h3>
        ${
          showCloseBtn
            ? `<button class="icon-btn modal-close-btn" id="confirmDialogCloseBtn">
                 <svg class="icon"><use href="#icon-x"></use></svg>
               </button>`
            : ""
        }
      </div>
      <div class="modal-body">
        ${options.content || ""}
      </div>
      <div class="modal-footer">
        ${showCancelBtn ? `<button class="btn-secondary" id="confirmDialogCancelBtn">${escapeHtml(options.cancelText || "取消")}</button>` : ""}
        <button class="btn-primary" id="confirmDialogBtn">${escapeHtml(options.confirmText || "确认")}</button>
      </div>
    </div>
  `;

  document.body.appendChild(dialog);

  const closeWithCancel = () => {
    closeConfirmDialog();
    options.onCancel?.();
  };

  document.getElementById("confirmDialogCloseBtn")?.addEventListener("click", closeWithCancel);
  document.getElementById("confirmDialogCancelBtn")?.addEventListener("click", closeWithCancel);
  document.getElementById("confirmDialogBtn")?.addEventListener("click", () => {
    closeConfirmDialog();
    options.onConfirm?.();
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeWithCancel();
  });
}

export function closeConfirmDialog(): void {
  document.getElementById("confirmDialog")?.remove();
}

/**
 * 1:1 复刻 legacy/rule-growth.js:showHelpDialog，含滚动高亮与 ESC 关闭。
 */
export function showHelpDialog(title: string, content: string): void {
  document.getElementById("help-dialog-overlay")?.remove();

  const dialogHtml = `
    <div id="help-dialog-overlay" class="dialog-overlay" data-action="close-help">
      <div class="dialog-box help-dialog" data-action="stop-propagation">
        <div class="dialog-header">
          <h3 class="dialog-title">
            <svg class="icon" style="margin-right: 0.5rem; color: var(--primary);">
              <use href="#icon-book"></use>
            </svg>
            ${escapeHtml(title)}
          </h3>
          <button class="dialog-close-btn" data-action="close-help" title="关闭">
            <svg class="icon"><use href="#icon-x"></use></svg>
          </button>
        </div>
        <div class="dialog-body" style="max-height: 70vh; overflow-y: auto;">
          ${content}
        </div>
        <div class="dialog-footer" style="text-align: right; padding-top: 1rem; border-top: 1px solid var(--border);">
          <button class="btn-primary" data-action="close-help">知了</button>
        </div>
      </div>
    </div>
  `;

  document.body.insertAdjacentHTML("beforeend", dialogHtml);
  const overlay = document.getElementById("help-dialog-overlay");
  overlay?.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    // 关闭按钮优先：旧版 X 与“知了”都在 .dialog-box 内部，不能被子元素拦截。
    if (target.closest('[data-action="close-help"]')) {
      closeHelpDialog();
      return;
    }
    if (target.closest('[data-action="stop-propagation"]')) return;
    closeHelpDialog();
  });

  const dialogBody = document.querySelector(".help-dialog .md-main");
  const navLinks = document.querySelectorAll(".md-nav-list a");
  const sections = document.querySelectorAll(".md-section");

  const handleScroll = () => {
    if (!dialogBody) return;
    let currentSectionId = "";
    const containerRect = dialogBody.getBoundingClientRect();
    const scrollTop = dialogBody.scrollTop;

    for (const section of Array.from(sections)) {
      const sectionRect = section.getBoundingClientRect();
      const relativeTop = sectionRect.top - containerRect.top;
      if (relativeTop <= 80) {
        currentSectionId = section.getAttribute("id") ?? "";
      }
    }

    if (dialogBody.scrollHeight - scrollTop <= dialogBody.clientHeight + 50) {
      const lastSection = sections[sections.length - 1];
      if (lastSection) currentSectionId = lastSection.getAttribute("id") ?? "";
    }

    if (!currentSectionId && sections.length > 0) {
      currentSectionId = sections[0].getAttribute("id") ?? "";
    }

    navLinks.forEach((link) => {
      link.classList.remove("active");
      if (link.getAttribute("href") === `#${currentSectionId}`) {
        link.classList.add("active");
      }
    });
  };

  if (dialogBody) {
    dialogBody.addEventListener("scroll", handleScroll);
    handleScroll();
  }

  const handleEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      closeHelpDialog();
      document.removeEventListener("keydown", handleEsc);
    }
  };
  document.addEventListener("keydown", handleEsc);
}

export function closeHelpDialog(): void {
  document.getElementById("help-dialog-overlay")?.remove();
}
