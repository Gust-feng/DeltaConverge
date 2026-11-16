import { useCallback, useEffect, useRef, useState } from "react";

import { getCommits, getGitBranch } from "../../lib/api";
import type { GitCommit } from "../../types";

const PAGE_SIZE = 20;

export type GitHistoryStatus = "loading" | "empty" | "error" | "ready";

export type GitHistoryState = {
  visible: boolean;
  status: GitHistoryStatus;
  commits: GitCommit[];
  hasMore: boolean;
  branch: string | null;
  error: string;
};

const INITIAL_STATE: GitHistoryState = {
  visible: false,
  status: "loading",
  commits: [],
  hasMore: false,
  branch: null,
  error: "",
};

/**
 * 1:1 复刻 legacy/git-history.js 的 GitHistory 对象。
 * 用请求序号代替 AbortController 丢弃过期结果（共享 api 不支持 signal）。
 */
export function useGitHistory(projectRoot: string | null) {
  const [state, setState] = useState<GitHistoryState>(INITIAL_STATE);
  const [loadingMore, setLoadingMore] = useState(false);

  const seqRef = useRef(0);
  const rootRef = useRef<string | null>(projectRoot);
  const previousRootRef = useRef<string | null | undefined>(undefined);

  const isStale = useCallback((seq: number, root: string) => {
    return seq !== seqRef.current || rootRef.current !== root;
  }, []);

  const loadBranch = useCallback(
    async (root: string, seq: number) => {
      try {
        const branch = await getGitBranch(root);
        if (isStale(seq, root)) return;
        setState((previous) => ({ ...previous, branch: branch || null }));
      } catch {
        if (isStale(seq, root)) return;
        setState((previous) => ({ ...previous, branch: null }));
      }
    },
    [isStale]
  );

  const loadFirstPage = useCallback(
    async (root: string, seq: number) => {
      try {
        const data = await getCommits(root, PAGE_SIZE, 0);
        if (isStale(seq, root)) return;
        if (data.success === false) {
          setState((previous) => ({
            ...previous,
            status: "error",
            error: data.error || "加载失败",
            commits: [],
          }));
          return;
        }
        const commits = data.commits || [];
        setState((previous) => ({
          ...previous,
          status: commits.length === 0 ? "empty" : "ready",
          commits,
          hasMore: commits.length >= PAGE_SIZE,
          error: "",
        }));
      } catch (error) {
        if (isStale(seq, root)) return;
        const message = error instanceof Error ? error.message : String(error);
        console.error("[GitHistory] Load error:", error);
        setState((previous) => ({
          ...previous,
          status: "error",
          error: message,
          commits: [],
        }));
      }
    },
    [isStale]
  );

  const init = useCallback(
    async (root: string) => {
      const seq = ++seqRef.current;
      setLoadingMore(false);
      // GitHistory.show() + 清空 commits/branch + renderLoading()
      setState({ visible: true, status: "loading", commits: [], hasMore: true, branch: null, error: "" });
      await loadBranch(root, seq);
      if (isStale(seq, root)) return;
      await loadFirstPage(root, seq);
    },
    [isStale, loadBranch, loadFirstPage]
  );

  const initEmpty = useCallback(() => {
    seqRef.current += 1;
    setLoadingMore(false);
    // GitHistory.init(null)：hide + 清状态 + 清分支 + renderEmpty()
    setState({ visible: false, status: "empty", commits: [], hasMore: false, branch: null, error: "" });
  }, []);

  useEffect(() => {
    const previous = previousRootRef.current;
    previousRootRef.current = projectRoot;
    rootRef.current = projectRoot;
    if (projectRoot) {
      void init(projectRoot);
    } else if (previous !== undefined) {
      initEmpty();
    }
    // 首次挂载且没有项目时不改动，保留静态初始的“加载中...”空态。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot]);

  const refresh = useCallback(async () => {
    const root = rootRef.current;
    if (!root) return;
    const seq = ++seqRef.current;
    setLoadingMore(false);
    // 旧版 refresh 不清 branch，只重置列表并显示 loading。
    setState((previous) => ({
      ...previous,
      status: "loading",
      commits: [],
      hasMore: true,
      error: "",
    }));
    await loadBranch(root, seq);
    if (isStale(seq, root)) return;
    await loadFirstPage(root, seq);
  }, [isStale, loadBranch, loadFirstPage]);

  const loadMore = useCallback(async () => {
    const root = rootRef.current;
    if (loadingMore || !state.hasMore || !root) return;

    const seq = ++seqRef.current;
    setLoadingMore(true);
    try {
      const data = await getCommits(root, PAGE_SIZE, state.commits.length);
      if (isStale(seq, root)) return;
      if (data.success === false) return;
      const newCommits = data.commits || [];
      if (newCommits.length > 0) {
        setState((previous) => ({
          ...previous,
          commits: [...previous.commits, ...newCommits],
          hasMore: newCommits.length >= PAGE_SIZE,
          status: "ready",
        }));
      } else {
        setState((previous) => ({ ...previous, hasMore: false }));
      }
    } catch (error) {
      if (isStale(seq, root)) return;
      console.error("[GitHistory] Load more error:", error);
    } finally {
      setLoadingMore(false);
    }
  }, [isStale, loadingMore, state.commits.length, state.hasMore]);

  return { state, loadingMore, refresh, loadMore };
}
