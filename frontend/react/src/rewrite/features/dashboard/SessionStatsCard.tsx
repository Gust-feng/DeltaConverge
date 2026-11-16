import type { DashboardSessionStats } from "./types";

export function SessionStatsCard({ stats }: { stats: DashboardSessionStats | null | undefined }) {
  const totalSessions = stats?.total_sessions || 0;
  const totalMessages = stats?.total_messages || 0;
  const statusEntries = Object.entries(stats?.by_status || {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);
  const projectCount = Object.keys(stats?.by_project || {}).length;

  return (
    <div className="card">
      <div className="card-header">
        <h3>会话统计</h3>
        <span id="session-total-badge" className="badge">
          {String(totalSessions)}
        </span>
      </div>
      <div className="card-body" id="session-stats-content">
        {stats ? (
          <>
            <div className="stat-row">
              <span className="label">消息总数:</span>
              <span className="value">{totalMessages}</span>
            </div>
            <div className="stat-row">
              <span className="label">项目数:</span>
              <span className="value">{projectCount}</span>
            </div>
            {statusEntries.map(([key, value]) => (
              <div className="stat-row" key={key}>
                <span className="label">{`${key}:`}</span>
                <span className="value">{value}</span>
              </div>
            ))}
          </>
        ) : null}
      </div>
    </div>
  );
}
