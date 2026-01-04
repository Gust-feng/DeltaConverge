/**
 * PR Submit Controller
 * 处理审查完成后提交PR的功能
 */

// 初始化状态
let prSubmitState = {
    projectRoot: null,
    isGithubRepo: false,
    owner: null,
    repo: null,
    defaultBranch: null,
    currentBranch: null,
    // 原始PR信息（用于基于历史PR创建分支）
    sourcePRNumber: null,
    sourceHeadSha: null,
    sourceBaseSha: null  // 原PR的base commit，用作新PR的目标分支
};

/**
 * 初始化PR提交模块
 */
async function initPRSubmit() {
    prSubmitState.projectRoot = window.currentProjectRoot;
    if (!prSubmitState.projectRoot) {
        return;
    }

    try {
        // 获取GitHub仓库信息
        const res = await fetch('/api/github/repo-info-from-remote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: prSubmitState.projectRoot })
        });
        const data = await res.json();

        if (data.success && data.is_github) {
            prSubmitState.isGithubRepo = true;
            prSubmitState.owner = data.owner;
            prSubmitState.repo = data.repo;
            prSubmitState.defaultBranch = data.default_branch || 'main';
        } else {
            prSubmitState.isGithubRepo = false;
        }

        // 获取当前分支
        const branchRes = await fetch('/api/git/current-branch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: prSubmitState.projectRoot })
        });
        const branchData = await branchRes.json();
        if (branchData.success) {
            prSubmitState.currentBranch = branchData.branch;
        }

        // 尝试从会话元数据恢复原始PR信息
        if (!prSubmitState.sourcePRNumber && window.currentSessionId) {
            const sRes = await fetch(`/api/sessions/${window.currentSessionId}`);
            if (sRes.ok) {
                const session = await sRes.json();
                const info = session.metadata ? session.metadata.source_pr_info : null;
                if (info) {
                    console.log('[PR Submit] Restored source PR info from session:', info);
                    setSourcePR(info.number, info.head_sha, info.base_sha);
                }
            }
        }

    } catch (e) {
        console.error('[PR Submit] Init error:', e);
    }
}

/**
 * 打开PR提交模态框
 */
function openPRSubmitModal() {
    // 检查是否已选择项目
    if (!window.currentProjectRoot) {
        if (typeof showToast === 'function') {
            showToast('请先选择项目文件夹', 'error');
        }
        return;
    }

    // 初始化并显示
    initPRSubmit().then(() => {
        const modal = document.getElementById('prSubmitModal');
        if (!modal) {
            createPRSubmitModal();
        }

        // 填充默认值
        updatePRSubmitForm();

        // 显示模态框
        document.getElementById('prSubmitModal').style.display = 'flex';
    });
}

/**
 * 关闭PR提交模态框
 */
function closePRSubmitModal() {
    const modal = document.getElementById('prSubmitModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 创建PR提交模态框HTML
 */
function createPRSubmitModal() {
    const modalHtml = `
        <div id="prSubmitModal" class="modal-overlay" style="display: none;">
            <div class="modal-container" style="max-width: 600px; width: 90%;">
                <div class="modal-header">
                    <h3>🚀 创建 Pull Request</h3>
                    <button class="modal-close-btn" onclick="closePRSubmitModal()">
                        <svg class="icon"><use href="#icon-x"></use></svg>
                    </button>
                </div>
                <div class="modal-body">
                    <!-- GitHub 状态提示 -->
                    <div id="prGithubStatus" class="pr-status-banner" style="margin-bottom: 1rem;"></div>
                    
                    <!-- 分支名称 -->
                    <div class="form-group">
                        <label for="prBranchName">源分支名称 <span class="required">*</span></label>
                        <input type="text" id="prBranchName" class="form-input" 
                               placeholder="review/pr-123" autocomplete="off">
                        <div id="prBranchHint" class="form-hint"></div>
                    </div>
                    
                    <!-- PR 标题 -->
                    <div class="form-group">
                        <label for="prTitle">PR 标题 <span class="required">*</span></label>
                        <input type="text" id="prTitle" class="form-input" 
                               placeholder="[代码审查] PR#123 审查结果" autocomplete="off">
                    </div>
                    
                    <!-- PR 描述 -->
                    <div class="form-group">
                        <label for="prBody">PR 描述 <span style="color: var(--text-muted); font-weight: normal;">(留空则自动生成摘要)</span></label>
                        <textarea id="prBody" class="form-textarea" rows="3" 
                                  placeholder="将自动使用审查报告摘要..."></textarea>
                    </div>
                    
                    <!-- 目标分支 -->
                    <div class="form-group">
                        <label for="prBaseBranch">目标分支</label>
                        <input type="text" id="prBaseBranch" class="form-input" 
                               placeholder="main">
                        <div class="form-hint">留空使用仓库默认分支</div>
                    </div>
                    
                    <!-- 选项 -->
                    <div class="form-group" style="display: flex; flex-direction: column; gap: 0.5rem;">
                        <label class="checkbox-label">
                            <input type="checkbox" id="prIncludeReview" checked>
                            <span>📝 附带审查评论 (将审查结果作为行级评论添加)</span>
                        </label>
                        <label class="checkbox-label">
                            <input type="checkbox" id="prDraft">
                            <span>创建为草稿 PR</span>
                        </label>
                    </div>
                    
                    <!-- 错误信息 -->
                    <div id="prSubmitError" class="error-message" style="display: none;"></div>
                    
                    <!-- 进度信息 -->
                    <div id="prSubmitProgress" class="progress-info" style="display: none;">
                        <div class="progress-spinner"></div>
                        <span id="prSubmitProgressText">正在处理...</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn-secondary" onclick="closePRSubmitModal()">取消</button>
                    <button id="prSubmitBtn" class="btn-primary" onclick="submitPRWithReview()">
                        <svg class="icon"><use href="#icon-send"></use></svg>
                        创建 PR 并提交审查
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // 添加分支名称验证
    const branchInput = document.getElementById('prBranchName');
    if (branchInput) {
        branchInput.addEventListener('input', debounce(validateBranchName, 300));
    }
}

/**
 * 更新PR提交表单的默认值
 */
function updatePRSubmitForm() {
    // 更新GitHub状态提示
    const statusBanner = document.getElementById('prGithubStatus');
    if (statusBanner) {
        if (prSubmitState.isGithubRepo) {
            statusBanner.innerHTML = `
                <span class="status-ok">✓</span>
                <span>GitHub 仓库: <strong>${prSubmitState.owner}/${prSubmitState.repo}</strong></span>
            `;
            statusBanner.className = 'pr-status-banner status-success';
        } else {
            statusBanner.innerHTML = `
                <span class="status-error">✗</span>
                <span>当前仓库不是 GitHub 仓库</span>
            `;
            statusBanner.className = 'pr-status-banner status-error';
        }
    }

    // 设置目标分支默认值 - GitHub API需要分支名称，不能是commit SHA
    const baseBranchInput = document.getElementById('prBaseBranch');
    if (baseBranchInput && prSubmitState.defaultBranch) {
        baseBranchInput.placeholder = prSubmitState.defaultBranch;
        // 不自动填充，让用户确认或使用默认值
    }

    // 生成默认分支名（确保唯一性）
    const branchInput = document.getElementById('prBranchName');
    if (branchInput && !branchInput.value) {
        // 如果有原PR编号，使用它作为分支名的一部分
        let baseName;
        if (prSubmitState.sourcePRNumber) {
            baseName = `review/pr-${prSubmitState.sourcePRNumber}`;
        } else {
            const timestamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
            baseName = `review/${timestamp}`;
        }

        // 自动生成唯一分支名
        generateUniqueBranchName(baseName).then(uniqueName => {
            if (branchInput && !branchInput.value) {
                branchInput.value = uniqueName;
            }
        });
    }
}

/**
 * 生成唯一的分支名称
 * 如果baseame已存在，会自动添加递增后缀 (-2, -3, ...)
 */
async function generateUniqueBranchName(baseName) {
    let candidateName = baseName;
    let suffix = 1;
    const maxAttempts = 20;  // 防止无限循环

    while (suffix <= maxAttempts) {
        try {
            const res = await fetch('/api/git/branch-exists', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_root: prSubmitState.projectRoot,
                    branch_name: candidateName
                })
            });
            const data = await res.json();

            if (!data.exists) {
                // 分支不存在，可以使用
                return candidateName;
            }

            // 分支已存在，尝试下一个后缀
            suffix++;
            candidateName = `${baseName}-${suffix}`;

        } catch (e) {
            console.warn('[PR Submit] Error checking branch:', e);
            // 出错时直接返回带时间戳的名称确保唯一
            const ts = Date.now().toString(36);
            return `${baseName}-${ts}`;
        }
    }

    // 超过最大尝试次数，使用时间戳
    const ts = Date.now().toString(36);
    return `${baseName}-${ts}`;
}

/**
 * 验证分支名称
 */
async function validateBranchName() {
    const branchInput = document.getElementById('prBranchName');
    const hint = document.getElementById('prBranchHint');
    if (!branchInput || !hint) return;

    const branchName = branchInput.value.trim();
    if (!branchName) {
        hint.textContent = '';
        hint.className = 'form-hint';
        return;
    }

    // 检查分支名格式
    if (!/^[\w\-./]+$/.test(branchName)) {
        hint.textContent = '分支名只能包含字母、数字、下划线、横线、点和斜线';
        hint.className = 'form-hint error';
        return;
    }

    // 检查分支是否已存在
    try {
        const res = await fetch('/api/git/branch-exists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_root: prSubmitState.projectRoot,
                branch_name: branchName
            })
        });
        const data = await res.json();

        if (data.exists) {
            hint.textContent = '该分支已存在';
            hint.className = 'form-hint error';
        } else {
            hint.textContent = '分支名可用 ✓';
            hint.className = 'form-hint success';
        }
    } catch (e) {
        console.error('[PR Submit] Branch check error:', e);
    }
}

/**
 * 提交PR
 */
async function submitPR() {
    const branchName = document.getElementById('prBranchName')?.value.trim();
    const title = document.getElementById('prTitle')?.value.trim();
    const body = document.getElementById('prBody')?.value.trim();
    const baseBranch = document.getElementById('prBaseBranch')?.value.trim();
    const isDraft = document.getElementById('prDraft')?.checked || false;

    const errorDiv = document.getElementById('prSubmitError');
    const progressDiv = document.getElementById('prSubmitProgress');
    const progressText = document.getElementById('prSubmitProgressText');
    const submitBtn = document.getElementById('prSubmitBtn');

    // 验证必填项
    if (!branchName) {
        showPRError('请输入分支名称');
        return;
    }
    if (!title) {
        showPRError('请输入PR标题');
        return;
    }

    if (!prSubmitState.isGithubRepo) {
        showPRError('当前仓库不是GitHub仓库');
        return;
    }

    // 隐藏错误，显示进度
    if (errorDiv) errorDiv.style.display = 'none';
    if (progressDiv) progressDiv.style.display = 'flex';
    if (submitBtn) submitBtn.disabled = true;

    try {
        // 使用一键提交API
        if (progressText) progressText.textContent = '创建分支并提交...';

        const res = await fetch('/api/github/create-pr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_root: prSubmitState.projectRoot,
                title: title,
                body: body || null,
                head_branch: branchName,
                base_branch: baseBranch || null,
                draft: isDraft,
                push_first: true
            })
        });

        const data = await res.json();

        if (data.success) {
            // 成功
            closePRSubmitModal();

            if (typeof showToast === 'function') {
                showToast(`PR #${data.pr_number} 创建成功!`, 'success');
            }

            // 在新标签页打开PR
            if (data.pr_url) {
                window.open(data.pr_url, '_blank');
            }
        } else {
            showPRError(data.error || '创建PR失败');
        }

    } catch (e) {
        console.error('[PR Submit] Error:', e);
        showPRError('请求失败: ' + e.message);
    } finally {
        if (progressDiv) progressDiv.style.display = 'none';
        if (submitBtn) submitBtn.disabled = false;
    }
}

/**
 * 显示PR提交错误
 */
function showPRError(message) {
    const errorDiv = document.getElementById('prSubmitError');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

/**
 * 防抖函数
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 创建PR并附带审查评论（综合功能）
 */
async function submitPRWithReview() {
    const branchName = document.getElementById('prBranchName')?.value.trim();
    const title = document.getElementById('prTitle')?.value.trim();
    const body = document.getElementById('prBody')?.value.trim();
    const baseBranch = document.getElementById('prBaseBranch')?.value.trim();
    const includeReview = document.getElementById('prIncludeReview')?.checked || false;
    const isDraft = document.getElementById('prDraft')?.checked || false;

    const errorDiv = document.getElementById('prSubmitError');
    const progressDiv = document.getElementById('prSubmitProgress');
    const progressText = document.getElementById('prSubmitProgressText');
    const submitBtn = document.getElementById('prSubmitBtn');

    // 验证必填项
    if (!branchName) {
        showPRError('请输入分支名称');
        return;
    }
    if (!title) {
        showPRError('请输入PR标题');
        return;
    }

    if (!prSubmitState.isGithubRepo) {
        showPRError('当前仓库不是GitHub仓库');
        return;
    }

    // 隐藏错误，显示进度
    if (errorDiv) errorDiv.style.display = 'none';
    if (progressDiv) progressDiv.style.display = 'flex';
    if (submitBtn) submitBtn.disabled = true;

    try {
        // 获取审查报告内容
        let reviewReport = null;
        if (includeReview) {
            // 优先使用全局暴露的原始Markdown内容（保留格式）
            if (window.currentReviewReportRaw && typeof window.currentReviewReportRaw === 'string') {
                reviewReport = window.currentReviewReportRaw;
            } else {
                // 回退：从DOM获取（可能丢失Markdown格式）
                const reportContainer = document.getElementById('reportContainer');
                if (reportContainer) {
                    reviewReport = reportContainer.innerText || reportContainer.textContent || '';
                }
            }
        }

        if (progressText) progressText.textContent = '正在创建PR...';

        // 使用综合API
        const res = await fetch('/api/github/create-pr-with-review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_root: prSubmitState.projectRoot,
                title: title,
                body: body || null,
                head_branch: branchName,
                base_branch: baseBranch || null,
                source_commit: prSubmitState.sourceHeadSha || null,  // 基于原PR的head_sha创建源分支
                base_commit: prSubmitState.sourceBaseSha || null,    // 基于原PR的base_sha创建目标分支
                review_report: reviewReport,
                draft: isDraft,
                push_first: true
            })
        });

        const data = await res.json();

        if (data.success) {
            closePRSubmitModal();

            let message = `PR #${data.pr_number} 创建成功!`;
            if (data.comments_count > 0) {
                message += ` 已添加 ${data.comments_count} 条审查评论`;
            }

            if (typeof showToast === 'function') {
                showToast(message, 'success');
            }

            // 在新标签页打开PR
            if (data.pr_url) {
                window.open(data.pr_url, '_blank');
            }
        } else {
            showPRError(data.error || '创建PR失败');
        }

    } catch (e) {
        console.error('[PR Submit] Error:', e);
        showPRError('请求失败: ' + e.message);
    } finally {
        if (progressDiv) progressDiv.style.display = 'none';
        if (submitBtn) submitBtn.disabled = false;
    }
}

/**
 * 设置原始PR信息（用于基于历史PR创建分支）
 */
function setSourcePR(prNumber, headSha, baseSha) {
    prSubmitState.sourcePRNumber = prNumber;
    prSubmitState.sourceHeadSha = headSha;
    prSubmitState.sourceBaseSha = baseSha;
    console.log('[PR Submit] Set source PR:', prNumber, 'head_sha:', headSha, 'base_sha:', baseSha);
}

// Export to window
window.openPRSubmitModal = openPRSubmitModal;
window.closePRSubmitModal = closePRSubmitModal;
window.submitPR = submitPR;
window.submitPRWithReview = submitPRWithReview;
window.initPRSubmit = initPRSubmit;
window.setSourcePR = setSourcePR;

// ============================================================================
// 提交审查结果到 PR Review
// ============================================================================

/**
 * 存储当前PR信息（用于审查结果提交）
 */
let currentPRInfo = {
    owner: null,
    repo: null,
    pr_number: null
};

/**
 * 设置当前PR信息
 */
function setCurrentPRInfo(owner, repo, prNumber) {
    currentPRInfo.owner = owner;
    currentPRInfo.repo = repo;
    currentPRInfo.pr_number = prNumber;
    console.log('[PR Submit] Set current PR info:', currentPRInfo);
}

/**
 * 打开提交审查结果模态框
 */
function openSubmitReviewModal() {
    // 检查是否有审查报告
    const reportContainer = document.getElementById('reportContainer');
    if (!reportContainer) {
        if (typeof showToast === 'function') {
            showToast('请先完成代码审查', 'error');
        }
        return;
    }

    const reportContent = reportContainer.innerText || reportContainer.textContent || '';
    if (!reportContent.trim() || reportContent.includes('选择需要审查的代码文件')) {
        if (typeof showToast === 'function') {
            showToast('审查报告为空，请先完成审查', 'error');
        }
        return;
    }

    // 创建模态框
    let modal = document.getElementById('submitReviewModal');
    if (!modal) {
        createSubmitReviewModal();
        modal = document.getElementById('submitReviewModal');
    }

    // 尝试自动填充PR信息
    autoFillPRInfo();

    modal.style.display = 'flex';
}

/**
 * 关闭提交审查结果模态框
 */
function closeSubmitReviewModal() {
    const modal = document.getElementById('submitReviewModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 创建提交审查结果模态框
 */
function createSubmitReviewModal() {
    const modalHtml = `
        <div id="submitReviewModal" class="modal-overlay" style="display: none;">
            <div class="modal-container" style="max-width: 550px; width: 90%;">
                <div class="modal-header">
                    <h3>📤 提交审查结果到 PR</h3>
                    <button class="modal-close-btn" onclick="closeSubmitReviewModal()">
                        <svg class="icon"><use href="#icon-x"></use></svg>
                    </button>
                </div>
                <div class="modal-body">
                    <p style="color: var(--text-muted); margin-bottom: 1rem; font-size: 0.9rem;">
                        将审查报告中的问题和建议作为 PR Review 评论提交到 GitHub。
                    </p>
                    
                    <!-- 仓库信息 -->
                    <div class="form-group">
                        <label for="reviewOwner">仓库所有者 <span class="required">*</span></label>
                        <input type="text" id="reviewOwner" class="form-input" placeholder="owner" autocomplete="off">
                    </div>
                    
                    <div class="form-group">
                        <label for="reviewRepo">仓库名称 <span class="required">*</span></label>
                        <input type="text" id="reviewRepo" class="form-input" placeholder="repository" autocomplete="off">
                    </div>
                    
                    <div class="form-group">
                        <label for="reviewPRNumber">PR 编号 <span class="required">*</span></label>
                        <input type="number" id="reviewPRNumber" class="form-input" placeholder="123" min="1" autocomplete="off">
                    </div>
                    
                    <!-- Review事件类型 -->
                    <div class="form-group">
                        <label for="reviewEvent">Review 类型</label>
                        <select id="reviewEvent" class="form-input">
                            <option value="COMMENT">评论 (COMMENT)</option>
                            <option value="APPROVE">批准 (APPROVE)</option>
                            <option value="REQUEST_CHANGES">请求修改 (REQUEST_CHANGES)</option>
                        </select>
                    </div>
                    
                    <!-- 错误信息 -->
                    <div id="submitReviewError" class="error-message" style="display: none;"></div>
                    
                    <!-- 进度信息 -->
                    <div id="submitReviewProgress" class="progress-info" style="display: none;">
                        <div class="progress-spinner"></div>
                        <span id="submitReviewProgressText">正在提交...</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn-secondary" onclick="closeSubmitReviewModal()">取消</button>
                    <button id="submitReviewBtn" class="btn-primary" onclick="submitReviewToPR()">
                        <svg class="icon"><use href="#icon-send"></use></svg>
                        提交 Review
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

/**
 * 自动填充PR信息
 */
function autoFillPRInfo() {
    // 尝试从存储的信息填充
    if (currentPRInfo.owner) {
        const ownerInput = document.getElementById('reviewOwner');
        if (ownerInput && !ownerInput.value) ownerInput.value = currentPRInfo.owner;
    }
    if (currentPRInfo.repo) {
        const repoInput = document.getElementById('reviewRepo');
        if (repoInput && !repoInput.value) repoInput.value = currentPRInfo.repo;
    }
    if (currentPRInfo.pr_number) {
        const prInput = document.getElementById('reviewPRNumber');
        if (prInput && !prInput.value) prInput.value = currentPRInfo.pr_number;
    }
}

/**
 * 提交审查结果到PR
 */
async function submitReviewToPR() {
    const owner = document.getElementById('reviewOwner')?.value.trim();
    const repo = document.getElementById('reviewRepo')?.value.trim();
    const prNumberStr = document.getElementById('reviewPRNumber')?.value.trim();
    const event = document.getElementById('reviewEvent')?.value || 'COMMENT';

    const errorDiv = document.getElementById('submitReviewError');
    const progressDiv = document.getElementById('submitReviewProgress');
    const submitBtn = document.getElementById('submitReviewBtn');

    // 验证
    if (!owner || !repo || !prNumberStr) {
        showSubmitReviewError('请填写完整的仓库信息和PR编号');
        return;
    }

    const prNumber = parseInt(prNumberStr, 10);
    if (isNaN(prNumber) || prNumber <= 0) {
        showSubmitReviewError('PR编号无效');
        return;
    }

    // 获取审查报告内容
    const reportContainer = document.getElementById('reportContainer');
    const reviewReport = reportContainer?.innerHTML || '';

    if (!reviewReport.trim()) {
        showSubmitReviewError('审查报告为空');
        return;
    }

    // 显示进度
    if (errorDiv) errorDiv.style.display = 'none';
    if (progressDiv) progressDiv.style.display = 'flex';
    if (submitBtn) submitBtn.disabled = true;

    try {
        const res = await fetch('/api/github/submit-review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                owner: owner,
                repo: repo,
                pr_number: prNumber,
                review_report: reviewReport,
                event: event
            })
        });

        const data = await res.json();

        if (data.success) {
            closeSubmitReviewModal();

            if (typeof showToast === 'function') {
                showToast(`Review 提交成功! 共 ${data.issues_count} 个问题, ${data.comments_count} 条评论`, 'success');
            }

            // 打开PR页面
            if (data.html_url) {
                window.open(data.html_url, '_blank');
            } else {
                window.open(`https://github.com/${owner}/${repo}/pull/${prNumber}`, '_blank');
            }
        } else {
            showSubmitReviewError(data.error || '提交失败');
        }

    } catch (e) {
        console.error('[PR Submit] Submit review error:', e);
        showSubmitReviewError('请求失败: ' + e.message);
    } finally {
        if (progressDiv) progressDiv.style.display = 'none';
        if (submitBtn) submitBtn.disabled = false;
    }
}

/**
 * 显示提交审查结果错误
 */
function showSubmitReviewError(message) {
    const errorDiv = document.getElementById('submitReviewError');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    }
}

// Export new functions to window
window.openSubmitReviewModal = openSubmitReviewModal;
window.closeSubmitReviewModal = closeSubmitReviewModal;
window.submitReviewToPR = submitReviewToPR;
window.setCurrentPRInfo = setCurrentPRInfo;
window.getSourcePR = () => prSubmitState;

