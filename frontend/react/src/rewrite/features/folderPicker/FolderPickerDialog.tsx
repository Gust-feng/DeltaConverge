import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Icon } from "../../components/Icon";
import { getSystemEnv, listDirectory, pickFolder } from "../../lib/api";
import { showConfirmDialog } from "../../lib/dialogs";
import { showToast } from "../../lib/toast";
import { useAppStore } from "../../state/appStore";
import { checkGitRepository, prefetchGitCheck } from "./gitCheck";
import { buildNotGitRepoWarning, GitSubdirWarningDialog } from "./warnings";

type DirectoryItem = {
  name: string;
  path: string;
  is_dir: boolean;
};

type ListView =
  | { kind: "loading" }
  | { kind: "message"; text: string }
  | { kind: "error"; text: string }
  | { kind: "items"; items: DirectoryItem[] };

type SubdirWarning = {
  path: string;
  gitRoot: string;
};

export function FolderPickerDialog() {
  // 打开瞬间的 currentProjectRoot 快照；后续 store 变化不重算初始路径。
  const initialProjectRootRef = useRef(useAppStore.getState().projectRoot);
  const setProjectRoot = useAppStore((state) => state.setProjectRoot);
  const setFolderPickerOpen = useAppStore((state) => state.setFolderPickerOpen);

  const [pathInput, setPathInput] = useState("");
  const [view, setView] = useState<ListView>({ kind: "loading" });
  const [loading, setLoading] = useState(false);
  const [selectChecking, setSelectChecking] = useState(false);
  const [nativeStatus, setNativeStatus] = useState<"idle" | "picking" | "checking">("idle");
  const [subdirWarning, setSubdirWarning] = useState<SubdirWarning | null>(null);

  const currentPathRef = useRef("");
  const requestSeqRef = useRef(0);

  const loadDirectory = useCallback(async (path: string) => {
    const seq = ++requestSeqRef.current;
    setLoading(true);

    try {
      const data = await listDirectory(path);
      if (seq !== requestSeqRef.current) return;

      if (data.error) {
        setView({ kind: "message", text: String(data.error) });
        return;
      }

      const resolvedPath = data.path || path;
      currentPathRef.current = resolvedPath;
      setPathInput(resolvedPath || "");

      const children = data.children ?? [];
      if (children.length === 0) {
        setView({ kind: "message", text: "空目录" });
        return;
      }

      setView({ kind: "items", items: children });
    } catch (error) {
      if (seq !== requestSeqRef.current) return;
      const message = error instanceof Error ? error.message : String(error);
      setView({ kind: "error", text: message });
    } finally {
      if (seq === requestSeqRef.current) {
        setLoading(false);
        // 预检查当前目录是否为 Git 仓库（静默，不阻塞 UI）。
        prefetchGitCheck(currentPathRef.current);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      let env: Record<string, unknown> = {};
      try {
        env = await getSystemEnv();
      } catch {
        // 旧版同样静默忽略 env 读取失败
      }
      if (cancelled) return;

      const defaultRoot =
        typeof env.default_project_root === "string" ? env.default_project_root : "";
      const initialPath = initialProjectRootRef.current || defaultRoot || "";
      currentPathRef.current = initialPath;
      setPathInput(initialPath);
      void loadDirectory(initialPath);
    })();

    return () => {
      cancelled = true;
      // 使在途请求失效，避免卸载后继续写入状态。
      requestSeqRef.current += 1;
    };
  }, [loadDirectory]);

  function close() {
    setFolderPickerOpen(false);
  }

  function completeSelection(
    selectedPath: string,
    message: string,
    messageType: "success" | "warning"
  ) {
    setProjectRoot(selectedPath);
    showToast(message, messageType);
    close();
  }

  function showNotGitRepoWarning(path: string) {
    showConfirmDialog({
      title: "非 Git 仓库",
      content: buildNotGitRepoWarning(path),
      confirmText: "仍然选择",
      cancelText: "重新选择",
      showCloseButton: true,
      onConfirm: () => {
        completeSelection(path, `已选择: ${path} (非 Git 仓库)`, "warning");
      },
      onCancel: () => {
        // 保持文件夹选择器打开
      },
    });
  }

  async function runSelectionFlow(targetPath: string) {
    const result = await checkGitRepository(targetPath);

    if (!result.isGit) {
      showNotGitRepoWarning(targetPath);
      return;
    }

    if (!result.isRoot && result.gitRoot) {
      setSubdirWarning({ path: targetPath, gitRoot: result.gitRoot });
      return;
    }

    completeSelection(targetPath, `已选择: ${targetPath}`, "success");
  }

  async function handleSelectCurrent() {
    const selectedPath = currentPathRef.current;
    if (!selectedPath) return;

    setSelectChecking(true);
    try {
      await runSelectionFlow(selectedPath);
    } finally {
      setSelectChecking(false);
    }
  }

  async function handleNativePick() {
    setNativeStatus("picking");
    try {
      const data = await pickFolder();

      if (data.error) {
        showToast(`系统选择器失败: ${data.error}`, "error");
        return;
      }

      if (!data.path) return;

      setPathInput(data.path);
      setNativeStatus("checking");
      await runSelectionFlow(data.path);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      showToast(`系统选择器失败: ${message}`, "error");
    } finally {
      setNativeStatus("idle");
    }
  }

  function handleGo() {
    void loadDirectory(pathInput);
  }

  function handleUp() {
    // 与旧版一致：以输入框当前值为基准，而不是 currentPath。
    let path = pathInput || "";
    if (!path) return;

    path = path.replace(/[\\/]+$/, "");
    const isWindowsPath = path.includes("\\") && !path.includes("/");
    const separator = isWindowsPath ? "\\" : "/";
    const index = path.lastIndexOf(separator);

    if (index <= 0) {
      void loadDirectory(path);
      return;
    }

    let parent = path.slice(0, index);
    if (isWindowsPath && parent.length <= 2) parent = parent + "\\";
    void loadDirectory(parent);
  }

  function handleDrillInto(name: string) {
    const base = currentPathRef.current;
    const separator = base.includes("\\") && !base.includes("/") ? "\\" : "/";
    const nextPath = (base ? base.replace(/[\\/]+$/, "") + separator : "") + name;
    void loadDirectory(nextPath);
  }

  function handleSubdirContinue() {
    const warning = subdirWarning;
    if (!warning) return;
    setSubdirWarning(null);
    completeSelection(warning.path, `已选择子目录: ${warning.path}`, "warning");
  }

  function handleSubdirUseRoot() {
    const warning = subdirWarning;
    if (!warning) return;
    setSubdirWarning(null);
    completeSelection(warning.gitRoot, `已选择项目根目录: ${warning.gitRoot}`, "success");
  }

  return (
    <>
      {createPortal(
        <div
          id="folderPickerDialog"
          className="modal-overlay"
          onClick={(event) => {
            if (event.target === event.currentTarget) close();
          }}
        >
          <div className="modal-container folder-picker-container">
            <div className="modal-header">
              <h3>选择项目文件夹</h3>
              <button type="button" className="close-btn" onClick={close}>
                <Icon name="x" />
              </button>
            </div>
            <div className="modal-body">
              <div className="picker-toolbar">
                <input
                  type="text"
                  id="folderPathInput"
                  className="picker-path-input bare-input"
                  placeholder="输入路径或浏览..."
                  value={pathInput}
                  onChange={(event) => setPathInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void loadDirectory(pathInput);
                  }}
                />
                <div className="picker-actions">
                  <button type="button" className="btn-secondary" id="folderGoBtn" onClick={handleGo}>
                    前往
                  </button>
                  <button type="button" className="btn-secondary" id="folderUpBtn" onClick={handleUp}>
                    <Icon name="arrow-up" /> 上级
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    id="nativePickerBtn"
                    onClick={() => void handleNativePick()}
                    disabled={nativeStatus !== "idle"}
                  >
                    {nativeStatus === "picking" ? (
                      "选择中..."
                    ) : nativeStatus === "checking" ? (
                      "检查中..."
                    ) : (
                      <>
                        <Icon name="folder" /> 系统选择器
                      </>
                    )}
                  </button>
                </div>
              </div>
              <div
                className={`file-list${loading ? " loading" : ""}`}
                id="folderListContainer"
              >
                {view.kind === "loading" ? <div className="empty-state">加载中...</div> : null}
                {view.kind === "message" ? <div className="empty-state">{view.text}</div> : null}
                {view.kind === "error" ? <div className="error-state">{view.text}</div> : null}
                {view.kind === "items"
                  ? view.items.map((item, index) => (
                      <div
                        key={`${item.path}-${index}`}
                        className="file-list-item"
                        data-name={item.name}
                        onClick={() => handleDrillInto(item.name)}
                      >
                        <Icon name="folder" />
                        <span>{item.name}</span>
                      </div>
                    ))
                  : null}
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={close}>
                取消
              </button>
              <button
                type="button"
                className="btn-primary"
                id="selectFolderBtn"
                onClick={() => void handleSelectCurrent()}
                disabled={selectChecking}
              >
                {selectChecking ? "检查中..." : "选择当前文件夹"}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {subdirWarning
        ? createPortal(
            <GitSubdirWarningDialog
              path={subdirWarning.path}
              gitRoot={subdirWarning.gitRoot}
              onCancel={() => setSubdirWarning(null)}
              onContinue={handleSubdirContinue}
              onUseRoot={handleSubdirUseRoot}
            />,
            document.body
          )
        : null}
    </>
  );
}
