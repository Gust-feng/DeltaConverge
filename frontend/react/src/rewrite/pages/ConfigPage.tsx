import { useEffect, useMemo, useState } from "react";

import { CloudIcon, ScanSearchIcon, SlidersIcon } from "../features/settings/icons";
import { ReviewToolsPanel } from "../features/settings/ReviewToolsPanel";
import { ModelServicesPanel } from "../features/settings/ModelServicesPanel";
import { ScannerCapabilities } from "../features/settings/ScannerCapabilities";
import { buildConfigSections, type ConfigField, type ConfigRecord } from "../features/config/configMeta";
import { getConfig, updateConfig } from "../lib/api";
import { showToast } from "../lib/toast";

type FieldValue = string | boolean;
type GroupId = "models" | "tools" | "capabilities";

const GROUPS = [
  { id: "models", label: "模型服务", icon: CloudIcon },
  { id: "tools", label: "审查工具", icon: ScanSearchIcon },
  { id: "capabilities", label: "常规", icon: SlidersIcon },
] as const;

const FIELD_META: Record<string, { label: string; description: string; unit?: string; min?: number }> = {
  "llm.enable_structured_output": {
    label: "结构化输出参数",
    description: "关闭时，仅通过提示词要求模型生成 JSON。开启时，同时向模型附带 JSON 格式约束；若服务不支持，会自动退回兼容方式。默认关闭。",
  },
  "review.enable_intent_cache": {
    label: "复用项目意图",
    description: "再次审查同一项目时，复用已有的项目意图分析，减少重复等待。关闭后每次重新分析。",
  },
  "review.intent_cache_ttl_days": {
    label: "缓存保留时间",
    description: "超过此时间，下一次审查会重新分析项目意图。0 表示每次重新分析。",
    unit: "天",
    min: 0,
  },
  "llm.call_timeout": {
    label: "模型响应等待时间",
    description: "单次模型请求的最长等待时间。网络较慢或模型思考较久时，可以适当增加。",
    unit: "秒",
    min: 1,
  },
  "llm.planner_timeout": {
    label: "审查规划等待时间",
    description: "生成审查计划的最长等待时间，超时后结束本次规划。",
    unit: "秒",
    min: 1,
  },
  "llm.planner_first_token_timeout": {
    label: "普通模型首段输出",
    description: "规划阶段等待普通模型开始输出的时间。",
    unit: "秒",
    min: 1,
  },
  "llm.planner_first_token_timeout_thinking": {
    label: "思考模型首段输出",
    description: "规划阶段等待思考模型开始输出的时间，包含输出前的思考。",
    unit: "秒",
    min: 1,
  },
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fieldId(key: string): string {
  return `ds-config-${key.replace(/\./g, "-")}`;
}

export function ConfigPage({ active }: { active: boolean }) {
  const [group, setGroup] = useState<GroupId>("models");
  const [fields, setFields] = useState<ConfigField[]>([]);
  const [values, setValues] = useState<Record<string, FieldValue>>({});
  const [savedValues, setSavedValues] = useState<Record<string, FieldValue>>({});
  const [loading, setLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const handler = (event: Event) => {
      if ((event as CustomEvent).detail === "config") setReloadKey((value) => value + 1);
    };
    window.addEventListener("dc:reload-page", handler);
    return () => window.removeEventListener("dc:reload-page", handler);
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);

    void (async () => {
      try {
        const config = (await getConfig()) as ConfigRecord;
        if (cancelled) return;
        const nextFields = buildConfigSections(config)
          .flatMap((section) => section.fields)
          .filter((field) => Object.prototype.hasOwnProperty.call(FIELD_META, field.key));
        const nextValues = Object.fromEntries(nextFields.map((field) => [field.key, field.initialValue]));
        setFields(nextFields);
        setValues(nextValues);
        setSavedValues(nextValues);
        setHasLoaded(true);
      } catch (error) {
        if (!cancelled) setLoadError(errorMessage(error));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [active, reloadKey]);

  const dirty = useMemo(
    () => fields.some((field) => values[field.key] !== savedValues[field.key]),
    [fields, savedValues, values]
  );

  const validationError = useMemo(() => {
    for (const field of fields) {
      if (field.kind !== "number") continue;
      const value = values[field.key];
      const number = Number(value);
      const meta = FIELD_META[field.key];
      if (typeof value !== "string" || !value.trim() || !Number.isSafeInteger(number) || number < (meta.min ?? 0)) {
        return `${meta.label}需填写${meta.min === 0 ? "不小于 0" : "大于 0"}的整数。`;
      }
    }
    return null;
  }, [fields, values]);

  async function saveConfig() {
    if (!dirty || saving || loading || loadError || validationError) return;
    const snapshot = { ...values };
    const updates: Record<string, Record<string, unknown>> = {};
    for (const field of fields) {
      if (snapshot[field.key] === savedValues[field.key]) continue;
      const [sectionKey, fieldKey] = field.key.split(".");
      if (!updates[sectionKey]) updates[sectionKey] = {};
      updates[sectionKey][fieldKey] = field.kind === "number" ? Number(snapshot[field.key]) : snapshot[field.key];
    }

    setSaving(true);
    try {
      await updateConfig(updates);
      setSavedValues(snapshot);
      showToast("更改已保存，下次审查时生效。", "success", { floating: true });
    } catch (error) {
      showToast("保存失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setSaving(false);
    }
  }

  function renderField(key: string) {
    const field = fields.find((item) => item.key === key);
    if (!field) return null;
    const meta = FIELD_META[key];
    const checked = values[key] === true;
    const disabled = saving || (key === "review.intent_cache_ttl_days" && values["review.enable_intent_cache"] === false);
    return (
      <div className="ds-preference-row" key={key}>
        <div className="ds-form-copy">
          <label className="ds-label" htmlFor={fieldId(key)}>{meta.label}</label>
          <p className="ds-hint" id={`${fieldId(key)}-hint`}>{meta.description}</p>
        </div>
        {field.kind === "boolean" ? (
          <label className="ds-switch">
            <input id={fieldId(key)} type="checkbox" role="switch" checked={checked} aria-checked={checked}
              aria-describedby={`${fieldId(key)}-hint`} disabled={saving}
              onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.checked }))} />
            <span className="ds-switch-track"><span className="ds-switch-thumb" /></span>
            <span className="ds-switch-text">{checked ? "已启用" : "已关闭"}</span>
          </label>
        ) : (
          <div className="ds-number-control">
            <input id={fieldId(key)} className="ds-input" type="number" min={meta.min} step={1}
              aria-describedby={`${fieldId(key)}-hint`} disabled={disabled}
              value={typeof values[key] === "string" ? values[key] : ""}
              onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} />
            <span>{meta.unit}</span>
          </div>
        )}
      </div>
    );
  }

  function renderPreferences() {
    if (loading) return <div className="ds-state-box" role="status"><span className="ds-spinner" />加载偏好设置中...</div>;
    if (loadError) return (
      <div className="ds-state-box ds-state-box--error" role="alert">
        加载偏好设置失败: {loadError}
        <button type="button" className="ds-link-btn" onClick={() => setReloadKey((value) => value + 1)}>重试</button>
      </div>
    );
    if (!hasLoaded || fields.length === 0) return <div className="ds-empty">当前服务未提供可调整的偏好设置</div>;
    return (
      <>
        <section className="ds-card ds-preferences">
          <header className="ds-card-head"><div><h3>模型输出</h3><p>选择是否使用模型接口的格式约束。</p></div></header>
          {renderField("llm.enable_structured_output")}
        </section>
        <section className="ds-card ds-preferences">
          <header className="ds-card-head"><div><h3>项目意图</h3><p>控制重复审查时如何使用已有的项目分析。</p></div></header>
          {renderField("review.enable_intent_cache")}
          {renderField("review.intent_cache_ttl_days")}
        </section>
        <section className="ds-card ds-preferences">
          <header className="ds-card-head"><div><h3>模型等待时间</h3><p>为模型响应和审查规划留出合适的时间。</p></div></header>
          {renderField("llm.call_timeout")}
          {renderField("llm.planner_timeout")}
          <details className="ds-disclosure ds-timeout-details">
            <summary>首段输出等待时间<span>适用于规划阶段</span></summary>
            {renderField("llm.planner_first_token_timeout")}
            {renderField("llm.planner_first_token_timeout_thinking")}
          </details>
        </section>
        {dirty ? <p className={`ds-preferences-note ${validationError ? "ds-preferences-note--error" : ""}`} role="status">
          {validationError ?? "更改将在保存后用于下一次审查。"}
        </p> : null}
      </>
    );
  }

  const activeGroup = GROUPS.find((item) => item.id === group) ?? GROUPS[0];
  const showSave = group === "capabilities" && hasLoaded && !loading && !loadError;

  return (
    <div id="page-config" className="page-view dc-settings-page" style={{ display: active ? "flex" : "none" }}>
      <div className="dc-settings">
        <aside className="ds-rail">
          <div className="ds-rail-heading"><strong>设置</strong></div>
          <nav aria-label="设置分组">
            {GROUPS.map((item) => {
              const GroupIcon = item.icon;
              return <button type="button" key={item.id}
                className={`ds-rail-item ${item.id === group ? "ds-rail-item--active" : ""}`}
                aria-current={item.id === group ? "page" : undefined} onClick={() => setGroup(item.id)}>
                <GroupIcon size={16} /><span>{item.label}</span>
              </button>;
            })}
          </nav>
        </aside>
        <div className="ds-main">
          <header className="ds-main-header">
            <div className="ds-main-title"><h1>{activeGroup.label}</h1>{dirty ? <span className="ds-dirty">未保存</span> : null}</div>
            {showSave ? <div className="ds-header-actions">
              {dirty ? <button type="button" className="ds-btn" disabled={saving} onClick={() => setValues({ ...savedValues })}>撤销更改</button> : null}
              <button type="button" className="ds-btn ds-btn--primary" disabled={saving || !dirty || Boolean(validationError)} onClick={() => void saveConfig()}>
                {saving ? "保存中..." : "保存更改"}
              </button>
            </div> : null}
          </header>
          <div className={`ds-content ${group === "models" ? "ds-content--flush" : ""}`}>
            {group === "models" ? <ModelServicesPanel active={active && group === "models"} />
              : group === "tools" ? <ReviewToolsPanel />
              : <div className="ds-capabilities">
                {renderPreferences()}
                <ScannerCapabilities active={active && group === "capabilities"} />
              </div>}
          </div>
        </div>
      </div>
    </div>
  );
}
