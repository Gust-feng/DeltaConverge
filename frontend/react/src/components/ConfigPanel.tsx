type Props = {
  configText: string;
  isSaving: boolean;
  onChange: (next: string) => void;
  onSave: () => void;
  tools: Array<Record<string, unknown>>;
  providers: Array<Record<string, unknown>>;
};

function displayName(record: Record<string, unknown>) {
  return String(record.display_name || record.name || record.id || record.provider || "Unnamed");
}

export function ConfigPanel({ configText, isSaving, onChange, onSave, tools, providers }: Props) {
  return (
    <section className="config-grid">
      <div className="panel-card">
        <div className="card-header">
          <div>
            <p className="section-eyebrow">Kernel Settings</p>
            <h2>Config Panel</h2>
          </div>
          <button className="primary" disabled={isSaving} onClick={onSave}>
            {isSaving ? "Saving..." : "Save"}
          </button>
        </div>
        <textarea className="config-editor" value={configText} onChange={(event) => onChange(event.target.value)} />
      </div>

      <div className="workspace-stack">
        <div className="panel-card">
          <div className="card-header">
            <div>
              <p className="section-eyebrow">Providers</p>
              <h2>Model Providers</h2>
            </div>
            <span>{providers.length}</span>
          </div>
          <div className="stack-list">
            {providers.length === 0 ? <div className="empty-state">No providers registered.</div> : null}
            {providers.map((provider, index) => (
              <article key={`${displayName(provider)}-${index}`} className="detail-card">
                <strong>{displayName(provider)}</strong>
                <p className="detail-meta">{String(provider.description || provider.base_url || provider.kind || "No description")}</p>
              </article>
            ))}
          </div>
        </div>

        <div className="panel-card">
          <div className="card-header">
            <div>
              <p className="section-eyebrow">Tools</p>
              <h2>Tool Registry</h2>
            </div>
            <span>{tools.length}</span>
          </div>
          <div className="stack-list">
            {tools.length === 0 ? <div className="empty-state">No tools reported by the kernel.</div> : null}
            {tools.map((tool, index) => (
              <article key={`${displayName(tool)}-${index}`} className="detail-card">
                <strong>{displayName(tool)}</strong>
                <p className="detail-meta">{String(tool.description || tool.kind || tool.category || "No description")}</p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
