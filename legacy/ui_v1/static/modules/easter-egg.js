/**
 * Easter Egg Module - 彩蛋模块
 * 用于在空白区域显示优雅的占位内容
 */

// 彩蛋配置 (已移除，直接使用内置模板)

/**
 * 基础代码模板（default 状态）
 */
function getBaseCodeLines() {
    return [
        { text: '// 正在尝试获取代码变更', type: 'comment' },
        { text: "import { Agent, Wisdom } from '@DeltaConverge/core';", type: 'keyword', html: "import { <span class=\"function\">Agent</span>, <span class=\"function\">Wisdom</span> } from <span class=\"string\">'@DeltaConverge/core'</span>;" },
        { text: '', type: '' },
        { text: 'async function main() {', type: 'keyword', html: 'async function <span class=\"function\">main</span>() {' },
        { text: '    // 选择文件以开始分析', type: 'indent comment' },
        { text: '    const target = await waitForSelection();', type: 'indent keyword', html: '    const <span class=\"variable\">target</span> = await <span class=\"function\">waitForSelection</span>();' },
        { text: '', type: '' },
        { text: '    // 无论代码写得多么复杂', type: 'indent comment' },
        { text: '    // 都逃不过 review：你写的，和你以为你写的。', type: 'indent comment' },
        { text: '    // 祝你好运。', type: 'indent comment' },
        { text: '    return Agent.review(target);', type: 'indent keyword', html: '    return <span class=\"function\">Agent</span>.<span class=\"function\">review</span>(<span class=\"variable\">target</span>);' },
        { text: '}', type: '' }
    ];
}

/**
 * 无变更状态追加的代码（no-changes 状态）
 * @param {string} diffMode 当前的 diff 模式：'working' | 'staged' | 'pr' | 'commit'
 */
function getNoChangesHint(diffMode = 'working') {
    const hints = {
        'working': '    // (或者你只是忘了 git add)',
        'staged': '    // (暂存区已清空，准备提交了吗？)',
        'pr': '    // (当前分支与目标分支完全一致)',
        'commit': '    // (所选时间点的代码完全相同)'
    };
    return hints[diffMode] || hints['working'];
}

function getNoChangesCodeLines(diffMode = 'working') {
    return [
        { text: '', type: '' },
        { text: '// 当前模式没有检测到代码变更', type: 'comment' },
        { text: '', type: '' },
        { text: 'if (diffs.length === 0) {', type: 'keyword', html: 'if (<span class="variable">diffs</span>.length === 0) {' },
        { text: '    // 这一刻，代码库达到了完美的平衡。', type: 'indent comment' },
        { text: getNoChangesHint(diffMode), type: 'indent comment', role: 'hint' },
        { text: '    console.log("It\'s clean. Too clean...");', type: 'indent', html: '    console.<span class="function">log</span>(<span class="string">"It\'s clean. Too clean..."</span>);' },
        { text: '}', type: '' }
    ];
}

/**
 * 等待选择提交的代码模板（waiting-commit 状态）
 */
function getWaitingCommitCodeLines() {
    return [
        { text: '// commit diff', type: 'comment' },
        { text: "import { History } from '@DeltaConverge/core';", type: 'keyword', html: "import { <span class=\"function\">History</span> } from <span class=\"string\">'@DeltaConverge/core'</span>;" },
        { text: '', type: '' },
        { text: 'async function compareCommits() {', type: 'keyword', html: 'async function <span class=\"function\">compareCommits</span>() {' },
        { text: '    // 先选择一个你关心的提交', type: 'indent comment' },
        { text: '    const from = await pickCommit();', type: 'indent keyword', html: '    const <span class=\"variable\">from</span> = await <span class=\"function\">pickCommit</span>();' },
        { text: '', type: '' },
        { text: '    // 如果你愿意，也可以再选一个结束点', type: 'indent comment' },
        { text: '    const to = await pickCommit() || "HEAD";', type: 'indent keyword', html: '    const <span class=\"variable\">to</span> = await <span class=\"function\">pickCommit</span>() || <span class=\"string\">"HEAD"</span>;' },
        { text: '', type: '' },
        { text: '    // 点击「查看」开始分析', type: 'indent comment' },
        { text: '    return History.diff(from, to);', type: 'indent keyword', html: '    return <span class=\"function\">History</span>.<span class=\"function\">diff</span>(<span class=\"variable\">from</span>, <span class=\"variable\">to</span>);' },
        { text: '}', type: '' }
    ];
}

/**
 * 选中提交后的代码模板（commit-selected 状态）
 */
function getCommitSelectedCodeLines(data) {
    const from = data && data.from ? data.from.substring(0, 7) : '???';
    const to = data && data.to ? (data.to === 'HEAD' ? 'HEAD' : data.to.substring(0, 7)) : 'HEAD';

    return [
        { text: `// 已选择提交范围 ${from} → ${to}`, type: 'comment' },
        { text: "import { TimeTraveller } from '@DeltaConverge/git';", type: 'keyword', html: "import { <span class=\"function\">TimeTraveller</span> } from <span class=\"string\">'@DeltaConverge/git'</span>;" },
        { text: '', type: '' },
        { text: 'async function analyzeHistory() {', type: 'keyword', html: 'async function <span class=\"function\">analyzeHistory</span>() {' },
        { text: `    const range = await git.getRange('${from}', '${to}');`, type: 'indent keyword', html: `    const <span class=\"variable\">range</span> = await <span class=\"variable\">git</span>.<span class=\"function\">getRange</span>(<span class=\"string\">'${from}'</span>, <span class=\"string\">'${to}'</span>);` },
        { text: '', type: '' },
        { text: '    // 变化有迹可循', type: 'indent comment' },
        { text: '    // 结果一目了然。', type: 'indent comment' },
        { text: '    return TimeTraveller.analyze(range);', type: 'indent keyword', html: '    return <span class=\"variable\">TimeTraveller</span>.<span class=\"function\">analyze</span>(<span class=\"variable\">range</span>);' },
        { text: '}', type: '' }
    ];
}

const animationContexts = new WeakMap();

function getAnimationContext(containerElement) {
    let ctx = animationContexts.get(containerElement);
    if (ctx) return ctx;
    ctx = {
        container: containerElement,
        processing: false,
        latestRequest: null,
        basePromise: null,
        baseToken: null,
        transitionToken: null,
        editor: null,
        codeArea: null,
        lineNumbers: null,
        tabName: null,
        renderedType: null,
        renderedDiffMode: 'working',
        renderedData: null, // 存储渲染的数据（如提交范围）
        currentOperation: null, // 'printing' | 'deleting' | null
        pendingDelete: false, // 是否有待执行的删除操作
        baseComplete: false // base 模块是否已完成打印
    };
    animationContexts.set(containerElement, ctx);
    return ctx;
}

function createToken() {
    return { cancelled: false };
}

function cancelTransition(ctx, includeBase = false) {
    if (ctx.transitionToken) ctx.transitionToken.cancelled = true;
    if (includeBase && ctx.baseToken) ctx.baseToken.cancelled = true;
}

function isActive(token) {
    return token && !token.cancelled;
}

/**
 * 等待元素可见
 */
function waitForVisible(element) {
    return new Promise(resolve => {
        // 如果已经可见，立即返回
        if (element.offsetParent !== null && element.getBoundingClientRect().width > 0) {
            resolve();
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            if (entries[0].isIntersecting) {
                observer.disconnect();
                resolve();
            }
        }, { threshold: 0.1 });
        observer.observe(element);

        // 超时保护，5秒后强制继续
        setTimeout(() => {
            observer.disconnect();
            resolve();
        }, 5000);
    });
}

function appendLineInstant(container, line, moduleName = 'base') {
    const div = document.createElement('div');
    div.className = `code-line ${line.type || ''}`;
    div.dataset.module = moduleName;
    if (line.role) div.dataset.role = line.role;
    div.innerHTML = line.html || line.text;
    container.appendChild(div);
}

function syncLineNumbers(codeArea, lineNumbers) {
    if (!lineNumbers) return;
    const count = codeArea.children.length;
    lineNumbers.innerHTML = '';
    for (let i = 1; i <= count; i++) {
        const span = document.createElement('span');
        span.textContent = i;
        lineNumbers.appendChild(span);
    }
}

function clearCursorMark(codeArea) {
    const cursors = codeArea.querySelectorAll('.blink-cursor');
    cursors.forEach(c => c.classList.remove('blink-cursor'));
}

function removeTrailingCursor(codeArea) {
    const lastEl = codeArea.lastElementChild;
    if (lastEl && lastEl.classList.contains('blink-cursor') && lastEl.textContent.trim() === '' && !lastEl.dataset.module) {
        lastEl.remove();
        return;
    }
    clearCursorMark(codeArea);
}

function ensureCursor(codeArea) {
    const cursors = codeArea.querySelectorAll('.code-line.blink-cursor');
    cursors.forEach(el => {
        if (!el.dataset.module && el.textContent.trim() === '') {
            el.remove();
        } else {
            el.classList.remove('blink-cursor');
        }
    });

    const last = codeArea.lastElementChild;
    if (last && !last.dataset.module && last.textContent.trim() === '') {
        // 已有空行，直接作为光标行
        last.classList.add('blink-cursor');
        return;
    }

    // 有模块内容的最后一行后，新增空行作为光标位置
    const cursorLine = document.createElement('div');
    cursorLine.className = 'code-line blink-cursor';
    codeArea.appendChild(cursorLine);
}

function setTabTitle(ctx, type) {
    if (!ctx.tabName) return;
    if (type === 'no-changes') {
        ctx.tabName.textContent = '无代码变更';
    } else if (type === 'waiting-commit') {
        ctx.tabName.textContent = '等待选择提交';
    } else {
        ctx.tabName.textContent = '未选择文件';
    }
}

async function typeText(element, text, token) {
    for (let i = 0; i < text.length; i++) {
        if (token && token.cancelled) return false;
        element.textContent += text[i];
        await new Promise(resolve => setTimeout(resolve, 15 + Math.random() * 15));
    }
    return true;
}

async function backspaceText(element, token) {
    const text = element.textContent;
    for (let i = text.length - 1; i >= 0; i--) {
        if (token && token.cancelled) return false;
        element.textContent = text.substring(0, i);
        await new Promise(resolve => setTimeout(resolve, 10 + Math.random() * 10));
    }
    return true;
}

async function typeLinesAnimated(container, lines, { lineNumbersEl, moduleName = 'base', token, ctx }) {
    const ctxLocal = ctx; // 存储上下文以便在函数中使用

    for (let i = 0; i < lines.length; i++) {
        if (token && token.cancelled) {
            if (ctxLocal) ctxLocal.currentOperation = null;
            return false;
        }

        if (ctxLocal && i === 0) {
            ctxLocal.currentOperation = 'printing';
        }

        removeTrailingCursor(container);
        const line = lines[i];
        const lineEl = document.createElement('div');
        lineEl.className = `code-line ${line.type || ''}`;
        lineEl.dataset.module = moduleName;
        if (line.role) lineEl.dataset.role = line.role;
        lineEl.classList.add('blink-cursor');
        container.appendChild(lineEl);
        syncLineNumbers(container, lineNumbersEl);

        if (line.text === '') {
            await new Promise(resolve => setTimeout(resolve, 40));
        } else if (line.html) {
            // 先逐字打印纯文本，完成后应用语法高亮
            const ok = await typeText(lineEl, line.text, token);
            if (!ok) {
                if (ctxLocal) ctxLocal.currentOperation = null;
                return false;
            }
            // 应用 HTML 高亮
            lineEl.innerHTML = line.html;
            await new Promise(resolve => setTimeout(resolve, 30));
        } else {
            const ok = await typeText(lineEl, line.text, token);
            if (!ok) {
                if (ctxLocal) ctxLocal.currentOperation = null;
                return false;
            }
            await new Promise(resolve => setTimeout(resolve, 40));
        }
    }

    ensureCursor(container);
    syncLineNumbers(container, lineNumbersEl);
    if (ctxLocal) ctxLocal.currentOperation = null;
    return true;
}

async function deleteModuleLinesAnimated(container, lineNumbersEl, moduleName, token, ctx) {
    const ctxLocal = ctx;
    const lines = Array.from(container.querySelectorAll(`.code-line[data-module="${moduleName}"]`)).reverse();

    if (lines.length === 0) {
        if (ctxLocal) ctxLocal.currentOperation = null;
        return true;
    }

    removeTrailingCursor(container);

    if (ctxLocal) ctxLocal.currentOperation = 'deleting';

    for (const line of lines) {
        if (token && token.cancelled) {
            if (ctxLocal) ctxLocal.currentOperation = null;
            return false;
        }

        line.classList.add('blink-cursor');

        // 对于包含 HTML 高亮的行，直接整行删除（避免处理复杂的HTML标签）
        // 对于普通文本行，执行逐字删除
        if (line.innerHTML !== line.textContent && line.innerHTML.includes('<span')) {
            // HTML 高亮行：短延迟后整行删除
            await new Promise(resolve => setTimeout(resolve, 120));
            line.remove();
        } else if (line.textContent.trim() === '') {
            // 空行：快速删除
            await new Promise(resolve => setTimeout(resolve, 60));
            line.remove();
        } else {
            // 普通文本行：逐字删除
            const ok = await backspaceText(line, token);
            if (!ok) {
                if (ctxLocal) ctxLocal.currentOperation = null;
                return false;
            }
            // 删除完成后稍作停留，然后移除空行
            await new Promise(resolve => setTimeout(resolve, 80));
            line.remove();
        }

        syncLineNumbers(container, lineNumbersEl);
    }

    ensureCursor(container);
    syncLineNumbers(container, lineNumbersEl);
    if (ctxLocal) {
        ctxLocal.currentOperation = null;
        ctxLocal.pendingDelete = false;
    }
    return true;
}

async function rewriteNoChangeHint(codeArea, diffMode, token) {
    const hintLine = codeArea.querySelector('.code-line[data-module="no-changes"][data-role="hint"]');
    if (!hintLine) return true;
    hintLine.classList.add('blink-cursor');
    hintLine.textContent = '';
    const ok = await typeText(hintLine, getNoChangesHint(diffMode), token);
    hintLine.classList.remove('blink-cursor');
    return ok;
}

function buildBaseShell(ctx, req) {
    const tabTitle = req.animate ? '初始化环境...' : (req.type === 'no-changes' ? '无代码变更' : '未选择文件');
    ctx.container.innerHTML = `
        <div class="easter-egg-editor" data-egg-type="default" data-diff-mode="${req.diffMode}">
            <div class="editor-header">
                <div class="editor-tabs">
                    <div class="editor-tab placeholder">
                        <span class="tab-icon">📄</span>
                        <span class="tab-name">${tabTitle}</span>
                    </div>
                </div>
            </div>
            <div class="editor-content">
                <div class="line-numbers"><span>1</span></div>
                <div class="code-area" id="easterEggCodeArea">
                    <div class="code-line blink-cursor"></div>
                </div>
            </div>
        </div>
    `;

    ctx.editor = ctx.container.querySelector('.easter-egg-editor');
    ctx.codeArea = ctx.container.querySelector('#easterEggCodeArea');
    ctx.lineNumbers = ctx.container.querySelector('.line-numbers');
    ctx.tabName = ctx.container.querySelector('.tab-name');
    ctx.basePromise = null;
    ctx.baseToken = null;
    ctx.transitionToken = null;
    ctx.renderedType = 'default';
    ctx.renderedDiffMode = req.diffMode;
    ctx.baseComplete = false;
    ctx.currentOperation = null;
    ctx.pendingDelete = false;
}

async function renderBaseIfNeeded(ctx, animate) {
    if (ctx.basePromise) {
        const done = await ctx.basePromise;
        if (!done) ctx.basePromise = null;
        return done;
    }

    ctx.baseToken = createToken();
    const token = ctx.baseToken;
    const baseLines = getBaseCodeLines();
    ctx.codeArea.innerHTML = '<div class="code-line blink-cursor"></div>';
    syncLineNumbers(ctx.codeArea, ctx.lineNumbers);

    ctx.basePromise = (async () => {
        if (!animate) {
            ctx.codeArea.innerHTML = '';
            baseLines.forEach(line => appendLineInstant(ctx.codeArea, line, 'base'));
            ensureCursor(ctx.codeArea);
            syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
            ctx.baseComplete = true;
            return true;
        }

        // 等待容器可见后再开始动画
        await waitForVisible(ctx.container);
        if (token.cancelled) return false;

        const finished = await typeLinesAnimated(ctx.codeArea, baseLines, {
            lineNumbersEl: ctx.lineNumbers,
            moduleName: 'base',
            token,
            ctx
        });
        if (finished) ctx.baseComplete = true;
        return finished;
    })();

    const finished = await ctx.basePromise;
    if (!finished) ctx.basePromise = null;
    return finished;
}

async function transitionToState(ctx, req) {
    ctx.transitionToken = createToken();
    const token = ctx.transitionToken;
    if (!ctx.codeArea) return 'cancelled';

    const hasNoChangeBlock = !!ctx.codeArea.querySelector('[data-module="no-changes"]');

    // 智能模式切换逻辑
    if (req.type === 'no-changes') {
        // 切换到无代码变更模式：等待当前 base 打印完成后再追加
        if (ctx.tabName) ctx.tabName.textContent = '无代码变更';

        // 如果正在进行 base 打印，等待完成
        if (ctx.basePromise) {
            const baseFinished = await ctx.basePromise;
            if (!baseFinished || !isActive(token)) return 'cancelled';
        }

        if (!hasNoChangeBlock) {
            if (req.animate) {
                removeTrailingCursor(ctx.codeArea);
                const appended = await typeLinesAnimated(ctx.codeArea, getNoChangesCodeLines(req.diffMode), {
                    lineNumbersEl: ctx.lineNumbers,
                    moduleName: 'no-changes',
                    token,
                    ctx
                });
                if (!appended || !isActive(token)) return 'cancelled';
            } else {
                removeTrailingCursor(ctx.codeArea);
                getNoChangesCodeLines(req.diffMode).forEach(line => appendLineInstant(ctx.codeArea, line, 'no-changes'));
            }
        } else if (ctx.renderedDiffMode !== req.diffMode) {
            const updated = req.animate ? await rewriteNoChangeHint(ctx.codeArea, req.diffMode, token) : (() => {
                const hintEl = ctx.codeArea.querySelector('.code-line[data-module="no-changes"][data-role="hint"]');
                if (hintEl) hintEl.textContent = getNoChangesHint(req.diffMode);
                return true;
            })();
            if (!updated || !isActive(token)) return 'cancelled';
        }
    } else {
        // 切换到有代码变更模式：立即中断并删除 no-changes 模块
        if (ctx.tabName) ctx.tabName.textContent = '未选择文件';

        // 立即中断 currentOperation（如果正在打印 no-changes）
        if (ctx.currentOperation === 'printing' && ctx.transitionToken) {
            ctx.transitionToken.cancelled = true;
            // 等待一个 tick 让打印循环响应取消
            await new Promise(resolve => setTimeout(resolve, 50));
            // 创建新的 token 继续
            ctx.transitionToken = createToken();
        }

        // 重新检查是否有 no-changes 模块（包括中途被中断的行）
        const noChangeLines = ctx.codeArea.querySelectorAll('[data-module="no-changes"]');
        if (noChangeLines.length > 0) {
            if (req.animate) {
                const removed = await deleteModuleLinesAnimated(ctx.codeArea, ctx.lineNumbers, 'no-changes', ctx.transitionToken, ctx);
                if (!removed || !isActive(ctx.transitionToken)) return 'cancelled';
            } else {
                removeTrailingCursor(ctx.codeArea);
                noChangeLines.forEach(el => el.remove());
                ensureCursor(ctx.codeArea);
                syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
            }
        }
    }

    if (!isActive(ctx.transitionToken)) return 'cancelled';
    ensureCursor(ctx.codeArea);
    syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
    return 'done';
}

async function renderWaitingCommit(ctx, req) {
    cancelTransition(ctx, true);
    const lines = getWaitingCommitCodeLines();
    ctx.container.innerHTML = `
        <div class="easter-egg-editor" data-egg-type="waiting-commit" data-diff-mode="${req.diffMode}">
            <div class="editor-header">
                <div class="editor-tabs">
                    <div class="editor-tab placeholder">
                        <span class="tab-icon">📑</span>
                        <span class="tab-name">${req.animate ? '初始化环境...' : '等待选择提交'}</span>
                    </div>
                </div>
            </div>
            <div class="editor-content">
                <div class="line-numbers"><span>1</span></div>
                <div class="code-area" id="easterEggCodeArea">
                    <div class="code-line blink-cursor"></div>
                </div>
            </div>
        </div>
    `;

    ctx.editor = ctx.container.querySelector('.easter-egg-editor');
    ctx.codeArea = ctx.container.querySelector('#easterEggCodeArea');
    ctx.lineNumbers = ctx.container.querySelector('.line-numbers');
    ctx.tabName = ctx.container.querySelector('.tab-name');
    ctx.basePromise = null;
    ctx.baseToken = createToken();
    ctx.transitionToken = null;
    ctx.renderedType = 'waiting-commit';
    ctx.renderedDiffMode = req.diffMode;
    ctx.renderedData = req.data; // 保存当前渲染的数据
    ctx.baseComplete = false; // 重置状态
    ctx.currentOperation = null;
    ctx.pendingDelete = false;

    if (!req.animate) {
        ctx.codeArea.innerHTML = '';
        lines.forEach(line => appendLineInstant(ctx.codeArea, line, 'waiting-commit'));
        ensureCursor(ctx.codeArea);
        syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
        setTabTitle(ctx, 'waiting-commit');
        ctx.baseComplete = true;
        return;
    }

    // 等待容器可见后再开始动画
    await waitForVisible(ctx.container);
    if (ctx.baseToken.cancelled) return;

    const finished = await typeLinesAnimated(ctx.codeArea, lines, {
        lineNumbersEl: ctx.lineNumbers,
        moduleName: 'waiting-commit',
        token: ctx.baseToken
    });
    if (finished) {
        setTabTitle(ctx, 'waiting-commit');
        ctx.baseComplete = true;
    }
    ensureCursor(ctx.codeArea);
    syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
}

async function renderCommitSelected(ctx, req) {
    cancelTransition(ctx, true);
    const lines = getCommitSelectedCodeLines(req.data);

    ctx.container.innerHTML = `
        <div class="easter-egg-editor" data-egg-type="commit-selected" data-diff-mode="${req.diffMode}">
            <div class="editor-header">
                <div class="editor-tabs">
                    <div class="editor-tab placeholder">
                        <span class="tab-icon">📆</span>
                        <span class="tab-name">${req.animate ? '正在回退历史' : '历史变更'}</span>
                    </div>
                </div>
            </div>
            <div class="editor-content">
                <div class="line-numbers"><span>1</span></div>
                <div class="code-area" id="easterEggCodeArea">
                    <div class="code-line blink-cursor"></div>
                </div>
            </div>
        </div>
    `;

    ctx.editor = ctx.container.querySelector('.easter-egg-editor');
    ctx.codeArea = ctx.container.querySelector('#easterEggCodeArea');
    ctx.lineNumbers = ctx.container.querySelector('.line-numbers');
    ctx.tabName = ctx.container.querySelector('.tab-name');
    ctx.basePromise = null;
    ctx.baseToken = createToken();
    ctx.transitionToken = null;
    ctx.renderedType = 'commit-selected';
    ctx.renderedDiffMode = req.diffMode;
    ctx.renderedData = req.data; // 保存当前渲染的数据（提交范围）
    ctx.baseComplete = false;
    ctx.currentOperation = null;
    ctx.pendingDelete = false;

    if (!req.animate) {
        ctx.codeArea.innerHTML = '';
        lines.forEach(line => appendLineInstant(ctx.codeArea, line, 'commit-selected'));
        ensureCursor(ctx.codeArea);
        syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
        if (ctx.tabName) ctx.tabName.textContent = '历史变更';
        ctx.baseComplete = true;
        return;
    }

    await waitForVisible(ctx.container);
    if (ctx.baseToken.cancelled) return;

    const finished = await typeLinesAnimated(ctx.codeArea, lines, {
        lineNumbersEl: ctx.lineNumbers,
        moduleName: 'commit-selected',
        token: ctx.baseToken
    });
    if (finished) {
        if (ctx.tabName) ctx.tabName.textContent = '历史变更';
        ctx.baseComplete = true;
    }
    ensureCursor(ctx.codeArea);
    syncLineNumbers(ctx.codeArea, ctx.lineNumbers);
}

async function processRequests(ctx) {
    ctx.processing = true;
    while (ctx.latestRequest) {
        const req = ctx.latestRequest;
        ctx.latestRequest = null;

        if (req.type === 'waiting-commit') {
            await renderWaitingCommit(ctx, req);
            continue;
        }

        if (req.type === 'commit-selected') {
            await renderCommitSelected(ctx, req);
            continue;
        }

        // 检查编辑器是否存在且在 DOM 中
        const editorValid = ctx.editor && ctx.editor.parentElement;
        if (!editorValid || (ctx.editor && ctx.editor.dataset.eggType === 'waiting-commit')) {
            buildBaseShell(ctx, req);
        }

        // 等待正在进行的删除操作完成（删除优先策略）
        if (ctx.pendingDelete) {
            await new Promise(resolve => setTimeout(resolve, 100));
            if (ctx.pendingDelete) {
                ctx.latestRequest = req; // 重新排队
                continue;
            }
        }

        const baseReady = await renderBaseIfNeeded(ctx, req.animate);
        if (!baseReady) continue;

        // 标记转换开始
        ctx.pendingDelete = (req.type !== 'no-changes' &&
            ctx.codeArea &&
            ctx.codeArea.querySelector('[data-module="no-changes"]'));

        const result = await transitionToState(ctx, req);
        if (result === 'cancelled') continue;

        ctx.renderedType = req.type;
        ctx.renderedDiffMode = req.diffMode;
        ctx.renderedData = req.data;
        if (ctx.editor) {
            ctx.editor.dataset.eggType = req.type;
            ctx.editor.dataset.diffMode = req.diffMode;
        }
    }
    ctx.processing = false;
}

/**
 * 初始化彩蛋（智能处理增量更新）
 * @param {HTMLElement} containerElement 容器元素
 * @param {boolean} animate 是否开启动画（仅在完全重建时有效）
 * @param {string} type 模式类型：'default' | 'no-changes' | 'waiting-commit'
 * @param {string} diffMode 当前的 diff 模式：'working' | 'staged' | 'pr' | 'commit'
 */
function initEasterEgg(containerElement, animate = false, type = 'default', diffMode = 'working', data = null) {
    if (!containerElement) return;

    const ctx = getAnimationContext(containerElement);

    // 检查编辑器是否还在 DOM 中（可能被外部清空）
    const editorExists = ctx.editor && ctx.editor.parentElement;

    // 检查 data 是否变化（用于 commit-selected 类型，提交范围可能不同）
    const dataChanged = JSON.stringify(data) !== JSON.stringify(ctx.renderedData);

    // 如果当前已经是目标状态且 base 已完成且编辑器存在且数据没变，无需重复请求
    if (editorExists &&
        ctx.renderedType === type &&
        ctx.renderedDiffMode === diffMode &&
        !dataChanged &&
        ctx.baseComplete &&
        !ctx.processing) {
        return;
    }

    // 如果编辑器不存在，重置状态
    if (!editorExists) {
        ctx.editor = null;
        ctx.codeArea = null;
        ctx.lineNumbers = null;
        ctx.tabName = null;
        ctx.basePromise = null;
        ctx.baseComplete = false;
        ctx.renderedType = null;
    }

    ctx.latestRequest = { type, diffMode, animate, data };

    if (type === 'waiting-commit' || type === 'commit-selected') {
        cancelTransition(ctx, true);
    } else {
        cancelTransition(ctx, false);
    }

    if (!ctx.processing) {
        processRequests(ctx);
    }
}

// 导出到全局
window.EasterEgg = {
    init: initEasterEgg
};
