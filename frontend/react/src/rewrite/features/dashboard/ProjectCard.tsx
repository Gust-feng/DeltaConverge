import { GitHistorySection } from "../gitHistory/GitHistorySection";

export function ProjectCard({
  pathText,
  diffText,
  projectRoot,
  onSwitch,
}: {
  pathText: string;
  diffText: string;
  projectRoot: string | null;
  onSwitch: () => void;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <h3>当前项目</h3>
        <button className="btn-text" onClick={onSwitch}>
          切换
        </button>
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flexShrink: 0 }}>
          <div className="stat-row">
            <span className="label">路径:</span>
            <span className="value" id="dash-project-path">
              {pathText}
            </span>
          </div>
          <div className="stat-row">
            <span className="label">Diff 状态:</span>
            <span className="value" id="dash-diff-status">
              {diffText}
            </span>
          </div>
        </div>
        <GitHistorySection projectRoot={projectRoot} />
      </div>
    </div>
  );
}
