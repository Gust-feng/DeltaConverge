import type { MessageRecord } from "../types";

type Props = {
  messages: MessageRecord[];
};

export function MessagesPanel({ messages }: Props) {
  return (
    <section className="panel-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Conversation Log</p>
          <h2>Messages Panel</h2>
        </div>
        <span>{messages.length}</span>
      </div>

      <div className="message-list">
        {messages.length === 0 ? <div className="empty-state">No messages recorded for this session.</div> : null}
        {messages.map((message) => (
          <article key={`${message.id || message.created_at}-${message.role}`} className={`message-card role-${message.role}`}>
            <div className="message-head">
              <strong>{message.role}</strong>
              <small>{new Date(message.created_at).toLocaleString()}</small>
            </div>
            <div className="message-meta">
              <span>{String(message.metadata.channel || "kernel")}</span>
              <span>{String(message.metadata.kind || "message")}</span>
            </div>
            <pre className="message-body">{message.content}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
