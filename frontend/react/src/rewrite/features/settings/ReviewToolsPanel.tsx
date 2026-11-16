import { useAppStore } from "../../state/appStore";

export function ReviewToolsPanel() {
  const tools = useAppStore((s) => s.tools);
  const selectedTools = useAppStore((s) => s.selectedTools);
  const enableStaticScan = useAppStore((s) => s.enableStaticScan);
  const optionsLoading = useAppStore((s) => s.optionsLoading);
  const optionsError = useAppStore((s) => s.optionsError);
  const toggleTool = useAppStore((s) => s.toggleTool);

  return (
    <div className="ds-capabilities">
      <section className="ds-card ds-preferences">
        <header className="ds-card-head">
          <div><h3>审查工具</h3><p>选择审查时允许使用的工具，更改即时生效，用于下一次审查。</p></div>
        </header>
        <div id="toolListContainer" aria-label="审查工具列表">
          {optionsLoading ? <div className="ds-state-box" role="status"><span className="ds-spinner" />正在加载工具...</div>
            : optionsError ? <div className="ds-state-box ds-state-box--error" role="alert">
              加载工具失败
              <button type="button" className="ds-link-btn" onClick={() => window.dispatchEvent(new CustomEvent("dc:retry-options"))}>重试</button>
            </div>
            : tools.length === 0 ? <div className="ds-empty">无可用工具</div>
            : tools.map((tool) => {
              const scannerBound = tool.name === "get_scanner_results";
              const checked = scannerBound ? enableStaticScan : selectedTools.includes(tool.name);
              const id = `ds-review-tool-${tool.name}`;
              return <div className="ds-preference-row" key={tool.name}>
                <div className="ds-form-copy">
                  <label className="ds-label" htmlFor={id}>{tool.name}</label>
                  {tool.description ? <p className="ds-hint" id={`${id}-hint`}>{tool.description}</p> : null}
                  {scannerBound ? <p className="ds-hint">随审查页的“静态分析”开关自动启用或关闭。</p> : null}
                </div>
                <label className="ds-switch">
                  <input id={id} type="checkbox" role="switch" checked={checked} aria-checked={checked}
                    aria-describedby={tool.description ? `${id}-hint` : undefined} disabled={scannerBound}
                    onChange={() => toggleTool(tool.name)} />
                  <span className="ds-switch-track"><span className="ds-switch-thumb" /></span>
                  <span className="ds-switch-text">{checked ? "已启用" : "已关闭"}</span>
                </label>
              </div>;
            })}
        </div>
      </section>
    </div>
  );
}
