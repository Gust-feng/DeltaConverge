import { JsonBlock } from "./JsonBlock";

type Props = {
  diffSnapshot: Record<string, unknown>;
};

type DiffFile = {
  path?: string;
  display_path?: string;
  change_type?: string;
  additions?: number;
  deletions?: number;
  hunks?: unknown[];
};

export function DiffPanel({ diffSnapshot }: Props) {
  const files = Array.isArray(diffSnapshot.diff_files) ? (diffSnapshot.diff_files as DiffFile[]) : [];
  const units = Array.isArray(diffSnapshot.diff_units) ? diffSnapshot.diff_units : [];

  return (
    <section className="panel-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Diff Snapshot</p>
          <h2>Diff Panel</h2>
        </div>
        <span>{files.length} files</span>
      </div>

      {files.length === 0 ? <div className="empty-state">No diff snapshot artifact for the selected run.</div> : null}

      <div className="stack-list">
        {files.map((file, index) => (
          <article key={`${file.path || file.display_path || "diff"}-${index}`} className="detail-card">
            <div className="card-header compact">
              <strong>{file.display_path || file.path || "Unnamed diff file"}</strong>
              <span>{file.change_type || "changed"}</span>
            </div>
            <p className="detail-meta">
              +{file.additions ?? 0} / -{file.deletions ?? 0} {Array.isArray(file.hunks) ? ` / ${file.hunks.length} hunks` : ""}
            </p>
          </article>
        ))}
      </div>

      <details className="detail-toggle">
        <summary>Raw diff units ({units.length})</summary>
        <JsonBlock value={units} />
      </details>
    </section>
  );
}
