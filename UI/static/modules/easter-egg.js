/**
 * Easter Egg Module - 彩蛋模块
 * 用于在空白区域显示优雅的占位内容
 * 可以随时替换这个文件来更换彩蛋
 */

// 彩蛋配置
const EASTER_EGG_CONFIG = {
    // 提示语集合
    tips: [
        '选择文件预览代码差异'
    ]
};

/**
 * 创建彩蛋 HTML 内容 - 模拟代码编辑器风格
 * @returns {string} HTML 字符串
 */
function createEasterEggHTML() {
    const randomTip = EASTER_EGG_CONFIG.tips[Math.floor(Math.random() * EASTER_EGG_CONFIG.tips.length)];

    return `
        <div class="easter-egg-editor">
            <div class="editor-header">
                <div class="editor-tabs">
                    <div class="editor-tab placeholder">
                        <span class="tab-icon">📄</span>
                        <span class="tab-name">未选择文件</span>
                    </div>
                </div>
            </div>
            <div class="editor-content">
                <div class="line-numbers">
                    <span>1</span>
                    <span>2</span>
                    <span>3</span>
                    <span>4</span>
                    <span>5</span>
                    <span>6</span>
                    <span>7</span>
                    <span>8</span>
                    <span>9</span>
                </div>
                <div class="code-area">
                    <div class="code-line comment">// ${randomTip}</div>
                    <div class="code-line"></div>
                    <div class="code-line keyword">function <span class="function">reviewCode</span>() {</div>
                    <div class="code-line indent comment">// 从左侧文件列表选择文件</div>
                    <div class="code-line indent keyword">const <span class="variable">changes</span> = <span class="function">getDiff</span>();</div>
                    <div class="code-line indent keyword">return <span class="function">analyze</span>(<span class="variable">changes</span>);</div>
                    <div class="code-line">}</div>
                    <div class="code-line"></div>
                    <div class="code-line blink-cursor"></div>
                </div>
            </div>
        </div>
    `;
}

/**
 * 获取简单占位 HTML
 */
function getEasterEggPlaceholder() {
    return createEasterEggHTML();
}

/**
 * 初始化彩蛋（带打字机动画）
 */
function initEasterEgg(containerElement, animate = false) {
    if (!containerElement) return;

    // 如果不需要动画，直接渲染静态 HTML
    if (!animate) {
        containerElement.innerHTML = createEasterEggHTML();
        return;
    }

    // 渲染编辑器框架（内容为空）
    const randomTip = EASTER_EGG_CONFIG.tips[Math.floor(Math.random() * EASTER_EGG_CONFIG.tips.length)];
    const codeLines = [
        { text: `// ${randomTip}`, type: 'comment' },
        { text: '', type: '' },
        { text: 'function reviewCode() {', type: 'keyword', html: 'function <span class="function">reviewCode</span>() {' },
        { text: '// 从左侧文件列表选择文件', type: 'indent comment' },
        { text: 'const changes = getDiff();', type: 'indent keyword', html: 'const <span class="variable">changes</span> = <span class="function">getDiff</span>();' },
        { text: 'return analyze(changes);', type: 'indent keyword', html: 'return <span class="function">analyze</span>(<span class="variable">changes</span>);' },
        { text: '}', type: '' }
    ];

    // 基础框架
    containerElement.innerHTML = `
        <div class="easter-egg-editor">
            <div class="editor-header">
                <div class="editor-tabs">
                    <div class="editor-tab placeholder">
                        <span class="tab-icon">📄</span>
                        <span class="tab-name">初始化环境...</span>
                    </div>
                </div>
            </div>
            <div class="editor-content">
                <div class="line-numbers">
                    <span>1</span>
                </div>
                <div class="code-area" id="easterEggCodeArea">
                    <div class="code-line blink-cursor"></div>
                </div>
            </div>
        </div>
    `;

    const codeArea = containerElement.querySelector('#easterEggCodeArea');
    const tabName = containerElement.querySelector('.tab-name');

    // 使用 IntersectionObserver 等待元素可见后再开始动画
    const observer = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting) {
            // 元素可见，开始动画
            observer.disconnect(); // 只触发一次

            // 延迟一点点开始，体验更好
            setTimeout(() => {
                typeLines(codeArea, codeLines, 0, () => {
                    // 动画完成，更新标签名
                    if (tabName) tabName.textContent = '未选择文件';

                    // 移除所有已有的光标
                    const existingCursors = codeArea.querySelectorAll('.blink-cursor');
                    existingCursors.forEach(el => el.classList.remove('blink-cursor'));

                    // 添加最后一行空行光标
                    const cursorLine = document.createElement('div');
                    cursorLine.className = 'code-line blink-cursor';
                    codeArea.appendChild(cursorLine);

                    // 补全行号
                    const lineNumbers = containerElement.querySelector('.line-numbers');
                    for (let i = 2; i <= 9; i++) {
                        const span = document.createElement('span');
                        span.textContent = i;
                        lineNumbers.appendChild(span);
                    }
                });
            }, 300);
        }
    }, { threshold: 0.1 });

    observer.observe(containerElement);
}

/**
 * 递归逐行打印
 */
function typeLines(container, lines, index, callback) {
    if (index >= lines.length) {
        if (callback) callback();
        return;
    }

    const line = lines[index];
    const lineEl = document.createElement('div');
    lineEl.className = `code-line ${line.type || ''}`;
    // 移除上一个光标
    const prevCursor = container.querySelector('.blink-cursor');
    if (prevCursor) prevCursor.classList.remove('blink-cursor');

    // 当前行添加光标
    lineEl.classList.add('blink-cursor');
    container.appendChild(lineEl);

    // 更新行号(简单处理，每一行加一个)
    // const lineNumbers = container.parentElement.querySelector('.line-numbers');
    // if (lineNumbers) {
    //    const num = document.createElement('span');
    //    num.textContent = index + 1;
    //    lineNumbers.appendChild(num);
    // }

    // 使用 HTML 内容（如果提供了）还是纯文本
    const content = line.html || line.text;

    // 这里为了简单和性能，直接整行显示，或者逐字显示
    // 为了"形成过程"，我们快速逐字显示文本部分

    if (line.text === '') {
        // 空行直接完成
        setTimeout(() => {
            typeLines(container, lines, index + 1, callback);
        }, 100);
    } else {
        // 模拟打字
        // 如果有 HTML 标签，比较难逐字打，这里简化为：
        // 1. 对于简单文本，逐字
        // 2. 对于复杂 HTML，整行延迟显示

        if (line.html) {
            setTimeout(() => {
                lineEl.innerHTML = line.html;
                setTimeout(() => {
                    typeLines(container, lines, index + 1, callback);
                }, 300); // 行间停顿
            }, 500); // 打字耗时模拟
        } else {
            typeText(lineEl, line.text, 0, () => {
                setTimeout(() => {
                    typeLines(container, lines, index + 1, callback);
                }, 200);
            });
        }
    }
}

function typeText(element, text, charIndex, onComplete) {
    if (charIndex >= text.length) {
        onComplete();
        return;
    }
    element.textContent += text[charIndex];
    setTimeout(() => {
        typeText(element, text, charIndex + 1, onComplete);
    }, 30 + Math.random() * 50); // 随机打字速度
}

// 导出到全局
window.EasterEgg = {
    init: initEasterEgg,
    getHTML: createEasterEggHTML,
    getPlaceholder: getEasterEggPlaceholder
};
