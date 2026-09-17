type Props = {
  projectRoot: string;
  prompt: string;
  model: string;
  enableStaticScan: boolean;
  isBusy: boolean;
  onProjectRootChange: (value: string) => void;
  onPromptChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onEnableStaticScanChange: (value: boolean) => void;
  onStartReview: () => void;
  onAnalyzeProject: () => void;
};

export function ReviewComposer({
  projectRoot,
  prompt,
  model,
  enableStaticScan,
  isBusy,
  onProjectRootChange,
  onPromptChange,
  onModelChange,
  onEnableStaticScanChange,
  onStartReview,
  onAnalyzeProject,
}: Props) {
  return (
    <section className="panel-card composer-card">
      <div className="card-header">
        <div>
          <p className="section-eyebrow">Review Intake</p>
          <h2>Review Composer</h2>
        </div>
        <div className="card-actions">
          <button className="ghost-button" disabled={isBusy} onClick={onAnalyzeProject}>
            Analyze Workspace
          </button>
          <button className="primary" disabled={isBusy} onClick={onStartReview}>
            {isBusy ? "Working..." : "Start Review"}
          </button>
        </div>
      </div>

      <div className="form-grid">
        <label className="full">
          Project Root
          <input value={projectRoot} onChange={(event) => onProjectRootChange(event.target.value)} placeholder="Z:\\path\\to\\repo" />
        </label>
        <label>
          Model
          <input value={model} onChange={(event) => onModelChange(event.target.value)} placeholder="auto" />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={enableStaticScan}
            onChange={(event) => onEnableStaticScanChange(event.target.checked)}
          />
          Enable static scan
        </label>
        <label className="full">
          Prompt
          <textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} rows={5} />
        </label>
      </div>
    </section>
  );
}
