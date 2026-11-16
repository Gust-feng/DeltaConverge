import { escapeHtml, getIcon } from "./html";

/**
 * 1:1 复刻 legacy/utils.js:showToast。
 * 旧版优先把消息写进 #messageContainer（即使聊天区当前被隐藏），
 * 只有该节点不存在时才创建浮层；浮层 class 也保留旧版的 toast-${type}。
 *
 * settings 页没有可见的消息区，传 `{ floating: true }` 强制使用右下角浮层，
 * 避免保存成功/失败的提示写进隐藏的聊天面板。
 */
export function showToast(
  message: string,
  type: "info" | "error" | "success" | "warning" = "info",
  options?: { floating?: boolean }
): void {
  const messageArea = options?.floating ? null : document.getElementById("messageContainer");
  if (messageArea) {
    const div = document.createElement("div");
    div.className = "message system-message instant";
    const iconName =
      type === "error" ? "x" : type === "success" ? "check" : type === "warning" ? "alert-triangle" : "bot";
    div.innerHTML = `
      <div class="avatar">${getIcon(iconName)}</div>
      <div class="message-body">
        <div class="content"><p>${escapeHtml(message)}</p></div>
      </div>
    `;
    messageArea.appendChild(div);
    messageArea.scrollTop = messageArea.scrollHeight;
    return;
  }

  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  let iconName = "bot";
  if (type === "error") iconName = "x";
  if (type === "success") iconName = "check";
  if (type === "warning") iconName = "alert-triangle";

  toast.innerHTML = `
    <div class="toast-icon">${getIcon(iconName)}</div>
    <div class="toast-content">${escapeHtml(message)}</div>
    <div class="toast-close">${getIcon("x")}</div>
  `;

  const closeBtn = toast.querySelector(".toast-close");
  if (closeBtn) {
    (closeBtn as HTMLElement).onclick = () => {
      toast.classList.add("hiding");
      toast.addEventListener("animationend", () => toast.remove());
    };
  }

  container.appendChild(toast);

  window.setTimeout(() => {
    if (toast.isConnected) {
      toast.classList.add("hiding");
      toast.addEventListener("animationend", () => toast.remove());
    }
  }, 5000);
}
