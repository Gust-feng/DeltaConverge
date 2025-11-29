const modelSelect = document.getElementById("model");
const toolsContainer = document.getElementById("tools");
const promptInput = document.getElementById("prompt");
const autoApproveInput = document.getElementById("autoApprove");
  const projectRootInput = document.getElementById("projectRoot");
const checkDiffBtn = document.getElementById("checkDiffBtn");
const diffStatusEl = document.getElementById("diffStatus");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const logEl = document.getElementById("log");
const statusEl = document.getElementById("status");

let controller = null;

// --- Renderer Class ---
class LogRenderer {
    constructor(container) {
        this.container = container;
        this.currentBlock = null; // { type: 'markdown'|'reasoning', element: HTMLElement, text: '' }
        this.marked = window.marked;
    }

    reset() {
        this.container.innerHTML = "";
        this.currentBlock = null;
    }

    _renderMarkdown(text) {
        if (this.marked) {
            return this.marked.parse(text);
        }
        return `<pre>${text}</pre>`;
    }

    appendMarkdown(text) {
        if (!text) return;
        if (!this.currentBlock || this.currentBlock.type !== 'markdown') {
            this.startNewBlock('markdown');
        }
        this.currentBlock.text += text;
        // Incremental rendering: update innerHTML of the current block
        this.currentBlock.element.innerHTML = this._renderMarkdown(this.currentBlock.text);
    }

    appendReasoning(text) {
        if (!text) return;
        if (!this.currentBlock || this.currentBlock.type !== 'reasoning') {
            this.startNewBlock('reasoning');
        }
        this.currentBlock.text += text;
        // Reasoning content is usually plain text, but we can support simple markdown or just text
        // Using textContent for safety and speed, or innerHTML if we want markdown inside reasoning
        // Let's use simple text mapping for now to avoid complex nested markdown issues
        const contentEl = this.currentBlock.element.querySelector('.reasoning-content');
        contentEl.innerText = this.currentBlock.text; 
    }

    closeReasoning() {
        if (this.currentBlock && this.currentBlock.type === 'reasoning') {
            this.currentBlock.element.removeAttribute('open');
            this.currentBlock = null; // Force new block next time
        }
    }

    startNewBlock(type) {
        if (type === 'markdown') {
            const div = document.createElement('div');
            div.className = 'markdown-body';
            this.container.appendChild(div);
            this.currentBlock = { type: 'markdown', element: div, text: '' };
        } else if (type === 'reasoning') {
            const details = document.createElement('details');
            details.className = 'reasoning-details';
            details.open = true; // Default open while streaming
            details.innerHTML = `
        <summary class="reasoning-summary">
            <span class="tag tag-think">思考</span> 
            <span class="summary-text">思考过程...</span>
        </summary>
        <div class="reasoning-content"></div>
      `;
            this.container.appendChild(details);
            this.currentBlock = { type: 'reasoning', element: details, text: '' };
        }
    }

    appendHTML(html) {
        // For tool results, warnings, etc.
        // Reset current block so next markdown starts fresh
        this.currentBlock = null;
        
        // Create a wrapper to append HTML string
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html;
        // Append children to container
        while (wrapper.firstChild) {
            this.container.appendChild(wrapper.firstChild);
        }
    }

    // Helper to ensure we have a place to stream plan content
    ensurePlanBlock() {
        let block = this.container.querySelector('.plan-block:last-child');
        // Check if the last element is indeed a plan block and "active" (not followed by other stuff)
        // Since we append sequentially, if lastChild is plan-block, we use it.
        if (!block || block !== this.container.lastElementChild) {
             block = document.createElement('div');
             block.className = 'plan-block';
             block.innerHTML = `<div class="plan-header"><span class="tag tag-plan">规划</span></div><div class="plan-content"></div>`;
             this.container.appendChild(block);
        }
        return block.querySelector('.plan-content');
    }

    appendToolStart(toolName, args) {
        this.closeReasoning();
        this.currentBlock = null;

        const div = document.createElement('div');
        div.className = 'tool-entry pending';
        // Store metadata to find it later
        div.dataset.toolName = toolName;
        div.dataset.status = 'pending';

        const argsHtml = this._formatArgs(args);
        
        div.innerHTML = `
            <div class="tool-header">
                <span class="tag tag-tool">工具</span>
                <strong>${toolName}</strong>
                <span class="tag tool-status">运行中...</span>
            </div>
            ${argsHtml ? `<div class="tool-args">${argsHtml}</div>` : ''}
        `;
        this.container.appendChild(div);
    }

    updateToolResult(toolName, success, error) {
        // Find the first pending tool entry with this name
        const entries = this.container.querySelectorAll('.tool-entry[data-status="pending"]');
        let target = null;
        for (let el of entries) {
             if (el.dataset.toolName === toolName) {
                 target = el;
                 break;
             }
        }
        
        const statusText = success ? '成功' : '失败';
        const statusClass = success ? 'tag-success' : 'tag-error';

        if (target) {
            target.classList.remove('pending');
            target.classList.add(success ? 'success' : 'error');
            target.dataset.status = 'done';
            
            const statusEl = target.querySelector('.tool-status');
            statusEl.textContent = statusText;
            statusEl.className = `tag tool-status ${statusClass}`;

            if (error) {
                const errDiv = document.createElement('div');
                errDiv.className = 'msg-error';
                errDiv.style.marginTop = '0.5rem';
                errDiv.innerText = error;
                target.appendChild(errDiv);
            }
        } else {
            // Fallback if start event missed
            const div = document.createElement('div');
            div.className = `tool-entry ${success ? 'success' : 'error'}`;
            div.innerHTML = `
                <div class="tool-header">
                    <span class="tag tag-tool">工具</span>
                    <strong>${toolName}</strong>
                    <span class="tag tool-status ${statusClass}">${statusText}</span>
                </div>
                ${error ? `<div class="msg-error" style="margin-top:0.5rem">${error}</div>` : ''}
            `;
            this.container.appendChild(div);
        }
    }

    _formatArgs(args) {
        if (!args) return '';
        if (typeof args === 'string') return args;
        try {
            if (Object.keys(args).length === 0) return '';
            return Object.entries(args).map(([k, v]) => {
                let valStr = v;
                if (typeof v === 'object') valStr = JSON.stringify(v);
                // Use compact HTML to avoid whitespace issues
                return `<div class="arg-row"><span class="arg-key">${k}:</span><span class="arg-value">${valStr}</span></div>`;
            }).join('');
        } catch (e) {
            return JSON.stringify(args);
        }
    }
}

const renderer = new LogRenderer(logEl);

// --- Helper Functions ---

function setStatus(text, cls = "") {
    statusEl.textContent = text;
    statusEl.className = `status ${cls}`.trim();
}

function renderTools(tools) {
    toolsContainer.innerHTML = "";
    tools.forEach((tool) => {
        const id = `tool-${tool.name}`;
        const wrapper = document.createElement("label");
        wrapper.className = "tool-item";
        wrapper.htmlFor = id;

        const input = document.createElement("input");
        input.type = "checkbox";
        input.id = id;
        input.value = tool.name;
        input.checked = !!tool.default;

        const name = document.createElement("strong");
        name.textContent = tool.name;

        const desc = document.createElement("span");
        desc.textContent = tool.description || "";
        desc.style.color = "#64748b";
        desc.style.fontSize = "0.8em";

        wrapper.appendChild(input);
        wrapper.appendChild(name);
        wrapper.appendChild(desc);
        toolsContainer.appendChild(wrapper);
    });
}

async function loadOptions() {
    try {
        const res = await fetch("/api/options");
        const data = await res.json();
        modelSelect.innerHTML = "";
        (data.models || []).forEach((m) => {
            const opt = document.createElement("option");
            opt.value = m.name;
            opt.textContent = m.name;
            modelSelect.appendChild(opt);
        });
        renderTools(data.tools || []);
    } catch (e) {
        renderer.appendHTML(`<div class="msg-error"><span class="tag tag-error">加载失败</span>${e.message || e}</div>`);
    }
}

function collectTools() {
    const inputs = toolsContainer.querySelectorAll("input[type=checkbox]");
    const selected = [];
    inputs.forEach((inp) => {
        if (inp.checked) selected.push(inp.value);
    });
    return selected;
}

async function checkDiff() {
    const projectRoot = projectRootInput.value.trim();
    diffStatusEl.textContent = "正在检查变更...";
    diffStatusEl.style.color = "#64748b";

    try {
        const res = await fetch("/api/diff/check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                prompt: "check", // dummy
                project_root: projectRoot || undefined
            }),
        });

        const data = await res.json();
        if (data.error) {
            diffStatusEl.textContent = `错误: ${data.error}`;
            diffStatusEl.style.color = "var(--error-color)";
        } else {
            const count = data.stats.total_files;
            diffStatusEl.textContent = `发现 ${count} 个变更文件 (Base: ${data.stats.base_branch || 'unknown'})`;
            diffStatusEl.style.color = "var(--success-color)";

            renderer.reset();
            if (count > 0) {
                renderer.appendMarkdown(`### 变更文件预览\n\n${data.files.map(f => `- \`${f}\``).join('\n')}\n\n---\n\n`);
            } else {
                renderer.appendMarkdown(`### 未发现变更\n\n请确认项目路径是否正确，或是否有未提交的更改。`);
            }
        }
    } catch (e) {
        diffStatusEl.textContent = `检查失败: ${e.message}`;
        diffStatusEl.style.color = "var(--error-color)";
    }
}

function parseSSE(buffer, handleEvent) {
    let remaining = buffer;
    let idx;
    while ((idx = remaining.indexOf("\n\n")) !== -1) {
        const raw = remaining.slice(0, idx).trim();
        remaining = remaining.slice(idx + 2);
        if (raw.startsWith("data:")) {
            try {
                const payload = JSON.parse(raw.replace(/^data:\s*/, ""));
                handleEvent(payload);
            } catch (e) {
                console.error("Parse error", e);
            }
        }
    }
    return remaining;
}

async function startReview() {
    if (controller) {
        controller.abort();
    }
    controller = new AbortController();

    const prompt = promptInput.value.trim();
    const body = {
        prompt: prompt || undefined,
        model: modelSelect.value || "auto",
        tools: collectTools(),
        autoApprove: autoApproveInput.checked,
        project_root: projectRootInput.value.trim() || undefined
    };

    renderer.reset();
    setStatus("运行中", "running");
    startBtn.disabled = true;
    stopBtn.disabled = false;

    try {
        const res = await fetch("/api/review/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: controller.signal,
        });

        if (!res.ok || !res.body) {
            throw new Error(`服务异常: ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        let lastEventType = null;
        // Track if we are currently outputting content for the final review to avoid duplication
        let hasStreamedReviewContent = false;

        const handleEvent = (evt) => {
            const t = evt.type;

            // 1. Always handle reasoning if present
            if (evt.reasoning_delta && evt.reasoning_delta.trim()) {
                renderer.appendReasoning(evt.reasoning_delta);
            }

            // 2. Determine if we should close reasoning (collapse it)
            // We close reasoning if we receive significant content or other events
            let hasContent = evt.content_delta && evt.content_delta.length > 0;
            if (hasContent || ['tool_call_start', 'tool_result', 'warning', 'error', 'final'].includes(t)) {
                renderer.closeReasoning();
            }

            // 3. Handle Content
            if (evt.content_delta) {
                if (t === "planner_delta") {
                    const planContent = renderer.ensurePlanBlock();
                    planContent.textContent += evt.content_delta;
                } else if (t === "delta" || t === "intent_delta") {
                     renderer.appendMarkdown(evt.content_delta);
                     if (t === "delta") hasStreamedReviewContent = true;
                }
            }

            // 4. Handle Tools & Status
            if (t === "tool_call_start") {
                renderer.appendToolStart(evt.tool_name, evt.arguments);
            } else if (t === "tool_result") {
                const success = !evt.error;
                renderer.updateToolResult(evt.tool_name, success, evt.error);
            } else if (t === "usage_summary") {
                // Optional: show usage stats in log or status bar
                console.log("Usage:", evt);
            } else if (t === "warning") {
                renderer.appendHTML(`<div class="msg-warning"><span class="tag tag-warning">警告</span>${evt.message}</div>`);
            } else if (t === "error") {
                renderer.appendHTML(`<div class="msg-error"><span class="tag tag-error">错误</span>${evt.message}</div>`);
            } else if (t === "final") {
                setStatus("审查完成", "success");
                startBtn.disabled = false;
                stopBtn.disabled = true;
                
                // If we haven't streamed any content (e.g. non-streaming model), render the final result
                if (!hasStreamedReviewContent && evt.content) {
                    renderer.appendMarkdown("\n\n### 审查结论\n\n" + evt.content);
                }
            }
            
            lastEventType = t;
        };

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            buffer = parseSSE(buffer, handleEvent);
        }
    } catch (e) {
        if (e.name === "AbortError") {
            renderer.appendHTML("<div class='msg-warning'><span class='tag tag-warn'>已停止</span> 用户终止操作</div>");
        } else {
            renderer.appendHTML(`<div class='msg-error'><span class='tag tag-error'>请求失败</span> ${e.message || e}</div>`);
            setStatus("错误", "error");
        }
    } finally {
        startBtn.disabled = false;
        stopBtn.disabled = true;
        controller = null;
    }
}

function stopReview() {
    if (controller) controller.abort();
    setStatus("已停止", "");
}

startBtn.addEventListener("click", startReview);
stopBtn.addEventListener("click", stopReview);
checkDiffBtn.addEventListener("click", checkDiff);

loadOptions();
