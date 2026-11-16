import { useEffect, useMemo, useRef, useState } from "react";

import { addModel, deleteModel, discoverProviderModels, type ProviderInfo } from "../../lib/api";
import { showToast } from "../../lib/toast";
import { ProviderLogo } from "./ProviderLogo";
import { AlertIcon, ArrowLeftIcon, SearchIcon, XIcon } from "./icons";

export function ModelPickerPanel({ provider, onClose, onSaved, onSavingChange }: {
  provider: ProviderInfo;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onSavingChange: (saving: boolean) => void;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set(provider.models));
  const [saved, setSaved] = useState<Set<string>>(() => new Set(provider.models));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [progress, setProgress] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void discoverProviderModels(provider.id, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setModels([...new Set([...result.models, ...provider.models])].sort((a, b) => a.localeCompare(b)));
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [provider.id, attempt]);

  useEffect(() => {
    if (!loading) searchRef.current?.focus();
  }, [loading]);

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase();
    return models.filter((model) => model.toLowerCase().includes(text));
  }, [models, query]);
  const additions = models.filter((model) => selected.has(model) && !saved.has(model));
  const removals = models.filter((model) => !selected.has(model) && saved.has(model));
  const changeCount = additions.length + removals.length;

  function toggleModel(model: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(model)) next.delete(model);
      else next.add(model);
      return next;
    });
  }

  function selectFiltered(checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      for (const model of filtered) {
        if (checked) next.add(model);
        else next.delete(model);
      }
      return next;
    });
  }

  async function confirmSelection() {
    if (saving || loading) return;
    if (changeCount === 0) {
      onClose();
      return;
    }
    setSaving(true);
    onSavingChange(true);
    setError(null);
    setProgress(0);
    const nextSaved = new Set(saved);
    let completed = 0;
    let failure: unknown;
    try {
      for (const model of additions) {
        await addModel(provider.id, model);
        nextSaved.add(model);
        setProgress(++completed);
      }
      for (const model of removals) {
        await deleteModel(provider.id, model);
        nextSaved.delete(model);
        setProgress(++completed);
      }
    } catch (reason) {
      failure = reason;
    }
    setSaved(nextSaved);
    if (completed > 0) await onSaved();
    setSaving(false);
    onSavingChange(false);
    if (failure) {
      const detail = failure instanceof Error ? failure.message : String(failure);
      setError(`${completed > 0 ? `已保存 ${completed} 项更改，其余更改未完成` : "保存失败"}：${detail}`);
    } else {
      showToast("模型列表已更新", "success", { floating: true });
      onClose();
    }
  }

  return (
    <section className="ds-discovery-content" aria-label="选择模型">
      <header className="ds-discovery-head">
        <button type="button" className="ds-icon-btn" title="返回模型服务详情" disabled={saving} onClick={onClose}>
          <ArrowLeftIcon size={18} />
        </button>
        <ProviderLogo provider={provider.id} label={provider.label} size="lg" />
        <div className="ds-discovery-heading">
          <h2>选择模型</h2>
          <p>{provider.label} · 勾选需要使用的模型</p>
        </div>
        <button type="button" className="ds-icon-btn" title="关闭选择面板" disabled={saving} onClick={onClose}>
          <XIcon size={19} />
        </button>
      </header>

      {!loading && models.length > 0 ? (
        <div className="ds-discovery-tools">
          <div className="ds-search ds-search--lg">
            <SearchIcon size={17} />
            <input
              ref={searchRef}
              aria-label="搜索可用模型"
              placeholder="搜索可用模型（ID 或名称）"
              value={query}
              disabled={saving}
              spellCheck={false}
              onChange={(event) => setQuery(event.target.value)}
            />
            {query ? (
              <button type="button" className="ds-search-clear" title="清空搜索" disabled={saving} onClick={() => setQuery("")}>
                <XIcon size={14} />
              </button>
            ) : null}
          </div>
          <div className="ds-discovery-summary">
            <span>已勾选 {selected.size} / {models.length} 个模型{query.trim() ? ` · 找到 ${filtered.length} 个` : ""}</span>
            <button type="button" className="ds-link-btn" disabled={saving || filtered.length === 0} onClick={() => selectFiltered(true)}>
              {query.trim() ? "全选结果" : "全选"}
            </button>
            <button type="button" className="ds-link-btn" disabled={saving || filtered.length === 0} onClick={() => selectFiltered(false)}>
              {query.trim() ? "清空结果" : "清空"}
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="ds-discovery-error" role="alert">
          <AlertIcon size={17} />
          <span>{error}</span>
          {models.length === 0 ? (
            <button type="button" className="ds-link-btn" disabled={loading} onClick={() => setAttempt((current) => current + 1)}>重试</button>
          ) : null}
        </div>
      ) : null}

      <div className="ds-discovery-list" aria-busy={loading || saving}>
        {loading ? (
          <div className="ds-state-box" role="status"><span className="ds-spinner" /><span>正在获取模型…</span></div>
        ) : filtered.length > 0 ? filtered.map((model) => (
          <label className={`ds-discovery-option ${selected.has(model) ? "ds-discovery-option--selected" : ""}`} key={model}>
            <input
              type="checkbox"
              checked={selected.has(model)}
              disabled={saving}
              onChange={() => toggleModel(model)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  toggleModel(model);
                }
              }}
            />
            <ProviderLogo provider={provider.id} label={provider.label} size="xs" />
            <span className="ds-discovery-model" title={model}>{model}</span>
            {saved.has(model) ? <span className="ds-model-tag">已在列表</span> : null}
          </label>
        )) : !error ? (
          <div className="ds-empty">{query.trim() ? "没有匹配的模型" : "该服务暂未返回模型，可返回后手动添加模型 ID"}</div>
        ) : null}
      </div>

      <footer className="ds-discovery-footer">
        <span aria-live="polite">{saving ? `正在保存 ${progress} / ${changeCount} 项更改` : changeCount > 0 ? `新增 ${additions.length} 个 · 移除 ${removals.length} 个` : ""}</span>
        <button type="button" className="ds-btn" disabled={saving} onClick={onClose}>取消</button>
        <button type="button" className="ds-btn ds-btn--primary" disabled={loading || saving || Boolean(error && models.length === 0)} onClick={() => void confirmSelection()}>
          {saving ? "保存中…" : `确认选择 (${selected.size} 个模型)`}
        </button>
      </footer>
    </section>
  );
}
