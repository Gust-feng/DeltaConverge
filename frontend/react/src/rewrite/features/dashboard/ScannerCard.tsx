import { useState } from "react";

import { Icon } from "../../components/Icon";
import { showScannerHelp } from "./scannerHelp";
import { sortScannerLanguagesByLegacyOrder } from "./types";
import type { DashboardScannerLanguage, DashboardScanners } from "./types";

type ScannerViewMode = "summary" | "detail";

function renderSummaryRows(languages: DashboardScannerLanguage[]) {
  return languages.map((language, index) => {
    const ratio = language.total_count > 0 ? language.available_count / language.total_count : 0;
    const colorClass = ratio === 1 ? "success" : ratio > 0 ? "warning" : "error";
    return (
      <div className="stat-row" key={`${language.language}-${index}`}>
        <span className="label" style={{ width: "100px" }}>
          {language.language}
        </span>
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "0.5rem" }}>
          <div style={{ width: "60px", height: "6px", background: "#f1f5f9", borderRadius: "3px", overflow: "hidden" }}>
            <div
              style={{
                width: `${ratio * 100}%`,
                height: "100%",
                background: `var(--${colorClass}-color, #10b981)`,
              }}
            />
          </div>
          <span className="value" style={{ minWidth: "30px", textAlign: "right" }}>
            {`${language.available_count}/${language.total_count}`}
          </span>
        </div>
      </div>
    );
  });
}

function renderDetailRows(languages: DashboardScannerLanguage[]) {
  const rows: JSX.Element[] = [];
  languages.forEach((language, languageIndex) => {
    const scanners = Array.isArray(language.scanners) ? language.scanners : [];
    scanners.forEach((scanner, scannerIndex) => {
      const statusLabel = scanner.available ? (
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>已就绪</span>
      ) : !scanner.enabled ? (
        <span style={{ fontSize: "0.75rem", color: "#f59e0b" }}>已禁用</span>
      ) : (
        <span style={{ fontSize: "0.75rem", color: "#ef4444" }}>未安装</span>
      );
      rows.push(
        <div className="stat-row" key={`${language.language}-${languageIndex}-${scanner.name}-${scannerIndex}`}>
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className="value" style={{ fontWeight: 600 }}>
              {scanner.name}
            </span>
            <span
              className="badge"
              style={{
                fontSize: "0.7rem",
                padding: "0.1rem 0.4rem",
                background: "#f1f5f9",
                color: "#64748b",
              }}
            >
              {language.language}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            {statusLabel}
            {scanner.available ? (
              <Icon name="check" plain style={{ color: "#10b981" }} />
            ) : (
              <Icon name="x" plain style={{ color: "#ef4444" }} />
            )}
          </div>
        </div>
      );
    });
  });
  return rows;
}

export function ScannerCard({
  scanners,
  detectedLanguages,
}: {
  scanners: DashboardScanners | null | undefined;
  detectedLanguages: string[];
}) {
  const [viewMode, setViewMode] = useState<ScannerViewMode>("summary");

  const languages = Array.isArray(scanners?.languages) ? scanners?.languages ?? [] : [];
  const orderedLanguages = sortScannerLanguagesByLegacyOrder(languages);
  const used =
    detectedLanguages.length > 0
      ? orderedLanguages.filter((language) => detectedLanguages.includes(language.language))
      : orderedLanguages;

  let totalAvailable = 0;
  let totalCount = 0;
  used.forEach((language) => {
    totalAvailable += language.available_count || 0;
    totalCount += language.total_count || 0;
  });

  const rows = viewMode === "summary" ? renderSummaryRows(used) : renderDetailRows(used);

  return (
    <div className="card">
      <div className="card-header">
        <h3 style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          代码扫描器
          <button id="scannerHelpBtn" className="hints-help-btn" onClick={() => showScannerHelp(detectedLanguages)}>
            <span className="help-text">?</span>
          </button>
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span id="scanner-summary-badge" className="badge">
            {scanners ? `${totalAvailable}/${totalCount}` : "0"}
          </span>
          <button
            id="scanner-toggle-btn"
            className="btn-text"
            onClick={() => setViewMode((mode) => (mode === "summary" ? "detail" : "summary"))}
          >
            扫描器种类
          </button>
        </div>
      </div>
      <div className="card-body compact-list" id="scanner-status-content">
        {scanners ? (
          rows.length > 0 ? (
            rows
          ) : (
            <div className="empty-state" style={{ padding: "1rem", fontSize: "0.85rem" }}>
              无相关扫描器
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}
