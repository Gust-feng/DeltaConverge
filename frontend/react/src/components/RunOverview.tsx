import type { MessageRecord, ScanResult, SessionDetail, WorkflowEvent } from "../types";
import { StatusPill } from "./StatusPill";

type Props = {
  sessionDetail: SessionDetail | null;
  messages: MessageRecord[];
  events: WorkflowEvent[];
  diffSnapshot: Record<string, unknown>;
  scanResult: ScanResult | null;
};

function countDiffFiles(diffSnapshot: Record<string, unknown>) {
  return Array.isArray(diffSnapshot.diff_files) ? diffSnapshot.diff_files.length : 0;
}

function countDiffUnits(diffSnapshot: Record<string, unknown>) {
  return Array.isArray(diffSnapshot.diff_units) ? diffSnapshot.diff_units.length : 0;
}

function countScanIssues(scanResult: ScanResult | null) {
  if (!scanResult) {
    return 0;
  }
  return Object.values(scanResult.issues_by_severity).reduce((total, issues) => total + issues.length, 0);
}

function statusTone(status: string): "neutral" | "active" | "success" | "danger" | "warning" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "active" || status === "running" || status === "created") return "active";
  if (status === "archived") return "warning";
  return "neutral";
}

export function RunOverview({ sessionDetail, messages, events, diffSnapshot, scanResult }: Props) {
  const run = sessionDetail?.latest_run ?? null;
  const summary = sessionDetail?.summary ?? null;

  return (
    <section className="overview-grid">
      <div className="metric-card">
        <span>Session</span>
        <strong>{summary?.name ?? "No session selected"}</strong>
        {summary ? <StatusPill tone={statusTone(summary.status)}>{summary.status}</StatusPill> : null}
      </div>
      <div className="metric-card">
        <span>Current Run</span>
        <strong>{run?.id ?? "No active run"}</strong>
        <small>{run?.model ?? "Select a model to start"}</small>
      </div>
      <div className="metric-card">
        <span>Events</span>
        <strong>{events.length}</strong>
        <small>Messages {messages.length}</small>
      </div>
      <div className="metric-card">
        <span>Diff</span>
        <strong>{countDiffFiles(diffSnapshot)} files</strong>
        <small>{countDiffUnits(diffSnapshot)} units</small>
      </div>
      <div className="metric-card">
        <span>Scan</span>
        <strong>{countScanIssues(scanResult)} issues</strong>
        <small>{scanResult ? "Latest result loaded" : "Pending / disabled"}</small>
      </div>
      <div className="metric-card">
        <span>Artifacts</span>
        <strong>{sessionDetail?.artifacts.length ?? 0}</strong>
        <small>{summary?.project_root ?? "Kernel artifacts only"}</small>
      </div>
    </section>
  );
}
