type Props = {
  children: string;
  tone?: "neutral" | "active" | "success" | "danger" | "warning";
};

export function StatusPill({ children, tone = "neutral" }: Props) {
  return <span className={`status-pill tone-${tone}`}>{children}</span>;
}
