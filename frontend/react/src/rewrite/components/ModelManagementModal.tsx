import { createPortal } from "react-dom";

import { ModelServicesPanel } from "../features/settings/ModelServicesPanel";
import { XIcon } from "../features/settings/icons";
import { useAppStore } from "../state/appStore";

/**
 * Dashboard「配置服务商」入口。内容与设置 › 模型服务共用同一套面板，
 * 避免弹窗与设置页出现两套不一致的模型管理界面。
 */
export function ModelManagementModal() {
  const open = useAppStore((state) => state.modelManagementOpen);
  const setModelManagementOpen = useAppStore((state) => state.setModelManagementOpen);

  return createPortal(
    <div
      id="modelManagementModal"
      className="modal dc-settings-modal"
      style={{ display: open ? "flex" : "none" }}
      role="dialog"
      aria-modal="true"
      aria-label="模型服务"
      onClick={(event) => {
        if (event.target === event.currentTarget) setModelManagementOpen(false);
      }}
    >
      <div className="dc-settings-modal-card">
        <header className="dc-settings-modal-head">
          <strong>模型服务</strong>
          <button
            type="button"
            className="ds-icon-btn"
            title="关闭"
            onClick={() => setModelManagementOpen(false)}
          >
            <XIcon size={18} />
          </button>
        </header>
        <div className="dc-settings-modal-body">
          <ModelServicesPanel active={open} />
        </div>
      </div>
    </div>,
    document.body
  );
}
