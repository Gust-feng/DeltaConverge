import { useEffect, useState } from "react";

import { loadDashboardSummary } from "../dashboard/dashboardApi";
import { showScannerHelp } from "../dashboard/scannerHelp";
import { sortScannerLanguagesByLegacyOrder, type DashboardScanners } from "../dashboard/types";
import { RefreshIcon, ScanSearchIcon } from "./icons";

export function ScannerCapabilities({ active }: { active: boolean }) {
  const [scanners, setScanners] = useState<DashboardScanners | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void loadDashboardSummary(null, { force: true }).then((summary) => {
      if (cancelled) return;
      if (!summary.scanners) throw new Error("当前服务未返回扫描器信息");
      setScanners(summary.scanners);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [active, refreshKey]);

  const languages = sortScannerLanguagesByLegacyOrder(scanners?.languages ?? []);
  const available = languages.reduce((sum, language) => sum + language.available_count, 0);
  const total = languages.reduce((sum, language) => sum + language.total_count, 0);

  return (
    <section className="ds-card ds-scanner-capabilities">
      <header className="ds-card-head">
        <div><h3><ScanSearchIcon size={17} />静态分析</h3><p>使用已安装的代码扫描器补充审查。是否运行，在审查页面中选择。</p></div>
        <button type="button" className="ds-btn ds-btn--sm" disabled={loading} onClick={() => setRefreshKey((value) => value + 1)}>
          <RefreshIcon size={14} />{loading ? "检测中..." : "重新检测"}
        </button>
      </header>
      {loading ? <div className="ds-state-box" role="status"><span className="ds-spinner" />正在检查扫描工具...</div>
        : error ? <div className="ds-state-box ds-state-box--error" role="alert">检测失败: {error}</div>
        : total === 0 ? <div className="ds-empty">当前服务未提供扫描工具</div>
        : <>
          <div className="ds-scanner-summary"><strong>{available}<span> / {total}</span></strong><span>个工具已就绪</span></div>
          <details className="ds-disclosure">
            <summary>查看工具状态<span>{languages.length} 种语言</span></summary>
            <div className="ds-scanner-languages">
              {languages.map((language) => <div className="ds-scanner-language" key={language.language}>
                <div className="ds-scanner-language-head"><strong>{language.language}</strong><span>{language.available_count}/{language.total_count} 已就绪</span></div>
                {language.scanners?.map((scanner) => {
                  const ready = scanner.enabled !== false && scanner.available;
                  return <div className="ds-scanner-tool" key={scanner.name}>
                    <span>{scanner.name}</span><span className={ready ? "ds-tool-status ds-tool-status--ready" : "ds-tool-status"}>
                      {scanner.enabled === false ? "已禁用" : ready ? "已就绪" : "未就绪"}
                    </span>
                  </div>;
                })}
              </div>)}
            </div>
          </details>
        </>}
      <div className="ds-capability-footer"><span>按项目语言安装所需工具，重启服务后重新检测。</span><button type="button" className="ds-link-btn" onClick={() => showScannerHelp([])}>安装与使用说明</button></div>
    </section>
  );
}
