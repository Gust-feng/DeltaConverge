import type { GitCommit } from "../../types";
import { useGitHistory } from "./useGitHistory";

function renderCommitMessage(message: string): { html: string } | { text: string } {
  const marked = typeof window !== "undefined" ? window.marked : undefined;
  if (marked && typeof marked.parse === "function") {
    return { html: marked.parse(message || "", { breaks: true }) };
  }
  return { text: message };
}

function CommitItem({ commit, isLast }: { commit: GitCommit; isLast: boolean }) {
  const message = renderCommitMessage(commit.message);
  const hashText = commit.short_hash || commit.hash.substring(0, 7);

  return (
    <div
      className="git-commit-item"
      data-hash={commit.hash}
      onClick={() => {
        console.log("[GitHistory] Clicked commit:", commit.hash);
      }}
    >
      <div className="commit-graph">
        <div className={commit.is_merge ? "commit-dot merge-commit" : "commit-dot"} />
        {!isLast ? <div className="commit-line" /> : null}
      </div>
      <div className="commit-info">
        {commit.refs ? <div className="commit-refs">{commit.refs}</div> : null}
        <div className="commit-header">
          <span className="commit-hash">{hashText}</span>
          <span className="commit-time">{commit.relative_date}</span>
        </div>
        {"html" in message ? (
          <div className="commit-message" dangerouslySetInnerHTML={{ __html: message.html }} />
        ) : (
          <div className="commit-message">{message.text}</div>
        )}
        <div className="commit-author">{`by ${commit.author}`}</div>
      </div>
    </div>
  );
}

export function GitHistorySection({ projectRoot }: { projectRoot: string | null }) {
  const { state, loadingMore, refresh, loadMore } = useGitHistory(projectRoot);

  let body;
  if (state.status === "loading") {
    body = (
      <div className="empty-state" style={{ padding: "1rem", textAlign: "center" }}>
        <p style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>加载中...</p>
      </div>
    );
  } else if (state.status === "error") {
    body = (
      <div className="empty-state" style={{ padding: "2rem", textAlign: "center" }}>
        <p style={{ color: "var(--danger)" }}>加载失败</p>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
          {state.error || "未知错误"}
        </p>
      </div>
    );
  } else if (state.status === "empty") {
    body = (
      <div className="empty-state" style={{ padding: "2rem", textAlign: "center" }}>
        <p style={{ color: "var(--text-muted)" }}>没有找到 Git 提交历史</p>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
          请确保当前项目是一个 Git 仓库
        </p>
      </div>
    );
  } else {
    body = state.commits.map((commit, index) => (
      <CommitItem key={`${commit.hash}-${index}`} commit={commit} isLast={index === state.commits.length - 1} />
    ));
  }

  return (
    <div
      id="git-history-section"
      style={{
        display: state.visible ? "block" : "none",
        flex: 1,
        overflowY: "auto",
        marginTop: "0.75rem",
        paddingTop: "0.75rem",
        borderTop: "1px solid var(--border, #e5e7eb)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <svg className="icon" style={{ width: "12px", height: "12px", color: "var(--text-muted)" }}>
            <use href="#icon-clock" />
          </svg>
          <span style={{ fontSize: "0.75rem", fontWeight: 500, color: "var(--text-muted)" }}>提交历史</span>
          <span
            id="git-current-branch"
            className="branch-badge"
            style={{ display: state.branch ? "inline-block" : "none" }}
          >
            {state.branch ? `● ${state.branch}` : ""}
          </span>
        </div>
        <button className="btn-text" style={{ fontSize: "0.7rem" }} onClick={() => void refresh()}>
          刷新
        </button>
      </div>
      <div className="git-history-body">
        <div id="git-commit-list" className="git-commit-list">
          {body}
        </div>
        <button
          id="git-load-more"
          className="btn-text"
          onClick={() => void loadMore()}
          disabled={loadingMore}
          style={{
            display: state.status === "ready" && state.hasMore ? "block" : "none",
            width: "100%",
            padding: "0.5rem",
            marginTop: "0.5rem",
            fontSize: "0.75rem",
            color: "var(--primary)",
            textAlign: "center",
          }}
        >
          {loadingMore ? "加载中..." : "加载更多..."}
        </button>
      </div>
    </div>
  );
}
