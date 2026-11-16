import { showConfirmDialog } from "../../lib/dialogs";
import { escapeHtml } from "../../lib/html";
import { scannerInstallGroups } from "./scannerInstallGuide";

export function showScannerHelp(detectedLanguages: string[]): void {
  const langs = Array.isArray(detectedLanguages) ? detectedLanguages : [];
  const normalizedLanguages = langs.map((language) => String(language).toLowerCase());
  const groups = scannerInstallGroups.map((group) => {
    const relevant = group.languages.some((language) => normalizedLanguages.includes(language));
    const tools = group.tools.map((tool) => `
      <div class="scanner-install-tool">
        <div class="scanner-install-tool-head">
          <strong>${escapeHtml(tool.name)}</strong>
          <a href="${escapeHtml(tool.url)}" target="_blank" rel="noopener noreferrer">官方安装说明 ↗</a>
        </div>
        <p>${escapeHtml(tool.description)}</p>
        ${tool.command ? `<pre><code>${escapeHtml(tool.command)}</code></pre>` : ""}
        ${tool.note ? `<p>${escapeHtml(tool.note)}</p>` : ""}
      </div>
    `).join("");
    return `<details class="scanner-install-group"${relevant || langs.length === 0 && group.languages.includes("python") ? " open" : ""}>
      <summary>${escapeHtml(group.title)}${relevant ? " · 当前项目" : ""}</summary>
      ${tools}
    </details>`;
  }).join("");

  showConfirmDialog({
    title: "扫描器安装与使用说明",
    content: `
      <div class="scanner-install-guide">
        <p>按项目语言准备需要的工具即可，无需安装全部扫描器。静态分析用于补充代码审查，可在审查页面选择是否运行。</p>
        <div class="scanner-install-note">
          <p><strong>安装到运行 DeltaConverge 后端服务的环境。</strong>远程访问时，请在服务端安装；Docker 部署时，请在容器镜像内安装。</p>
          <p>Windows 打包程序可能已内置部分 Python 工具，请先查看“工具状态”，仅补充未就绪的工具。源码运行时，请先激活启动服务所用的 Python 虚拟环境，再执行下方命令。</p>
        </div>
        ${langs.length > 0 ? `<p>当前项目语言：<strong>${langs.map((language) => escapeHtml(String(language))).join("、")}</strong>。对应语言的安装说明已展开，也可展开其他语言查看。</p>` : ""}
        <h4>选择语言，查看下载与安装方法</h4>
        ${groups}
        <h4>安装后如何确认</h4>
        <ol>
          <li>确保工具可从启动服务的环境中运行；需要添加 PATH 的工具，请把可执行文件所在目录加入 PATH。</li>
          <li>安装或修改 PATH 后，重启 DeltaConverge 后端服务；Windows 打包程序请退出后重新打开。</li>
          <li>进入“设置 → 常规 → 静态分析”，点击“重新检测”，展开“查看工具状态”确认结果。</li>
          <li>开始审查前，在审查页面勾选“静态分析”。部分工具还需要项目依赖、配置文件或构建产物，安装就绪后请按官方说明准备。</li>
        </ol>
        <h4>状态与常见问题</h4>
        <ul>
          <li><strong>已就绪</strong>：已检测到工具；实际扫描仍取决于项目配置和工具运行结果。</li>
          <li><strong>未安装 / 未就绪</strong>：服务未检测到可用工具。检查安装环境、PATH 和运行时版本；仅在项目内安装的工具未必能被服务发现。</li>
          <li><strong>已禁用</strong>：工具被扫描配置禁用，安装后还需要启用才能参与扫描。</li>
        </ul>
        <p>仪表盘按项目语言显示扫描器；点击“扫描器种类”可查看各工具状态。设置页可查看服务支持的全部工具。</p>
      </div>
    `,
    confirmText: "知了",
    showCancel: false,
  });
}
