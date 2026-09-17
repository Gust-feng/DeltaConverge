type Props = {
  value: unknown;
  emptyText?: string;
  compact?: boolean;
};

export function JsonBlock({ value, emptyText = "No structured data yet.", compact = false }: Props) {
  if (value == null) {
    return <div className="empty-state">{emptyText}</div>;
  }

  const content = typeof value === "string" ? value : JSON.stringify(value, null, compact ? 0 : 2);
  if (!content || content === "{}" || content === "[]") {
    return <div className="empty-state">{emptyText}</div>;
  }
  return <pre className="json-block">{content}</pre>;
}
