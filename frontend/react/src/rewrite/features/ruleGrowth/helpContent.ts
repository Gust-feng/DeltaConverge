/**
 * rule-growth.js:1025-1116 的硬编码帮助文档，原样迁移。
 * 注意：旧版 content 自身包含一层 .dialog-body，而 showHelpDialog 外层还会再包一层，
 * 这里保持相同的嵌套结构。
 */
export const HINTS_HELP_CONTENT = `
        <div class="dialog-body">
            <div class="md-doc">
                <aside class="md-sidebar">
                    <nav class="md-nav">
                        <div class="md-nav-title">目录</div>
                        <ul class="md-nav-list">
                            <li><a href="#sec-overview" class="active">核心机制</a></li>
                            <li><a href="#sec-conflict-types">冲突类型</a></li>
                            <li><a href="#sec-grouping">聚合维度</a></li>
                            <li><a href="#sec-consistency">一致性</a></li>
                            <li><a href="#sec-rule-hint">规则提示</a></li>
                            <li><a href="#sec-tags">标签作用</a></li>
                        </ul>
                    </nav>
                </aside>
            <main class="md-main">
                <section id="sec-overview" class="md-section">
                    <h2>什么是规则优化</h2>
                    <p>系统同时使用两种方式判断代码变更需要多少上下文信息：<strong>规则层</strong>（基于预设规则快速判断）和<strong>LLM 层</strong>（大语言模型深度分析）</p>
                    <p>当两者判断不一致时，系统记录为「冲突」。多个相似的冲突被聚合后，形成<strong>参考提示</strong>，供您判断是否需要更新规则配置</p>
                </section>

                <section id="sec-conflict-types" class="md-section">
                    <h2>冲突类型</h2>
                    <p>系统会检测以下四种冲突情况：</p>
                    <table class="md-table">
                        <tr>
                            <td><strong>规则高/LLM扩展</strong></td>
                            <td>规则层很有信心，但 LLM 认为需要更多上下文。说明规则可能<strong>低估了变更的复杂度</strong></td>
                        </tr>
                        <tr>
                            <td><strong>规则高/LLM跳过</strong></td>
                            <td>规则层认为需要审查，但 LLM 建议跳过。说明规则可能<strong>过度敏感</strong>，对无关紧要的变更也要求审查</td>
                        </tr>
                        <tr>
                            <td><strong>规则低/LLM明确</strong></td>
                            <td>规则层不确定（低置信度），但 LLM 给出了明确建议。这类冲突可用于<strong>发现新的规则模式</strong></td>
                        </tr>
                        <tr>
                            <td><strong>上下文级别不匹配</strong></td>
                            <td>规则层和 LLM 层建议的上下文级别差异较大</td>
                        </tr>
                    </table>
                </section>

                <section id="sec-grouping" class="md-section">
                    <h2>如何聚合</h2>
                    <p>系统按以下三个维度对冲突进行分组：</p>
                    <table class="md-table">
                        <tr><td><strong>编程语言</strong></td><td>如 Python、CSS、JavaScript 等</td></tr>
                        <tr><td><strong>语义标签</strong></td><td>代码变更的特征标签，如「完整类定义」「API端点」等</td></tr>
                        <tr><td><strong>冲突类型</strong></td><td>上述四种冲突类型之一</td></tr>
                    </table>
                    <p>具有相同语言、相同标签组合、相同冲突类型的记录会被归为同一组，统一分析</p>
                </section>

                <section id="sec-consistency" class="md-section">
                    <h2>一致性指标</h2>
                    <p><strong>一致性</strong>表示 LLM 在同一组冲突中给出相同建议的比例</p>
                    <p>计算方式：统计该组所有冲突中 LLM 的建议，找出最常见的建议，计算其占比</p>
                    <p>例如：某组有5次冲突，LLM 建议了4次「文件级上下文」、1次「函数级上下文」，则一致性为 <strong>80%</strong></p>
                    <div class="md-callout">
                        <p>一致性越高，说明 LLM 的判断越稳定，该提示的参考价值越高</p>
                    </div>
                </section>

                <section id="sec-rule-hint" class="md-section">
                    <h2>规则提示</h2>
                    <p><strong>py:fastapi:routers</strong> 是命中规则的路径标识：</p>
                    <ul class="md-list">
                        <li><strong>py</strong> — 语言：Python</li>
                        <li><strong>fastapi</strong> — 框架类型</li>
                        <li><strong>routers</strong> — 具体模块</li>
                    </ul>
                    <p>它告诉您这个变更命中了哪条规则，便于定位和调整规则配置</p>
                </section>

                <section id="sec-tags" class="md-section">
                    <h2>标签作用</h2>
                    <p><strong>clustered_changes</strong>、<strong>complete_class</strong> 等标签是代码变更的语义特征</p>
                    <p>系统按「语言 + 标签组合」聚合冲突。例如所有带有 complete_class + clustered_changes 标签的 Python 文件冲突会被归为同一模式</p>
                    <p>当某个标签组合反复触发相同类型的冲突时，说明现有规则对这类代码变更模式的判断可能存在系统性偏差</p>
                </section>
            </main>
        </div> <!-- Close md-doc -->
        </div> <!-- Close dialog-body -->
    `;
