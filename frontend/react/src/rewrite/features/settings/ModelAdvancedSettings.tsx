import { useEffect, useId, useState } from "react";

import {
  getModelMetadataSettings,
  updateModelMetadataSettings,
  type ModelMetadataSettings,
  type ModelMetadataOverrides,
} from "../../lib/api";
import { showToast } from "../../lib/toast";

const LIMITS = [
  { key: "context_window", label: "上下文窗口", hint: "输入与输出合计的最大 token 数。" },
  { key: "max_input_tokens", label: "最大输入", hint: "模型单次允许接收的最大 token 数。" },
  { key: "max_output_tokens", label: "最大输出", hint: "限制单次生成长度，并用于预留输出预算。" },
] as const;

const CAPABILITIES = [
  { key: "reasoning", label: "思考模型", hint: "用于选择思考模型的等待时间。" },
  { key: "tool_calling", label: "工具调用", hint: "模型是否支持函数或工具调用。" },
  { key: "json_object", label: "JSON 模式", hint: "是否接受 JSON 输出格式参数。" },
  { key: "json_schema", label: "严格 JSON Schema", hint: "是否接受指定字段和类型的输出约束。" },
  { key: "vision", label: "视觉能力", hint: "记录模型是否支持图片输入。" },
] as const;

type CapabilityValue = "auto" | "true" | "false";
type Draft = { limits: Record<string, string>; capabilities: Record<string, CapabilityValue> };

function draftFrom(settings: ModelMetadataSettings): Draft {
  return {
    limits: Object.fromEntries(LIMITS.map(({ key }) => [key, settings.overrides.limits[key]?.toString() ?? ""])),
    capabilities: Object.fromEntries(CAPABILITIES.map(({ key }) => [key,
      typeof settings.overrides.capabilities[key] === "boolean" ? String(settings.overrides.capabilities[key]) as CapabilityValue : "auto",
    ])),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function ModelAdvancedSettings({ provider, model, onSaved, onClose }: {
  provider: string;
  model: string;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const id = useId();
  const [settings, setSettings] = useState<ModelMetadataSettings | null>(null);
  const [draft, setDraft] = useState<Draft>({ limits: {}, capabilities: {} });
  const [savedDraft, setSavedDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void getModelMetadataSettings(provider, model, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      const next = draftFrom(data);
      setSettings(data);
      setDraft(next);
      setSavedDraft(JSON.stringify(next));
    }).catch((cause) => {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [provider, model, reload]);

  const dirty = JSON.stringify(draft) !== savedDraft;
  const invalidLimit = LIMITS.find(({ key }) => {
    const value = draft.limits[key]?.trim();
    return value && (!Number.isSafeInteger(Number(value)) || Number(value) <= 0);
  });
  const effectiveLimits = Object.fromEntries(LIMITS.map(({ key }) => [key,
    draft.limits[key]?.trim() ? Number(draft.limits[key]) : settings?.defaults.limits[key] ?? 0,
  ]));
  const oversizedLimit = effectiveLimits.context_window ? LIMITS.find(({ key }) =>
    key !== "context_window" && effectiveLimits[key] > effectiveLimits.context_window
  ) : undefined;
  const validation = invalidLimit ? `${invalidLimit.label}需填写大于 0 的整数。`
    : oversizedLimit ? `${oversizedLimit.label}不能超过上下文窗口（${effectiveLimits.context_window} token）。` : null;

  function overrides(): ModelMetadataOverrides {
    return {
      limits: Object.fromEntries(LIMITS.filter(({ key }) => draft.limits[key]?.trim())
        .map(({ key }) => [key, Number(draft.limits[key])])),
      capabilities: Object.fromEntries(CAPABILITIES.filter(({ key }) => draft.capabilities[key] !== "auto")
        .map(({ key }) => [key, draft.capabilities[key] === "true"])),
    };
  }

  async function save(reset = false) {
    if (saving || (!reset && validation)) return;
    setSaving(true);
    setError(null);
    try {
      const data = await updateModelMetadataSettings(provider, model, reset ? { limits: {}, capabilities: {} } : overrides());
      const next = draftFrom(data);
      setSettings(data);
      setDraft(next);
      setSavedDraft(JSON.stringify(next));
      await onSaved();
      showToast(reset ? "已恢复自动元数据。" : "模型高级设置已保存，下次请求时生效。", "success", { floating: true });
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="ds-model-advanced ds-state-box" role="status">加载模型高级设置中…</div>;
  if (!settings) return <div className="ds-model-advanced ds-state-box ds-state-box--error" role="alert">
    <span>{error ?? "无法加载模型设置"}</span>
    <button type="button" className="ds-link-btn" onClick={() => setReload((value) => value + 1)}>重试</button>
    <button type="button" className="ds-link-btn" onClick={onClose}>关闭</button>
  </div>;

  const hasOverrides = Object.keys(settings.overrides.limits).length > 0 || Object.keys(settings.overrides.capabilities).length > 0;
  const hasDefaults = Object.keys(settings.defaults.limits).length > 0 || Object.keys(settings.defaults.capabilities).length > 0;

  return <section className="ds-model-advanced" aria-label={`${model} 高级设置`}>
    <div className="ds-model-advanced-head">
      <div><h3>高级设置</h3><p className="ds-hint">仅覆盖此模型。数值留空、能力选择「自动」时沿用默认元数据。</p></div>
      <button type="button" className="ds-btn" disabled={saving} onClick={onClose}>关闭</button>
    </div>
    <p className="ds-hint">{settings.source ? "自动值来自本地模型目录及服务配置。" : hasDefaults
      ? "目录未收录此模型；未填写项沿用服务配置，缺失项保持未知。"
      : "未找到自动元数据，可根据服务商说明手动填写；不填写则保持未知。"}</p>
    <fieldset disabled={saving} className="ds-model-metadata-fields">
      <legend>Token 限制</legend>
      <div className="ds-model-limit-grid">
        {LIMITS.map(({ key, label, hint }) => <div className="ds-field" key={key}>
          <label className="ds-label" htmlFor={`${id}-${key}`}>{label}</label>
          <input id={`${id}-${key}`} className="ds-input" type="number" min={1} step={1}
            aria-describedby={`${id}-${key}-hint`} placeholder={settings.defaults.limits[key] ? `自动：${settings.defaults.limits[key]}` : "未设置"}
            value={draft.limits[key] ?? ""} onChange={(event) => setDraft((current) => ({ ...current, limits: { ...current.limits, [key]: event.target.value } }))} />
          <small id={`${id}-${key}-hint`} className="ds-hint">{hint}</small>
        </div>)}
      </div>
    </fieldset>
    <fieldset disabled={saving} className="ds-model-metadata-fields">
      <legend>模型能力</legend>
      <div className="ds-model-capability-grid">
        {CAPABILITIES.map(({ key, label, hint }) => {
          const baseline = settings.defaults.capabilities[key];
          const autoLabel = typeof baseline === "boolean" ? `自动（${baseline ? "支持" : "不支持"}）` : "自动（未知）";
          return <div className="ds-field" key={key}>
            <label className="ds-label" htmlFor={`${id}-${key}`}>{label}</label>
            <select id={`${id}-${key}`} className="ds-input ds-select" value={draft.capabilities[key] ?? "auto"}
              aria-describedby={`${id}-${key}-hint`}
              onChange={(event) => setDraft((current) => ({ ...current, capabilities: { ...current.capabilities, [key]: event.target.value as CapabilityValue } }))}>
              <option value="auto">{autoLabel}</option><option value="true">支持</option><option value="false">不支持</option>
            </select>
            <small id={`${id}-${key}-hint`} className="ds-hint">{hint}</small>
          </div>;
        })}
      </div>
      <p className="ds-hint">JSON 格式参数仍受「常规 → 结构化输出参数」开关控制。视觉能力仅记录信息，不会新增图片上传功能。</p>
    </fieldset>
    {error ? <p className="ds-preferences-note ds-preferences-note--error" role="alert">{error}</p> : null}
    {validation ? <p className="ds-preferences-note ds-preferences-note--error" role="alert">{validation}</p> : null}
    <div className="ds-model-advanced-actions">
      <button type="button" className="ds-link-btn" disabled={saving || !hasOverrides} onClick={() => void save(true)}>恢复自动值</button>
      {dirty ? <span className="ds-dirty">未保存</span> : null}
      <button type="button" className="ds-btn" disabled={saving || !dirty} onClick={() => { setDraft(draftFrom(settings)); setError(null); }}>撤销更改</button>
      <button type="button" className="ds-btn ds-btn--primary" disabled={saving || !dirty || Boolean(validation)} onClick={() => void save()}>{saving ? "保存中…" : "保存高级设置"}</button>
    </div>
  </section>;
}
