import type { WorkflowEvent } from "../../types";

/**
 * v2 的 SSE 是信封事件（WorkflowEvent{seq,type,stage,payload}），
 * 旧 UI 消费的是扁平事件（evt.type/evt.content/evt.tool_name...）。
 * 这里按旧 review.js 的消费习惯做归一化，保留旧字段名。
 */
export type FlatEvent = Record<string, unknown> & {
  type: string;
  seq?: number;
  stage?: string | null;
};

export function flattenEvent(event: WorkflowEvent): FlatEvent[] {
  const payload = (event.payload ?? {}) as Record<string, unknown>;
  const stage = event.stage ?? (payload.stage as string | undefined) ?? null;
  const seq = event.seq;

  switch (event.type) {
    case "review.delta": {
      const subType = String(payload.type ?? "");
      if (subType === "delta") {
        const out: FlatEvent[] = [];
        if (payload.reasoning_delta) {
          out.push({ type: "thought", content: payload.reasoning_delta, stage, seq });
        }
        if (payload.content_delta) {
          out.push({ type: "chunk", content: payload.content_delta, stage, seq });
        }
        const toolDeltas = Array.isArray(payload.tool_calls_delta) ? payload.tool_calls_delta : [];
        for (const tc of toolDeltas as Array<Record<string, unknown>>) {
          const fn = (tc.function ?? {}) as Record<string, unknown>;
          if (fn.name) {
            out.push({
              type: "tool_start",
              tool: fn.name,
              tool_name: fn.name,
              arguments: fn.arguments,
              index: tc.index,
              call_index: tc.index,
              tool_call_id: tc.id,
              stage,
              seq,
            });
          }
        }
        return out;
      }
      return [{ ...payload, type: subType || event.type, stage, seq }];
    }
    case "scan.progress":
      return [{ ...payload, type: String(payload.legacy_type ?? "scanner_progress"), stage: "scan", seq }];
    case "scan.started":
      return [{ ...payload, type: "static_scan_start", stage: "scan", seq }];
    case "scan.finished":
      return [{ ...payload, type: "static_scan_complete", stage: "scan", seq }];
    case "stage.started":
      return [{ ...payload, type: "pipeline_stage_start", stage: event.stage ?? null, seq }];
    case "stage.finished":
      return [{ ...payload, type: "pipeline_stage_end", stage: event.stage ?? null, seq }];
    case "review.failed":
      return [{ ...payload, type: "error", message: payload.error, stage: null, seq }];
    case "review.completed":
      return [];
    default:
      return [];
  }
}

export function flattenEvents(events: WorkflowEvent[]): FlatEvent[] {
  return events.flatMap(flattenEvent);
}

/**
 * 解析 fetch 的 SSE 响应流。用于 POST 形式的 chat / intent 流。
 */
export async function readSseStream(
  response: Response,
  onEvent: (data: Record<string, unknown>) => void
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        onEvent(JSON.parse(data) as Record<string, unknown>);
      } catch {
        // 旧实现同样忽略无法解析的心跳/注释
      }
    }
  }
}
