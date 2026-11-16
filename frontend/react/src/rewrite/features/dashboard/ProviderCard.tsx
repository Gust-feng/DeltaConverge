import type { DashboardProvider } from "./types";

function normalizeProviders(providers: DashboardProvider[] | null | undefined) {
  return (Array.isArray(providers) ? providers : []).map((provider) => ({
    name: provider.name || provider.id || "",
    label: provider.label || "",
    available: Boolean(provider.available),
    error: provider.error ?? null,
  }));
}

export function ProviderCard({
  providers,
  onConfigure,
}: {
  providers: DashboardProvider[] | null | undefined;
  onConfigure: () => void;
}) {
  const rows = normalizeProviders(providers);
  const total = rows.length || 0;
  const available = rows.filter((provider) => provider.available).length;

  return (
    <div className="card">
      <div className="card-header">
        <h3>LLM 提供商</h3>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginLeft: "auto" }}>
          <span id="provider-available-badge" className="badge">
            {`${available}/${total}`}
          </span>
          <button className="btn-secondary btn-small" onClick={onConfigure}>
            配置服务
          </button>
        </div>
      </div>
      <div className="card-body compact-list" id="provider-status-content">
        {rows.map((provider, index) => {
          const statusText = provider.available ? "已配置" : "未配置";
          return (
            <div className="stat-row" key={`${provider.name}-${index}`}>
              <span className="label">{`${provider.label || provider.name}:`}</span>
              <span className="value" style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                <span
                  className={`status-dot ${provider.available ? "success" : "error"}`}
                  title={provider.error || statusText}
                />
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{statusText}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
