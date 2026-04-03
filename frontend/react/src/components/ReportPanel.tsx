type Props = {
  reportText: string;
  question: string;
  qaAnswer: string;
  disabled: boolean;
  onQuestionChange: (value: string) => void;
  onSubmit: () => void;
};

export function ReportPanel({ reportText, question, qaAnswer, disabled, onQuestionChange, onSubmit }: Props) {
  return (
    <section className="panel-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Review Output</p>
          <h2>Report Panel</h2>
        </div>
      </div>

      <article className="report-surface">
        {reportText ? <pre className="report-text">{reportText}</pre> : <div className="empty-state">No report yet. Start a review to populate the final report.</div>}
      </article>

      <div className="qa-box">
        <div className="card-header compact">
          <h3>Review QA</h3>
        </div>
        <textarea
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          rows={4}
          placeholder="Ask about the review conclusion, diff impact, or why a finding matters..."
        />
        <button className="primary" disabled={disabled || !question.trim()} onClick={onSubmit}>
          Ask QA
        </button>
        {qaAnswer ? <pre className="report-text secondary">{qaAnswer}</pre> : <div className="empty-state">No QA answer yet.</div>}
      </div>
    </section>
  );
}
