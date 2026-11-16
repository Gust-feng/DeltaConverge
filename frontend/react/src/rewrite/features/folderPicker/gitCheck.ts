import { checkGitRepository as requestGitCheck } from "../../lib/api";

/**
 * 1:1 复刻 legacy/ui_v1/static/modules/state.js:201-296 的 Git 检测语义：
 * - 5 秒超时；
 * - 成功结果缓存 30 秒，错误结果缓存 5 秒；
 * - 缓存 key 为“去尾分隔符 + 小写”的路径；
 * - isRoot 通过“去尾分隔符 + 小写 + 反斜杠转斜杠”比较得出。
 */

export type GitCheckResult = {
  isGit: boolean;
  isRoot: boolean;
  gitRoot: string | null;
  error: string | null;
};

type CacheEntry = {
  ts: number;
  ttl: number;
  result: GitCheckResult;
};

const SUCCESS_TTL_MS = 30 * 1000;
const ERROR_TTL_MS = 5 * 1000;
const TIMEOUT_MS = 5 * 1000;

const gitRepoCheckCache = new Map<string, CacheEntry>();

function cacheKeyFor(path: string): string {
  return path.toLowerCase().replace(/[\\/]+$/, "");
}

function normalizeForCompare(path: string): string {
  return path.replace(/[\\/]+$/, "").toLowerCase().replace(/\\/g, "/");
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error("请求超时"));
    }, ms);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      }
    );
  });
}

export async function checkGitRepository(
  path: string,
  options: { force?: boolean } = {}
): Promise<GitCheckResult> {
  if (!path) {
    return { isGit: false, isRoot: false, gitRoot: null, error: "No path provided" };
  }

  const now = Date.now();
  const cacheKey = cacheKeyFor(path);

  if (!options.force) {
    const cached = gitRepoCheckCache.get(cacheKey);
    if (cached && now - cached.ts < cached.ttl) {
      return cached.result;
    }
  }

  try {
    const data = await withTimeout(requestGitCheck(path), TIMEOUT_MS);

    let result: GitCheckResult;
    if (data.error && !data.is_git) {
      result = { isGit: false, isRoot: false, gitRoot: null, error: data.error };
    } else if (!data.is_git) {
      result = { isGit: false, isRoot: false, gitRoot: null, error: null };
    } else {
      const gitRoot = data.git_root || null;
      const isRoot = gitRoot
        ? normalizeForCompare(path) === normalizeForCompare(gitRoot)
        : false;
      result = { isGit: true, isRoot, gitRoot, error: data.error || null };
    }

    gitRepoCheckCache.set(cacheKey, { ts: now, ttl: SUCCESS_TTL_MS, result });
    return result;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const result: GitCheckResult = {
      isGit: false,
      isRoot: false,
      gitRoot: null,
      error: message,
    };
    // 与旧版一致：HTTP 非 2xx 属于“正常返回的错误”，缓存 30 秒；
    // 网络失败 / 超时使用 5 秒短缓存，便于用户修复后快速重试。
    const ttl = /^HTTP\s/.test(message) ? SUCCESS_TTL_MS : ERROR_TTL_MS;
    gitRepoCheckCache.set(cacheKey, { ts: now, ttl, result });
    return result;
  }
}

/** 静默预检查；已有未过期缓存时不发请求。 */
export function prefetchGitCheck(path?: string | null): void {
  if (!path) return;
  const cached = gitRepoCheckCache.get(cacheKeyFor(path));
  if (cached && Date.now() - cached.ts < cached.ttl) return;
  void checkGitRepository(path);
}
