import type { ProjectAnalysis } from "../types";
import { JsonBlock } from "./JsonBlock";

type Props = {
  projectAnalysis: ProjectAnalysis | null;
};

export function ProjectPanel({ projectAnalysis }: Props) {
  return (
    <section className="panel-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Project Context</p>
          <h2>Project Panel</h2>
        </div>
      </div>

      {!projectAnalysis ? <div className="empty-state">Run workspace analysis to capture repository structure and dependencies.</div> : null}

      {projectAnalysis ? (
        <div className="stack-list">
          <section className="detail-card">
            <div className="card-header compact">
              <strong>Repository Info</strong>
            </div>
            <JsonBlock value={projectAnalysis.info} />
          </section>
          <section className="detail-card">
            <div className="card-header compact">
              <strong>Dependencies</strong>
            </div>
            <JsonBlock value={projectAnalysis.dependencies} />
          </section>
          <section className="detail-card">
            <div className="card-header compact">
              <strong>Git Snapshot</strong>
            </div>
            <JsonBlock value={projectAnalysis.git} />
          </section>
          <section className="detail-card">
            <div className="card-header compact">
              <strong>README Extraction</strong>
            </div>
            <JsonBlock value={projectAnalysis.readme} />
          </section>
          <section className="detail-card">
            <div className="card-header compact">
              <strong>File Tree Snapshot</strong>
            </div>
            <JsonBlock value={projectAnalysis.tree} />
          </section>
        </div>
      ) : null}
    </section>
  );
}
