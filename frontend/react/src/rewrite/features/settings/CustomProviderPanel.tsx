import { useState } from "react";
import { ProviderLogo } from "./ProviderLogo";
import { ChevronDownIcon, EyeIcon, EyeOffIcon, PlusIcon, TrashIcon } from "./icons";

type Props = {
  label: string;
  baseUrl: string;
  protocol: string;
  apiKey: string;
  busy: boolean;
  onLabel: (value: string) => void;
  onBaseUrl: (value: string) => void;
  onProtocol: (value: string) => void;
  onApiKey: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
};

export function CustomProviderPanel(props: Props) {
  const [showKey, setShowKey] = useState(false);
  return (
    <div className="ds-detail">
      <header className="ds-detail-head">
        <ProviderLogo provider="custom" label="自定义服务" size="lg" />
        <input className="ds-custom-name" aria-label="服务名称" value={props.label}
          disabled={props.busy} onChange={(event) => props.onLabel(event.target.value)} placeholder="自定义服务" />
        <button type="button" className="ds-icon-btn ds-provider-remove" title="取消添加服务"
          disabled={props.busy} onClick={props.onCancel}><TrashIcon size={17} /></button>
      </header>
      <div className="ds-divider" />
      <section className="ds-section">
        <label className="ds-label" htmlFor="ds-custom-key">API Key</label>
        <div className="ds-key-control">
          <div className="ds-input-wrap">
            <input id="ds-custom-key" className="ds-input ds-input--key" autoComplete="off"
              type={showKey ? "text" : "password"} value={props.apiKey} placeholder="请输入密钥"
              disabled={props.busy} onChange={(event) => props.onApiKey(event.target.value)} />
            <button type="button" className="ds-input-icon" title={showKey ? "隐藏密钥" : "显示密钥"}
              onClick={() => setShowKey((value) => !value)}>{showKey ? <EyeOffIcon size={17} /> : <EyeIcon size={17} />}</button>
          </div>
        </div>
        <div className="ds-field-grid">
          <div className="ds-field">
            <label className="ds-label" htmlFor="ds-custom-url">Base URL</label>
            <input id="ds-custom-url" className="ds-input" type="url" value={props.baseUrl}
              placeholder="https://api.example.com/v1" disabled={props.busy}
              onChange={(event) => props.onBaseUrl(event.target.value)} />
          </div>
          <div className="ds-field">
            <label className="ds-label" htmlFor="ds-custom-protocol">协议</label>
            <div className="ds-select-wrap">
              <select id="ds-custom-protocol" className="ds-input ds-select" value={props.protocol}
                disabled={props.busy} onChange={(event) => props.onProtocol(event.target.value)}>
                <option value="chat_completions">/chat/completions</option>
                <option value="responses">/responses</option>
              </select>
              <ChevronDownIcon size={16} />
            </div>
          </div>
        </div>
        {props.baseUrl.trim() ? <div className="ds-connection-actions">
          <button type="button" className="ds-btn ds-btn--primary" disabled={props.busy}
            onClick={props.onSave}>{props.busy ? "保存中…" : "保存服务"}</button>
        </div> : null}
      </section>
      <div className="ds-divider" />
      <section className="ds-section ds-section--models">
        <div className="ds-model-head">
          <div className="ds-model-heading"><span>模型列表</span></div>
          <div className="ds-model-tools">
            <button type="button" className="ds-btn" disabled title="请先保存服务连接"><PlusIcon size={16} />添加模型</button>
            <button type="button" className="ds-btn" disabled title="请先保存服务连接">获取模型</button>
          </div>
        </div>
        <div className="ds-empty ds-empty--draft"><PlusIcon size={25} /><span>暂无可用的模型</span></div>
      </section>
    </div>
  );
}
