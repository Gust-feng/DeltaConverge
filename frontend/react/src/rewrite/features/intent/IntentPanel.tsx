import { Fragment, useEffect, useRef, useState } from "react";

import { Icon } from "../../components/Icon";
import { analyzeIntentStream, getIntent, updateIntent } from "../../lib/api";
import { escapeHtml } from "../../lib/html";
import { showToast } from "../../lib/toast";
import { availableModel, reconcileModel, modelCapabilityLabel } from "../../lib/modelSelection";
import { getProjectName, useAppStore } from "../../state/appStore";
import type { IntentRecord, ModelGroup } from "../../types";

type IntentLoadRecord = IntentRecord & { response?: { content?: unknown } };

function renderMarkdownHtml(text: string, wrapFallback: boolean): string {
  const marked = typeof window !== "undefined" ? window.marked : undefined;
  if (marked && typeof marked.parse === "function") {
    return marked.parse(text);
  }
  return wrapFallback ? `<div class="intent-text">${escapeHtml(text)}</div>` : escapeHtml(text);
}

function IntentModelDropdown({
  groups,
  selectedModel,
  selectedLabel,
  onSelect,
}: {
  groups: ModelGroup[];
  selectedModel: string;
  selectedLabel: string;
  onSelect: (model: string, label: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handleDocumentClick = (event: MouseEvent) => {
      const root = rootRef.current;
      if (root && root.classList.contains("open") && !root.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, [open]);

  return (
    <div
      ref={rootRef}
      className={`custom-dropdown${open ? " open" : ""}`}
      id="intentModelDropdown"
      style={{ width: "200px" }}
    >
      <div
        className="dropdown-trigger"
        id="intentModelDropdownTrigger"
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        <span id="intentSelectedModelText">{selectedModel || selectedLabel ? selectedLabel : "请选择模型"}</span>
        <svg className="icon chevron">
          <use href="#icon-chevron-down" />
        </svg>
      </div>
      <div className="dropdown-menu" id="intentModelDropdownMenu">
        {groups.length === 0 ? <div className="dropdown-item" style={{ opacity: 0.5 }}>请先在设置中获取并保存模型</div> : null}
        {groups.map((group, groupIndex) => {
          const providerName = group.label || group.provider || "Unknown";
          const models = group.models || [];
          if (models.length === 0) return null;
          return (
            <Fragment key={`${group.provider}-${groupIndex}`}>
              <div className="dropdown-group-header">
                <span>{providerName}</span>
              </div>
              {models.map((model, modelIndex) => {
                const modelName = model.name || "";
                const modelLabel = model.label || model.name || "";
                const isAvailable = model.available !== false;
                return (
                  <div
                    className={`dropdown-item${selectedModel === modelName ? " selected" : ""}`}
                    data-value={modelName}
                    key={`${modelName}-${modelIndex}`}
                    style={isAvailable ? undefined : { opacity: 0.5, cursor: "not-allowed" }}
                    onClick={
                      isAvailable
                        ? () => {
                            onSelect(modelName, modelLabel);
                            setOpen(false);
                          }
                        : undefined
                    }
                  >
                    <span>{modelLabel}{modelCapabilityLabel(model.capabilities) ? ` · ${modelCapabilityLabel(model.capabilities)}` : ""}</span>
                  </div>
                );
              })}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}

export function IntentPanel({ projectRoot }: { projectRoot: string | null }) {
  const availableGroups = useAppStore((state) => state.availableGroups);

  const [selectedModel, setSelectedModel] = useState("");
  const [selectedLabel, setSelectedLabel] = useState("");

  const [thoughtDisplay, setThoughtDisplay] = useState<"none" | "block">("none");
  const [thoughtCollapsed, setThoughtCollapsed] = useState(false);
  const [thoughtStatus, setThoughtStatus] = useState("");
  const [thoughtText, setThoughtText] = useState("");

  const [viewDisplay, setViewDisplay] = useState<"block" | "none" | undefined>(undefined);
  const [emptyDisplay, setEmptyDisplay] = useState<"flex" | "none" | undefined>(undefined);
  const [textareaDisplay, setTextareaDisplay] = useState<"none" | "block">("none");
  const [actionsDisplay, setActionsDisplay] = useState<"none" | "flex">("none");

  const [markdown, setMarkdown] = useState("");
  const [renderedHtml, setRenderedHtml] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [editValue, setEditValue] = useState("");

  const contentRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const thoughtContentRef = useRef<HTMLDivElement>(null);
  const loadSeqRef = useRef(0);
  const previousRootRef = useRef<string | null | undefined>(undefined);
  const analyzingRef = useRef(false);

  useEffect(() => {
    const next = reconcileModel(availableGroups, selectedModel);
    setSelectedModel(next);
    setSelectedLabel(availableModel(availableGroups, next)?.label ?? "");
  }, [availableGroups, selectedModel]);

  // 项目变化时重新加载意图（loadIntentData）
  useEffect(() => {
    const previousRoot = previousRootRef.current;
    previousRootRef.current = projectRoot;
    const seq = ++loadSeqRef.current;

    if (!projectRoot) {
      if (previousRoot !== undefined) {
        setMarkdown("");
        setRenderedHtml("");
        setEmptyDisplay("flex");
        setViewDisplay("block");
        setThoughtDisplay("none");
      }
      return;
    }

    const projectName = getProjectName(projectRoot);
    void getIntent(projectRoot, projectName)
      .then((data) => {
        if (seq !== loadSeqRef.current) return;
        const record = data as IntentLoadRecord;
        let content = typeof record.content === "string" ? record.content : "";
        if (!content && record.response && typeof record.response.content === "string") {
          content = record.response.content;
        }
        if (content) {
          setMarkdown(content);
          setRenderedHtml(renderMarkdownHtml(content, true));
          setEmptyDisplay("none");
          setViewDisplay("block");
          setThoughtDisplay("none");
        } else {
          setMarkdown("");
          setRenderedHtml("");
          setEmptyDisplay("flex");
        }
      })
      .catch((error) => {
        if (seq !== loadSeqRef.current) return;
        const message = error instanceof Error ? error.message : String(error);
        const notFound = /404|intent_cache_not_found/i.test(message);
        // 旧版把 404（新项目尚无缓存）当作正常空态，不打 console.error。
        if (!notFound) {
          console.error("Load intent error:", error);
        } else {
          setMarkdown("");
        }
        setRenderedHtml("");
        setEmptyDisplay("flex");
      });
  }, [projectRoot]);

  useEffect(() => {
    const element = thoughtContentRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [thoughtText]);

  async function runAnalysis() {
    if (analyzingRef.current) return;
    if (!projectRoot) {
      showToast("请先选择项目文件夹", "error");
      return;
    }

    if (!availableModel(useAppStore.getState().availableGroups, selectedModel)) {
      showToast("请先在设置中获取并保存模型，然后选择可用模型。", "error", { floating: true });
      return;
    }

    analyzingRef.current = true;
    setAnalyzing(true);
    setEmptyDisplay("none");
    setViewDisplay("block");
    setRenderedHtml("");
    setThoughtDisplay("none");
    setThoughtText("");
    setThoughtStatus("");
    setThoughtCollapsed(false);

    let fullContent = "";
    let fullThought = "";
    let thoughtStarted = false;

    try {
      const modelToUse = selectedModel;
      if (!modelToUse) {
        showToast("请先在意图面板选择模型", "error");
        return;
      }

      await analyzeIntentStream(projectRoot, modelToUse, {
        onThought(content) {
          if (!thoughtStarted) {
            thoughtStarted = true;
            setThoughtDisplay("block");
            setThoughtCollapsed(false);
            setThoughtStatus("思考中...");
          }
          fullThought += content;
          setThoughtText(fullThought);
        },
        onChunk(content) {
          fullContent += content;
          setRenderedHtml(renderMarkdownHtml(fullContent, false));
        },
        onFinal(content) {
          if (content) {
            fullContent = content;
            setRenderedHtml(renderMarkdownHtml(fullContent, false));
          }
          if (fullThought) {
            setThoughtCollapsed(true);
            setThoughtStatus("已完成");
          }
        },
        onError(message) {
          showToast(`分析出错: ${message}`, "error");
        },
      });

      setMarkdown(fullContent);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("Intent Analysis Error:", error);
      showToast(`分析失败: ${message}`, "error");
      if (!fullContent) {
        setRenderedHtml(`<p class="error-text">分析失败: ${escapeHtml(message)}</p>`);
      }
    } finally {
      analyzingRef.current = false;
      setAnalyzing(false);
    }
  }

  function enterEditMode() {
    const fallback = contentRef.current ? contentRef.current.innerText : "";
    setEditValue(markdown || fallback);
    setViewDisplay("none");
    setTextareaDisplay("block");
    setActionsDisplay("flex");
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function cancelEditMode() {
    setViewDisplay("block");
    setTextareaDisplay("none");
    setActionsDisplay("none");
  }

  async function saveEdit() {
    const newContent = editValue;
    setMarkdown(newContent);
    setRenderedHtml(renderMarkdownHtml(newContent, false));

    cancelEditMode();

    if (projectRoot) {
      try {
        const result = await updateIntent(projectRoot, newContent);
        if (result.success) {
          showToast("意图已保存", "success");
        } else {
          showToast(`保存失败: ${result.error || "Unknown error"}`, "error");
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.error("Save intent error:", error);
        showToast(`保存请求失败: ${message}`, "error");
      }
    } else {
      showToast("未选择项目，仅本地更新", "warning");
    }
  }

  return (
    <div className="card" id="intent-panel" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <div className="card-header">
        <div className="header-title-group">
          <h3>项目意图分析</h3>
          <span id="intent-metadata" className="intent-metadata" style={{ display: "none" }} />
        </div>
        <div className="header-controls" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <IntentModelDropdown
            groups={availableGroups}
            selectedModel={selectedModel}
            selectedLabel={selectedLabel}
            onSelect={(model, label) => {
              setSelectedModel(model);
              setSelectedLabel(label);
            }}
          />
          <button
            className="btn-primary btn-small"
            id="intent-analyze-btn"
            onClick={() => void runAnalysis()}
            title="使用选定模型分析"
            disabled={analyzing}
          >
            {analyzing ? (
              <div className="spinner-small" />
            ) : (
              <>
                <svg className="icon">
                  <use href="#icon-bot" />
                </svg>
                <span>分析</span>
              </>
            )}
          </button>
          <button className="btn-secondary btn-small" id="intent-edit-btn" onClick={enterEditMode} title="编辑">
            <svg className="icon">
              <use href="#icon-edit" />
            </svg>
          </button>
        </div>
      </div>

      <div
        className="card-body intent-card-body"
        style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", padding: 0 }}
      >
        <div
          id="intent-thought-container"
          className={`intent-thought-container${thoughtCollapsed ? " collapsed" : ""}`}
          style={{ display: thoughtDisplay }}
        >
          <div
            className="thought-header"
            id="thought-header-toggle"
            style={{ cursor: "pointer" }}
            onClick={() => setThoughtCollapsed((value) => !value)}
          >
            <span>思考过程</span>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span id="thought-status">{thoughtStatus}</span>
              <svg
                className="chevron-icon"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>
          </div>
          <div id="intent-thought-content" className="thought-content" ref={thoughtContentRef}>
            {thoughtText}
          </div>
        </div>

        <div className="intent-content-wrapper" style={{ flex: 1, overflowY: "auto", padding: "1.5rem", minHeight: "60vh" }}>
          <div id="intent-view" className="markdown-body" style={viewDisplay ? { display: viewDisplay } : undefined}>
            <div className="empty-state" id="intent-empty" style={emptyDisplay ? { display: emptyDisplay } : undefined}>
              <div className="empty-icon">
                <Icon name="bot" plain className="icon-large" />
              </div>
              <p>选择需要审查的代码文件</p>
            </div>
            <div id="intent-content" ref={contentRef} dangerouslySetInnerHTML={{ __html: renderedHtml }} />
          </div>
          <textarea
            id="intent-textarea"
            className="intent-textarea"
            ref={textareaRef}
            value={editValue}
            onChange={(event) => setEditValue(event.target.value)}
            placeholder="Markdown content..."
            style={{
              display: textareaDisplay,
              width: "100%",
              height: "100%",
              minHeight: "60vh",
              border: "none",
              resize: "vertical",
              outline: "none",
              lineHeight: "1.6",
              fontSize: "0.95rem",
            }}
          />
        </div>

        <div
          id="intent-edit-actions"
          style={{
            display: actionsDisplay,
            padding: "1rem",
            borderTop: "1px solid var(--border)",
            background: "#f9fafb",
            justifyContent: "flex-end",
            gap: "0.5rem",
          }}
        >
          <button className="btn-secondary" onClick={cancelEditMode}>
            取消
          </button>
          <button className="btn-primary" onClick={() => void saveEdit()}>
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
