import type { ScanResult } from "../types";
import { JsonBlock } from "./JsonBlock";
import { StatusPill } from "./StatusPill";

type Props = {
  scanResult: ScanResult | null;
};

function prettySeverity(severity: string) {
  return severity.replace(/_/g, " ");
}

function toneForSeverity(severity: string): "neutral" | "active" | "success" | "danger" | "warning" {
  const normalized = severity.toLowerCase();
  if (normalized.includes("critical") || normalized.includes("high")) return "danger";
  if (normalized.includes("medium")) return "warning";
  if (normalized.includes("low") || normalized.includes("info")) return "active";
  return "neutral";
}

export function ScanPanel({ scanResult }: Props) {
  if (!scanResult) {
    return (
      <section className="panel-card">
        <div className="card-header">
          <div>
            <p className="section-eyebrow">Static Scan</p>
            <h2>Scan Panel</h2>
          </div>
        </div>
        <div className="empty-state">No scan result artifact yet. Start a run with static scan enabled.</div>
      </section>
    );
  }

  const severityEntries = Object.entries(scanResult.issues_by_severity);

  return (
    <section className="panel-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Static Scan</p>
          <h2>Scan Panel</h2>
        </div>
      </div>

      <div className="severity-grid">
        {severityEntries.map(([severity, issues]) => (
          <div key={severity} className="metric-card compact">
            <StatusPill tone={toneForSeverity(severity)}>{prettySeverity(severity)}</StatusPill>
            <strong>{issues.length}</strong>
          </div>
        ))}
      </div>

      <div className="stack-list">
        {severityEntries.map(([severity, issues]) => (
          <section key={severity} className="detail-card">
            <div className="card-header compact">
              <strong>{prettySeverity(severity)}</strong>
              <span>{issues.length}</span>
            </div>
            {issues.length === 0 ? <div className="empty-state compact">No issues in this bucket.</div> : null}
            {issues.slice(0, 20).map((issue, index) => {
              const issueRecord = issue as Record<string, unknown>;
              return (
                <article key={`${severity}-${index}`} className="issue-item">
                  <strong>{String(issueRecord.rule_id || issueRecord.rule || issueRecord.code || "Unnamed issue")}</strong>
                  <p>{String(issueRecord.message || issueRecord.summary || issueRecord.description || "No summary")}</p>
                  <small>{String(issueRecord.file || issueRecord.path || issueRecord.location || "No file location")}</small>
                  <details>
                    <summary>Details</summary>
                    <JsonBlock value={issueRecord} compact />
                  </details>
                </article>
              );
            })}
          </section>
        ))}
      </div>

      <details className="detail-toggle">
        <summary>Linked review mapping</summary>
        <JsonBlock value={scanResult.linked} />
      </details>
    </section>
  );
}
