import type { SessionSummary } from "../types";
import { StatusPill } from "./StatusPill";

type Props = {
  sessions: SessionSummary[];
  totalCount: number;
  currentSessionId: string | null;
  filterValue: string;
  isLoading: boolean;
  onFilterChange: (value: string) => void;
  onRefresh: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
};

function statusTone(status: string): "neutral" | "active" | "success" | "danger" | "warning" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "active" || status === "running" || status === "created") return "active";
  if (status === "archived") return "warning";
  return "neutral";
}

export function SessionHistory({
  sessions,
  totalCount,
  currentSessionId,
  filterValue,
  isLoading,
  onFilterChange,
  onRefresh,
  onSelect,
  onDelete,
}: Props) {
  return (
    <aside className="sidebar-card session-sidebar">
      <div className="sidebar-header">
        <div>
          <p className="sidebar-eyebrow">Kernel Store</p>
          <h2>Session History</h2>
        </div>
        <button className="ghost-button" onClick={onRefresh}>
          Refresh
        </button>
      </div>

      <div className="sidebar-search">
        <input
          value={filterValue}
          onChange={(event) => onFilterChange(event.target.value)}
          placeholder="Filter by name, path, tag, status..."
        />
        <span>
          {sessions.length}/{totalCount}
        </span>
      </div>

      <div className="session-list">
        {isLoading ? <div className="empty-state">Loading sessions...</div> : null}
        {!isLoading && sessions.length === 0 ? <div className="empty-state">No sessions match the current filter.</div> : null}
        {sessions.map((session) => (
          <article
            key={session.id}
            className={`session-item ${currentSessionId === session.id ? "active" : ""}`}
            onClick={() => onSelect(session.id)}
          >
            <div className="session-row">
              <strong>{session.name}</strong>
              <button
                className="icon-button"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(session.id);
                }}
                aria-label={`Delete ${session.name}`}
                title="Delete session"
              >
                ×
              </button>
            </div>
            <div className="session-row">
              <StatusPill tone={statusTone(session.status)}>{session.status}</StatusPill>
              <small>{new Date(session.updated_at).toLocaleString()}</small>
            </div>
            <p className="session-path">{session.project_root || "No project root"}</p>
            {session.tags.length > 0 ? (
              <div className="session-tags">
                {session.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </aside>
  );
}
