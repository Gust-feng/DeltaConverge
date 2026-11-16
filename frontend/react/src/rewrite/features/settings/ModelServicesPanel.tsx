import { useCallback, useEffect, useMemo, useState } from "react";

import { ModelPickerPanel } from "./ModelPickerPanel";
import { ModelAdvancedSettings } from "./ModelAdvancedSettings";
import { CustomProviderPanel } from "./CustomProviderPanel";
import { ProviderLogo } from "./ProviderLogo";
import { PROVIDER_CATALOG, providerOrder, providerDescription } from "./providerCatalog";
import {
  AlertIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  EyeIcon,
  EyeOffIcon,
  PlusIcon,
  SearchIcon,
  TrashIcon,
  XIcon,
} from "./icons";
import {
  addModel,
  createProvider,
  deleteModel,
  deleteProvider,
  getProviderKeys,
  isAddedProvider,
  setProviderDisabled,
  setProviderKey,
  updateProvider,
  type ProviderInfo,
} from "../../lib/api";
import { showConfirmDialog } from "../../lib/dialogs";
import { escapeHtml } from "../../lib/html";
import { showToast } from "../../lib/toast";
import { useAppStore } from "../../state/appStore";
import { refreshSavedModels } from "../../state/modelOptions";
import { modelCapabilityLabel } from "../../lib/modelSelection";
import type { ProviderKeyInfo } from "../../types";

const PROTOCOL_LABELS: Record<string, string> = {
  chat_completions: "/chat/completions",
  responses: "/responses",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * 模型服务面板：服务商列表 + 服务详情。
 * 与旧版一致，数据加载后同步全局模型状态，供顶部模型选择器立即生效。
 */
export function ModelServicesPanel({ active }: { active: boolean }) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [keys, setKeys] = useState<ProviderKeyInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"key" | "model" | "provider" | "connection" | null>(null);
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [protocol, setProtocol] = useState("chat_completions");

  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [customFormOpen, setCustomFormOpen] = useState(false);
  const [modelQuery, setModelQuery] = useState("");

  const [keyValue, setKeyValue] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [addingModel, setAddingModel] = useState(false);
  const [newModelName, setNewModelName] = useState("");
  const [advancedModel, setAdvancedModel] = useState<string | null>(null);

  const [customLabel, setCustomLabel] = useState("");
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [customProtocol, setCustomProtocol] = useState("chat_completions");
  const [customApiKey, setCustomApiKey] = useState("");

  const activeModel = useAppStore((state) => state.model);

  // 与旧版 loadUnifiedData 一致：并行拉取，成功后同步全局模型状态。
  const load = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoading(true);
    setLoadError(null);

    const [providerResult, keyResult] = await Promise.allSettled([
      refreshSavedModels(),
      getProviderKeys(),
    ]);

    if (providerResult.status === "rejected") {
      console.error("Failed to load providers", providerResult.reason);
      setLoadError(errorMessage(providerResult.reason));
      setLoading(false);
      return;
    }

    if (!providerResult.value) {
      setLoading(false);
      return;
    }

    const providerItems = providerResult.value
      .map((item) => ({
        ...item,
        label: item.custom ? item.label : PROVIDER_CATALOG[item.id]?.label ?? item.label,
      }))
      .sort((a, b) => providerOrder(a.id) - providerOrder(b.id));
    const keyData = keyResult.status === "fulfilled" ? keyResult.value : { providers: [] };

    setProviders(providerItems);
    setKeys(Array.isArray(keyData.providers) ? keyData.providers : []);

    const store = useAppStore.getState();
    const connections = providerItems.filter(isAddedProvider);
    if (connections.length === 0) setCatalogOpen(true);
    setSelectedProvider((current) =>
      current === "__custom_draft__" || current && connections.some((item) => item.id === current)
        ? current
        : connections.find((item) => store.model?.startsWith(`${item.id}:`))?.id
          ?? connections[0]?.id ?? null
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    if (active) void load(true);
  }, [active, load]);

  // 重复点击当前导航时旧版会重新执行 loader；这里保持同样的刷新语义。
  useEffect(() => {
    if (!active) return;
    const handler = (event: Event) => {
      if ((event as CustomEvent).detail === "config") void load(true);
    };
    window.addEventListener("dc:reload-page", handler);
    return () => window.removeEventListener("dc:reload-page", handler);
  }, [active, load]);

  useEffect(() => {
    if (!active) {
      setCatalogOpen(false);
      setAddingModel(false);
      setDiscoveryOpen(false);
    }
  }, [active]);

  // Esc 先收起目录/添加行，不关闭外层设置弹窗。
  useEffect(() => {
    if (!active) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (discoveryOpen) {
        event.stopPropagation();
        if (!busy) setDiscoveryOpen(false);
        return;
      }
      if (catalogOpen) {
        event.stopPropagation();
        setCatalogOpen(false);
        return;
      }
      if (addingModel) {
        event.stopPropagation();
        setAddingModel(false);
        setNewModelName("");
      }
    };
    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, [active, addingModel, catalogOpen, discoveryOpen, busy]);

  const provider = selectedProvider ? providers.find((item) => item.id === selectedProvider) : undefined;
  const keyInfo = provider ? keys.find((item) => item.provider === provider.id) : undefined;
  const configured = Boolean(keyInfo?.configured);
  const providerModels = provider?.models ?? [];
  const providerDetails = provider?.model_details ?? [];
  const visibleProviders = providers.filter(isAddedProvider);
  const connectionDirty = Boolean(provider && (
    baseUrl.trim() !== (provider.base_url ?? "") || protocol !== (provider.protocol || "chat_completions")
  ));

  useEffect(() => {
    setKeyValue("");
    setShowKey(false);
    setAddingModel(false);
    setNewModelName("");
    setModelQuery("");
    setDiscoveryOpen(false);
    setAdvancedModel(null);
  }, [provider?.id]);

  useEffect(() => {
    setBaseUrl(provider?.base_url ?? "");
    setProtocol(provider?.protocol || "chat_completions");
  }, [provider?.id, provider?.base_url, provider?.protocol]);

  const filteredModels = useMemo(() => {
    const query = modelQuery.trim().toLowerCase();
    if (!query) return providerModels;
    return providerModels.filter((model) => model.toLowerCase().includes(query));
  }, [modelQuery, providerModels]);

  const catalogProviders = useMemo(() => {
    const query = catalogQuery.trim().toLowerCase();
    const source = providers.filter((item) => !item.custom);
    if (!query) return source;
    return source.filter(
      (item) => item.label.toLowerCase().includes(query) || item.id.toLowerCase().includes(query)
    );
  }, [catalogQuery, providers]);

  function selectProvider(providerId: string) {
    if (busy) return;
    setSelectedProvider(providerId);
    setCatalogOpen(false);
    setCatalogOpen(false);
    setKeyValue("");
    setShowKey(false);
    setAddingModel(false);
    setNewModelName("");
    setModelQuery("");
    setDiscoveryOpen(false);
  }

  function openCatalog() {
    if (busy) return;
    setDiscoveryOpen(false);
    setCatalogQuery("");
    setCatalogOpen(true);
  }

  async function chooseCatalogProvider(item: ProviderInfo) {
    if (busy) return;
    setBusy("provider");
    try {
      if (item.disabled || !(item.added || item.configured)) {
        await setProviderDisabled(item.id, false);
      }
      await load(false);
      setSelectedProvider(item.id);
      setKeyValue("");
      setShowKey(false);
      setModelQuery("");
      setCatalogOpen(false);
    } catch (error) {
      showToast("添加服务失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setBusy(null);
    }
  }

  async function saveKey() {
    if (!provider || busy) return;
    const value = keyValue.trim();
    if (!value) {
      showToast("请输入密钥", "warning", { floating: true });
      return;
    }

    setBusy("key");
    try {
      await setProviderKey(provider.id, value);
      showToast("密钥已保存", "success", { floating: true });
      setKeyValue("");
      setShowKey(false);
      await load(false);
    } catch (error) {
      showToast("保存失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setBusy(null);
    }
  }

  function clearKey() {
    if (!provider) return;
    const providerId = provider.id;

    showConfirmDialog({
      content: "确定要清除该密钥吗？",
      onConfirm: async () => {
        setBusy("key");
        try {
          await setProviderKey(providerId, "");
          showToast("密钥已清除", "success", { floating: true });
          await load(false);
        } catch (error) {
          showToast("清除失败: " + errorMessage(error), "error", { floating: true });
        } finally {
          setBusy(null);
        }
      },
    });
  }

  async function confirmAddModel() {
    if (!provider || busy) return;
    const name = newModelName.trim();
    if (!name) {
      showToast("请输入模型名称", "warning", { floating: true });
      return;
    }

    setBusy("model");
    try {
      await addModel(provider.id, name);
      showToast("模型已添加", "success", { floating: true });
      setNewModelName("");
      setAddingModel(false);
      await load(false);
    } catch (error) {
      showToast("添加失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setBusy(null);
    }
  }

  function requestDeleteModel(modelName: string) {
    if (!provider) return;
    const providerId = provider.id;

    showConfirmDialog({
      content: `确认删除模型 ${escapeHtml(modelName)}?`,
      onConfirm: async () => {
        setBusy("model");
        try {
          await deleteModel(providerId, modelName);
          showToast("模型已删除", "success", { floating: true });
          await load(false);
        } catch (error) {
          showToast("删除失败: " + errorMessage(error), "error", { floating: true });
        } finally {
          setBusy(null);
        }
      },
    });
  }

  async function copyModelId(modelName: string) {
    try {
      await navigator.clipboard.writeText(modelName);
      showToast("已复制模型 ID", "success", { floating: true });
    } catch (error) {
      showToast("复制失败: " + errorMessage(error), "error", { floating: true });
    }
  }

  async function saveConnection() {
    if (!provider || busy || !connectionDirty) return;
    const updates: { base_url?: string; protocol?: string } = {};
    if (baseUrl.trim() !== (provider.base_url ?? "")) updates.base_url = baseUrl.trim();
    if (protocol !== (provider.protocol || "chat_completions")) updates.protocol = protocol;
    setBusy("connection");
    try {
      await updateProvider(provider.id, updates);
      showToast("连接设置已保存", "success", { floating: true });
      await load(false);
    } catch (error) {
      showToast("保存失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setBusy(null);
    }
  }

  function resetCustomProviderForm() {
    setCustomLabel("");
    setCustomBaseUrl("");
    setCustomProtocol("chat_completions");
    setCustomApiKey("");
  }

  async function saveCustomProvider() {
    setBusy("provider");
    try {
      const created = await createProvider({
        label: customLabel.trim() || "自定义服务",
        base_url: customBaseUrl,
        protocol: customProtocol,
        api_key: customApiKey || undefined,
      });
      showToast("服务已添加", "success", { floating: true });
      resetCustomProviderForm();
      setCustomFormOpen(false);
      setCatalogOpen(false);
      await load(false);
      setSelectedProvider(created.id);
    } catch (error) {
      showToast("添加失败: " + errorMessage(error), "error", { floating: true });
    } finally {
      setBusy(null);
    }
  }

  function requestDeleteProvider() {
    if (!provider) return;
    const providerId = provider.id;
    const action = provider.custom ? "删除" : "移除";
    showConfirmDialog({
      content: `确认${action}服务「${escapeHtml(provider.label)}」吗？`,
      onConfirm: async () => {
        setBusy("provider");
        try {
          if (provider.custom) await deleteProvider(providerId);
          else await setProviderDisabled(providerId, true);
          showToast(provider.custom ? "服务已删除" : "服务已移除", "success", { floating: true });
          setSelectedProvider(null);
          await load(false);
        } catch (error) {
          showToast(`${action}失败: ` + errorMessage(error), "error", { floating: true });
        } finally {
          setBusy(null);
        }
      },
    });
  }

  function renderCatalog() {
    return (
      <div className="ds-catalog">
        <header className="ds-catalog-head">
          <div>
            <h2>添加服务</h2>
          </div>
          <button type="button" className="ds-icon-btn" title="关闭" onClick={() => setCatalogOpen(false)}>
            <XIcon size={19} />
          </button>
        </header>

        <div className="ds-catalog-tools">
          <button type="button" className="ds-btn ds-custom-trigger" onClick={() => {
            setCustomLabel((value) => value || "自定义服务");
            setCustomFormOpen(true);
            setSelectedProvider("__custom_draft__");
            setCatalogOpen(false);
            setDiscoveryOpen(false);
          }}>
            <PlusIcon size={16} />自定义服务
          </button>
          <div className="ds-search ds-search--lg">
            <SearchIcon size={17} />
            <input
              type="text"
              placeholder="搜索厂商或平台"
              aria-label="搜索厂商或平台"
              value={catalogQuery}
              onChange={(event) => setCatalogQuery(event.target.value)}
            />
            {catalogQuery ? (
              <button type="button" className="ds-search-clear" title="清空" onClick={() => setCatalogQuery("")}>
                <XIcon size={14} />
              </button>
            ) : null}
          </div>
        </div>

        <div className="ds-catalog-grid">
          {catalogProviders.map((item) => {
            const itemKey = keys.find((key) => key.provider === item.id);
            return (
              <button
                type="button"
                className="ds-catalog-card"
                key={item.id}
                disabled={Boolean(busy)}
                onClick={() => void chooseCatalogProvider(item)}
              >
                <ProviderLogo provider={item.id} label={item.label} size="lg" />
                <span className="ds-catalog-meta">
                  <span className="ds-catalog-name">{item.label}</span>
                  <span className="ds-catalog-sub">{providerDescription(item.id)}</span>
                </span>
                {!item.disabled && (item.added || itemKey?.configured) ? (
                  <span className="ds-config-tag">已添加</span>
                ) : null}
                <ChevronRightIcon className="ds-catalog-chevron" size={18} />
              </button>
            );
          })}
          {catalogProviders.length === 0 ? <div className="ds-empty">没有匹配的服务</div> : null}
        </div>


      </div>
    );
  }

  function renderDetail() {
    if (!provider) return <div className="ds-empty ds-empty--center">请选择左侧服务商进行配置</div>;

    return (
      <div className="ds-detail">
        <header className="ds-detail-head">
          <ProviderLogo provider={provider.id} label={provider.label} size="lg" />
          <div className="ds-detail-heading">
            <h2>{provider.label}</h2>
            <span className="ds-detail-id">{provider.custom ? "自定义兼容服务" : `${provider.label} · ${providerDescription(provider.id)}`}</span>
          </div>
          <span className={`ds-status ${configured ? "ds-status--on" : ""}`}>
            <span className="ds-status-dot" />
            {configured ? "已配置" : "未配置"}
          </span>
          <button
            type="button"
            className="ds-icon-btn ds-provider-remove"
            title={provider.custom ? "删除服务" : "移除服务"}
            disabled={Boolean(busy)}
            onClick={requestDeleteProvider}
          >
            <TrashIcon size={16} />
          </button>
        </header>

        <div className="ds-divider" />

        <section className="ds-section">
          <label className="ds-label" htmlFor="ds-provider-key">
            API Key
          </label>
          <div className="ds-key-control">
            <div className="ds-input-wrap">
              <input
                id="ds-provider-key"
                className="ds-input"
                type={showKey ? "text" : "password"}
                autoComplete="new-password"
                placeholder={configured ? `已保存 ${keyInfo?.masked ?? ""}` : "输入 API Key..."}
                value={keyValue}
                onChange={(event) => setKeyValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveKey();
                }}
              />
              <button
                type="button"
                className="ds-input-icon"
                title={showKey ? "隐藏密钥" : "显示密钥"}
                onClick={() => setShowKey((current) => !current)}
              >
                {showKey ? <EyeOffIcon size={17} /> : <EyeIcon size={17} />}
              </button>
            </div>
            <button
              type="button"
              className={`ds-btn ${keyValue.trim() ? "ds-btn--primary" : ""}`}
              disabled={Boolean(busy) || !keyValue.trim()}
              onClick={() => void saveKey()}
            >
              保存
            </button>
            {configured ? (
              <button type="button" className="ds-btn" disabled={Boolean(busy)} onClick={clearKey}>
                清除
              </button>
            ) : null}
          </div>

          <div className="ds-field-grid">
            <div className="ds-field">
              <label className="ds-label" htmlFor="ds-provider-base-url">
                Base URL
              </label>
              <input
                id="ds-provider-base-url"
                className="ds-input"
                type="text"
                disabled={Boolean(busy)}
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div className="ds-field">
              <label className="ds-label" htmlFor="ds-provider-protocol">
                协议
              </label>
              <div className="ds-select-wrap">
                <select
                  id="ds-provider-protocol"
                  className="ds-input ds-select"
                  disabled={Boolean(busy)}
                  value={protocol}
                  onChange={(event) => setProtocol(event.target.value)}
                >
                  <option value="chat_completions">{PROTOCOL_LABELS.chat_completions}</option>
                  <option value="responses">{PROTOCOL_LABELS.responses}</option>
                </select>
                <ChevronDownIcon size={16} />
              </div>
            </div>
          </div>
          {connectionDirty ? (
            <div className="ds-connection-actions">
              <span className="ds-dirty">未保存</span>
              <button type="button" className="ds-btn" disabled={Boolean(busy)} onClick={() => {
                setBaseUrl(provider.base_url ?? "");
                setProtocol(provider.protocol || "chat_completions");
              }}>取消修改</button>
              <button type="button" className="ds-btn ds-btn--primary" disabled={Boolean(busy) || !baseUrl.trim()} onClick={() => void saveConnection()}>
                {busy === "connection" ? "保存中…" : "保存连接设置"}
              </button>
            </div>
          ) : null}
        </section>

        <div className="ds-divider" />

        <section className="ds-section ds-section--models">
          <div className="ds-model-head">
            <div className="ds-model-heading">
              <span>模型</span>
              <span className="ds-count">{providerModels.length}</span>
            </div>
            <div className="ds-model-tools">
              <div className="ds-search ds-search--sm">
                <SearchIcon size={15} />
                <input
                  type="text"
                  placeholder="搜索模型"
                  value={modelQuery}
                  onChange={(event) => setModelQuery(event.target.value)}
                />
              </div>
              <button
                type="button"
                className="ds-btn"
                disabled={Boolean(busy) || !configured || connectionDirty || provider.disabled}
                title={connectionDirty ? "请先保存连接设置" : !configured ? "请先保存 API Key" : undefined}
                onClick={() => setDiscoveryOpen(true)}
              >
                <SearchIcon size={15} />
                获取模型
              </button>
              <button
                type="button"
                className="ds-btn"
                disabled={Boolean(busy)}
                onClick={() => setAddingModel(true)}
              >
                <PlusIcon size={15} />
                添加模型
              </button>
            </div>
          </div>

          {addingModel ? (
            <div className="ds-model-add">
              <input
                className="ds-input"
                type="text"
                autoFocus
                placeholder="输入模型 ID，例如 deepseek-chat"
                value={newModelName}
                onChange={(event) => setNewModelName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void confirmAddModel();
                  if (event.key === "Escape") {
                    setAddingModel(false);
                    setNewModelName("");
                  }
                }}
              />
              <button
                type="button"
                className="ds-icon-btn ds-icon-btn--confirm"
                title="确认添加"
                disabled={Boolean(busy)}
                onClick={() => void confirmAddModel()}
              >
                <CheckIcon size={16} />
              </button>
              <button
                type="button"
                className="ds-icon-btn"
                title="取消"
                onClick={() => {
                  setAddingModel(false);
                  setNewModelName("");
                }}
              >
                <XIcon size={16} />
              </button>
            </div>
          ) : null}

          <div className="ds-model-list">
            {filteredModels.map((model) => {
              const isActiveModel = activeModel === `${provider.id}:${model}`;
              return (
                <div className="ds-model-entry" key={model}>
                <div className={`ds-model-row ${isActiveModel ? "ds-model-row--active" : ""}`}>
                  <ProviderLogo provider={provider.id} label={provider.label} size="xs" />
                  <span className="ds-model-name" title={model}>
                    {model}
                  </span>
                  {(() => {
                    const capability = modelCapabilityLabel(providerDetails.find((detail) => detail.id === model)?.capabilities as Record<string, unknown> | undefined);
                    return capability ? <span className="ds-model-capability">{capability}</span> : null;
                  })()}
                  {isActiveModel ? <span className="ds-model-tag">当前</span> : null}
                  <div className="ds-model-actions">
                    <button type="button" className="ds-link-btn ds-model-advanced-toggle"
                      aria-label={`${model} 高级设置`} aria-expanded={advancedModel === model}
                      disabled={Boolean(busy)} onClick={() => setAdvancedModel((current) => current === model ? null : model)}>
                      高级设置
                    </button>
                    <button
                      type="button"
                      className="ds-icon-btn"
                      title="复制模型 ID"
                      onClick={() => void copyModelId(model)}
                    >
                      <CopyIcon size={15} />
                    </button>
                    <button
                      type="button"
                      className="ds-icon-btn ds-model-delete"
                      title="删除模型"
                      disabled={Boolean(busy)}
                      onClick={() => requestDeleteModel(model)}
                    >
                      <TrashIcon size={15} />
                    </button>
                  </div>
                </div>
                {advancedModel === model ? <ModelAdvancedSettings provider={provider.id} model={model}
                  onSaved={() => load(false)} onClose={() => setAdvancedModel(null)} /> : null}
                </div>
              );
            })}
            {filteredModels.length === 0 ? (
              <div className="ds-empty ds-empty--models">
                <span>{modelQuery.trim() ? "没有匹配的模型" : "暂无模型"}</span>
                {!modelQuery.trim() ? <small>点击「添加模型」手动添加模型 ID</small> : null}
              </div>
            ) : null}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="ds-model-services">
      <aside className="ds-provider-pane">
        <div className="ds-provider-list">
          {loading && providers.length === 0 ? (
            <div className="ds-state-box">
              <span className="ds-spinner" />
            </div>
          ) : loadError ? (
            <div className="ds-state-box ds-state-box--error">
              <AlertIcon size={18} />
              <span>加载失败</span>
              <button type="button" className="ds-link-btn" onClick={() => void load(true)}>
                重试
              </button>
            </div>
          ) : (
            visibleProviders.map((item) => {
              const itemKey = keys.find((key) => key.provider === item.id);
              const isActive = item.id === selectedProvider && !catalogOpen;
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`ds-provider-row ${isActive ? "ds-provider-row--active" : ""}`}
                  onClick={() => selectProvider(item.id)}
                >
                  <ProviderLogo provider={item.id} label={item.label} size="md" />
                  <span className="ds-provider-name">{item.label}</span>
                  {!item.disabled ? (
                    <span
                      className={`ds-config-dot ${itemKey?.configured ? "ds-config-dot--on" : ""}`}
                      title={itemKey?.configured ? "已配置" : "未配置"}
                    />
                  ) : null}
                </button>
              );
            })
          )}
        {customFormOpen ? (
          <button type="button" className={`ds-provider-row ${selectedProvider === "__custom_draft__" && !catalogOpen ? "ds-provider-row--active" : ""}`}
            onClick={() => { setSelectedProvider("__custom_draft__"); setCatalogOpen(false); setDiscoveryOpen(false); }}>
            <ProviderLogo provider="custom" label="自定义服务" size="md" />
            <span className="ds-provider-name">{customLabel || "自定义服务"}</span>
          </button>
        ) : null}
        </div>
        <div className="ds-provider-footer">
          <button type="button" className="ds-add-provider" onClick={openCatalog}>
            <PlusIcon size={16} />
            添加服务
          </button>
        </div>
      </aside>

      <section className={`ds-detail-pane ${discoveryOpen && !catalogOpen ? "ds-detail-pane--picker" : ""}`}>
        {catalogOpen ? renderCatalog() : customFormOpen && selectedProvider === "__custom_draft__" ? (
          <CustomProviderPanel label={customLabel} baseUrl={customBaseUrl} protocol={customProtocol}
            apiKey={customApiKey} busy={Boolean(busy)} onLabel={setCustomLabel} onBaseUrl={setCustomBaseUrl}
            onProtocol={setCustomProtocol} onApiKey={setCustomApiKey} onSave={() => void saveCustomProvider()}
            onCancel={() => {
              setCustomFormOpen(false);
              resetCustomProviderForm();
              setSelectedProvider(visibleProviders[0]?.id ?? null);
              if (visibleProviders.length === 0) setCatalogOpen(true);
            }} />
        ) : active && discoveryOpen && provider ? (
          <ModelPickerPanel
            key={provider.id}
            provider={provider}
            onClose={() => setDiscoveryOpen(false)}
            onSaved={() => load(false)}
            onSavingChange={(saving) => setBusy(saving ? "model" : null)}
          />
        ) : renderDetail()}
      </section>
    </div>
  );
}
