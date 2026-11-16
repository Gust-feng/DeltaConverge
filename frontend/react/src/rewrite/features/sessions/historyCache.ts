import { listSessionsLegacy } from "../../lib/api";
import type { LegacySessionSummary } from "../../types";

// Bound the GET so a reloading/unresponsive server cannot leave the drawer loading forever.
export async function fetchHistory(projectRoot: string | null, timeoutMs = 12_000): Promise<LegacySessionSummary[]> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await listSessionsLegacy(projectRoot, controller.signal);
  } catch (error) {
    if (controller.signal.aborted) throw new Error("历史记录加载超时，请检查服务后重试");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

type HistoryEntry = {
  sessions: LegacySessionSummary[] | null;
  error: string | null;
  updatedAt: number;
  revision: number;
  pending: Promise<void> | null;
};

// Shared across drawer opens and React StrictMode remounts. Empty results are cached too.
export class HistoryCache {
  private entries = new Map<string, HistoryEntry>();
  private listeners = new Set<() => void>();

  constructor(
    private readonly fetchSessions = fetchHistory,
    private readonly now = Date.now,
    private readonly maxAge = 15_000,
  ) {}

  snapshot(projectRoot: string | null): HistoryEntry {
    const key = projectRoot || "";
    let entry = this.entries.get(key);
    if (!entry) {
      entry = { sessions: null, error: null, updatedAt: 0, revision: 0, pending: null };
      this.entries.set(key, entry);
    }
    return entry;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }

  invalidate(update?: (sessions: LegacySessionSummary[]) => LegacySessionSummary[]): void {
    for (const entry of this.entries.values()) {
      entry.revision++;
      entry.updatedAt = 0;
      if (update && entry.sessions) entry.sessions = update(entry.sessions);
    }
    this.notify();
  }

  load(projectRoot: string | null, force = false): Promise<void> {
    const entry = this.snapshot(projectRoot);
    if (entry.pending) return entry.pending;
    if (!force && entry.sessions !== null && entry.updatedAt > 0 && this.now() - entry.updatedAt < this.maxAge) {
      return Promise.resolve();
    }
    entry.error = null;
    // Start on a microtask so pending is visible before notifying subscribers.
    const pending = Promise.resolve().then(async () => {
      for (;;) {
        const revision = entry.revision;
        try {
          const sessions = await this.fetchSessions(projectRoot);
          // A create/update/delete happened during this request. Discard its stale result
          // and issue one follow-up request, shared by all current callers.
          if (revision !== entry.revision) continue;
          entry.sessions = sessions;
          entry.error = null;
          entry.updatedAt = this.now();
        } catch (error) {
          if (revision !== entry.revision) continue;
          entry.error = error instanceof Error ? error.message : String(error);
        }
        break;
      }
    }).finally(() => {
      if (entry.pending === pending) entry.pending = null;
      this.notify();
    });
    entry.pending = pending;
    this.notify();
    return pending;
  }
}

export const historyCache = new HistoryCache();
