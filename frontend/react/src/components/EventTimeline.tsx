import type { WorkflowEvent } from "../types";
import { JsonBlock } from "./JsonBlock";
import { StatusPill } from "./StatusPill";

type Props = {
  events: WorkflowEvent[];
};

function eventTone(type: string): "neutral" | "active" | "success" | "danger" | "warning" {
  if (type === "review.completed" || type === "scan.finished") return "success";
  if (type === "review.failed") return "danger";
  if (type.endsWith(".started") || type === "review.delta") return "active";
  if (type === "tool.finished") return "warning";
  return "neutral";
}

export function EventTimeline({ events }: Props) {
  return (
    <section className="panel-card rail-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">SSE Stream</p>
          <h2>Event Timeline</h2>
        </div>
        <span>{events.length}</span>
      </div>

      <div className="timeline-list">
        {events.length === 0 ? <div className="empty-state">No workflow events yet.</div> : null}
        {events.map((event) => (
          <article key={`${event.run_id}-${event.seq}`} className="timeline-item">
            <div className="timeline-head">
              <StatusPill tone={eventTone(event.type)}>{event.type}</StatusPill>
              <small>#{event.seq}</small>
            </div>
            <strong>{event.stage || "kernel"}</strong>
            <small>{new Date(event.created_at).toLocaleString()}</small>
            <details>
              <summary>Payload</summary>
              <JsonBlock value={event.payload} compact />
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
