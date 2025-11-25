const streamBox = document.getElementById("stream");
const tokenHud = document.getElementById("token-hud");
const statusHud = document.getElementById("status");
const promptInput = document.getElementById("prompt");
const modelSelect = document.getElementById("model");
const toolsBox = document.getElementById("tools");
const projectRootInput = document.getElementById("project-root");
const autoApprove = document.getElementById("auto-approve");
const startBtn = document.getElementById("start");
const refreshBtn = document.getElementById("refresh-tools");

const toolsState = { tools: [] };
let isRunning = false;
const toolNameCache = {};

async function fetchTools() {
  try {
    const res = await fetch("/api/tools");
    const data = await res.json();
    toolsState.tools = data.tools || [];
    renderTools();
  } catch (e) {
    console.error("tools fetch failed", e);
  }
}

function renderTools() {
  toolsBox.innerHTML = "";
  toolsState.tools.forEach((name) => {
    const id = `tool-${name}`;
    const label = document.createElement("label");
    label.className = "checkbox";
    label.innerHTML = `
      <input type="checkbox" id="${id}" value="${name}" checked />
      <span>${name}</span>
    `;
    toolsBox.appendChild(label);
  });
}

function getSelectedTools() {
  return Array.from(toolsBox.querySelectorAll("input[type=checkbox]"))
    .filter((el) => el.checked)
    .map((el) => el.value);
}

function appendBubble(text, cls = "assistant") {
  const div = document.createElement("div");
  div.className = `bubble ${cls}`;
  div.textContent = text;
  streamBox.appendChild(div);
  streamBox.scrollTop = streamBox.scrollHeight;
  return div;
}

function appendToolBubble(html) {
  const div = document.createElement("div");
  div.className = "bubble tool";
  div.innerHTML = html;
  streamBox.appendChild(div);
  streamBox.scrollTop = streamBox.scrollHeight;
}

let currentBubble = null;
function appendDelta(text) {
  if (!text) return;
  // 将增量累积到当前回答气泡，避免一行一个气泡
  if (!currentBubble || !currentBubble.className.includes("assistant")) {
    currentBubble = appendBubble("", "assistant");
  }
  currentBubble.textContent += text;
  streamBox.scrollTop = streamBox.scrollHeight;
}

function setStatus(text, muted = false) {
  statusHud.textContent = text;
  statusHud.className = muted ? "pill muted" : "pill";
}

function resetUI() {
  streamBox.innerHTML = "";
  tokenHud.textContent = "Tokens: -";
  setStatus("Idle", true);
  currentBubble = null;
  usageAgg.reset();
}

async function startReview() {
  if (isRunning) return;
  const prompt = promptInput.value.trim();
  if (!prompt) {
    alert("Prompt 不能为空");
    return;
  }
  const model = modelSelect.value;
  const tools = getSelectedTools();
  const projectRoot = projectRootInput.value.trim();
  isRunning = true;
  startBtn.disabled = true;
  resetUI();
  setStatus("Running...");

  let buffer = "";

  try {
    const res = await fetch("/api/review/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        model,
        tools,
        projectRoot: projectRoot || null,
        autoApprove: autoApprove.checked,
      }),
    });

    if (!res.ok || !res.body) {
      throw new Error(`请求失败: ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const chunk of parts) {
        const line = chunk.trim();
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        handleEvent(JSON.parse(payload));
      }
    }
  } catch (err) {
    console.error(err);
    appendBubble(`错误: ${err.message}`, "error");
  } finally {
    isRunning = false;
    startBtn.disabled = false;
    setStatus("Idle", true);
    currentBubble = null;
  }
}

function handleEvent(evt) {
  const type = evt.type || "delta";
  if (type === "delta") {
    const text = evt.content_delta || "";
    if (!currentBubble || !currentBubble.className.includes("assistant")) {
      currentBubble = appendBubble("", "assistant");
    }
    appendDelta(text);
    // 如果有工具调用分片，提示一次
    const tcd = evt.tool_calls_delta;
    if (Array.isArray(tcd) && tcd.length) {
      tcd.forEach((call) => {
        const key = call?.id ?? call?.index ?? `idx_${Math.random()}`;
        const reportedName = call?.function?.name || call?.name;
        if (reportedName) {
          toolNameCache[key] = reportedName;
        }
        const name = reportedName || toolNameCache[key] || "tool";
        appendBubble(`准备调用工具: ${name}`, "tool");
      });
    }
    if (evt.usage || evt.call_usage) {
      updateTokens(evt);
    }
  } else if (type === "usage_summary") {
    if (evt.usage || evt.call_usage) updateTokens(evt);
  } else if (type === "tool_result") {
    renderToolResult(evt);
  } else if (type === "final") {
    // 最终内容已经通过 delta 流式累积，这里只提示完成
    currentBubble = null;
    appendBubble("完成", "final");
  } else if (type === "error") {
    appendBubble(`错误: ${evt.message || "未知错误"}`, "error");
  }
}

const usageAgg = {
  callUsage: new Map(),
  reset() {
    this.callUsage.clear();
  },
  update(usage, callIndex) {
    const toInt = (v) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    };
    const inTok = toInt(usage.input_tokens || usage.prompt_tokens);
    const outTok = toInt(usage.output_tokens || usage.completion_tokens);
    const totalTok = toInt(usage.total_tokens);
    const idx = Number.isFinite(Number(callIndex)) ? Number(callIndex) : 1;
    const prev = this.callUsage.get(idx) || { in: 0, out: 0, total: 0 };
    const current = {
      in: Math.max(prev.in, inTok),
      out: Math.max(prev.out, outTok),
      total: Math.max(prev.total, totalTok),
    };
    this.callUsage.set(idx, current);
    const totals = Array.from(this.callUsage.values()).reduce(
      (acc, v) => ({
        in: acc.in + v.in,
        out: acc.out + v.out,
        total: acc.total + v.total,
      }),
      { in: 0, out: 0, total: 0 }
    );
    return { current, totals };
  },
  totals() {
    return Array.from(this.callUsage.values()).reduce(
      (acc, v) => ({
        in: acc.in + v.in,
        out: acc.out + v.out,
        total: acc.total + v.total,
      }),
      { in: 0, out: 0, total: 0 }
    );
  },
};

function updateTokens(evt) {
  const usage = evt.usage;
  const callUsage = evt.call_usage;
  const sessionUsage = evt.session_usage;
  const stage = evt.usage_stage;
  const callIndex = evt.call_index;

  let callData = null;
  let sessionData = null;
  if (callUsage && sessionUsage) {
    callData = callUsage;
    sessionData = sessionUsage;
  } else if (usage) {
    const aggregated = usageAgg.update(usage, callIndex);
    callData = aggregated.current;
    sessionData = aggregated.totals;
  }
  if (!callData || !sessionData) return;

  const label =
    stage === "planner" || callIndex === 0
      ? "planner"
      : `call#${callIndex || 1}`;
  tokenHud.textContent = `Tokens: ${label} total=${callData.total || "-"} (in=${callData.in || "-"}, out=${callData.out || "-"}) | session=${sessionData.total || "-"} (in=${sessionData.in || "-"}, out=${sessionData.out || "-"})`;
}

function renderToolResult(evt) {
  const name = evt.tool_name || "tool";
  const args = evt.arguments || {};
  const content = evt.error ? `❌ ${evt.error}` : evt.content || "(empty result)";

  const label =
    {
      read_file_hunk: "读取文件片段",
      list_project_files: "项目文件列表",
      read_file_info: "文件信息",
      search_in_project: "项目搜索",
      get_dependencies: "依赖扫描",
      echo_tool: "回显",
    }[name] || name;

  const meta = `参数: ${JSON.stringify(args, null, 2)}`;

  // 针对不同工具调整展示
  if (name === "read_file_hunk") {
    createToolCard(label, meta, content, { monospace: true, previewLines: 40 });
    return;
  }

  if (name === "list_project_files") {
    createToolCard(label, meta, content, {
      monospace: true,
      previewLines: 30,
      maxLength: 8000,
    });
    return;
  }

  if (name === "read_file_info") {
    createToolCard(label, meta, content, { monospace: false, previewLines: 20 });
    return;
  }

  if (name === "search_in_project") {
    createToolCard(label, meta, content, {
      monospace: true,
      previewLines: 40,
      maxLength: 8000,
    });
    return;
  }

  if (name === "get_dependencies") {
    createToolCard(label, meta, content, { monospace: false, previewLines: 30, maxLength: 8000 });
    return;
  }

  // 默认回退
  createToolCard(label, meta, content, { monospace: true, previewLines: 20, maxLength: 4000 });
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function truncate(str, maxLen) {
  if (!str) return "";
  return str.length > maxLen ? str.slice(0, maxLen) + "\n...(truncated)" : str;
}

function createToolCard(title, meta, rawContent, opts) {
  const options = Object.assign(
    { monospace: true, previewLines: 30, maxLength: 12000 },
    opts || {}
  );
  const full = truncate(rawContent || "", options.maxLength);
  const lines = full.split("\n");
  const needsCollapse = lines.length > options.previewLines;
  const preview = needsCollapse ? lines.slice(0, options.previewLines).join("\n") : full;

  const card = document.createElement("div");
  card.className = "tool-card";
  card.innerHTML = `
    <div class="tool-title">🔧 ${escapeHtml(title)}</div>
    <div class="tool-meta">${escapeHtml(meta)}</div>
    <div class="tool-content">
      <pre class="tool-pre" style="${options.monospace ? "" : "font-family: inherit;"}">${escapeHtml(preview)}</pre>
      ${needsCollapse ? '<div class="tool-overlay"></div>' : ""}
    </div>
    ${needsCollapse ? '<div class="tool-footer"><button class="tool-toggle">展开全部</button></div>' : ""} 
  `;
  streamBox.appendChild(card);
  streamBox.scrollTop = streamBox.scrollHeight;

  if (needsCollapse) {
    const pre = card.querySelector(".tool-pre");
    const overlay = card.querySelector(".tool-overlay");
    const btn = card.querySelector(".tool-toggle");
    btn.addEventListener("click", () => {
      const expanded = btn.getAttribute("data-expanded") === "1";
      if (expanded) {
        pre.textContent = preview;
        btn.textContent = "展开全部";
        btn.setAttribute("data-expanded", "0");
        overlay.style.display = "block";
      } else {
        pre.textContent = full;
        btn.textContent = "收起";
        btn.setAttribute("data-expanded", "1");
        overlay.style.display = "none";
      }
    });
  }
}

startBtn.addEventListener("click", startReview);
refreshBtn.addEventListener("click", fetchTools);

fetchTools();
resetUI();
promptInput.value =
  "你现在要审查一次代码变更（PR）。请阅读自动生成的上下文，围绕静态缺陷、逻辑缺陷、内存与资源问题、安全漏洞给出审查意见，如需更多上下文请调用工具。";
