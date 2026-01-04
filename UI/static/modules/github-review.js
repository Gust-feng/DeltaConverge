/**
 * GitHub PR Review Controller
 * Handles PR URL input and navigation to Commit History
 */

async function startGitHubReview() {
    const input = document.getElementById('prUrlInput');
    const btn = document.getElementById('btnStartPrReview');
    const errorDiv = document.getElementById('prReviewError');

    if (!input || !btn || !errorDiv) return;

    const url = input.value.trim();
    const projectRoot = window.currentProjectRoot;

    // Reset error
    errorDiv.style.display = 'none';
    errorDiv.textContent = '';

    // Validation
    if (!url) {
        showError('请输入 PR URL');
        return;
    }

    if (!projectRoot) {
        showError('请先在左上角选择本地仓库文件夹');
        return;
    }

    // Set loading state
    btn.disabled = true;
    const originalBtnContent = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> 解析中...';

    try {
        // 1. Fetch PR Info to get base/head SHA
        const response = await fetch('/api/github/pr-info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });

        const data = await response.json();

        if (!data.success) {
            throw new Error(data.error || '解析 PR 失败');
        }

        const { base_sha, head_sha, title, pr_number, owner, repo } = data;

        if (!base_sha || !head_sha) {
            throw new Error('无法获取 PR 的提交信息 (SHA 缺失)');
        }

        console.log(`[GitHub PR] Parsed: #${pr_number} ${title} (${base_sha.substring(0, 7)}...${head_sha.substring(0, 7)})`);

        // 保存原始PR信息用于后续创建分支
        if (typeof setSourcePR === 'function') {
            setSourcePR(pr_number, head_sha, base_sha);
        }

        // 2. 验证 base 和 head commit 是否在本地仓库中存在
        btn.innerHTML = '<span class="spinner"></span> 验证提交...';

        const checkCommit = async (hash) => {
            const res = await fetch('/api/git/check-commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_root: projectRoot, commit_hash: hash })
            });
            const result = await res.json();
            return result.success && result.exists;
        };

        let [baseExists, headExists] = await Promise.all([
            checkCommit(base_sha),
            checkCommit(head_sha)
        ]);

        // 如果提交不存在，尝试自动 fetch PR refs
        if (!baseExists || !headExists) {
            btn.innerHTML = '<span class="spinner"></span> 正在获取 PR 提交...';

            try {
                const fetchRes = await fetch('/api/git/fetch-pr', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        project_root: projectRoot,
                        pr_number: pr_number
                    })
                });
                const fetchResult = await fetchRes.json();

                if (fetchResult.success) {
                    console.log(`[GitHub PR] Fetched PR #${pr_number} refs successfully`);
                    // 重新检查提交是否存在
                    [baseExists, headExists] = await Promise.all([
                        checkCommit(base_sha),
                        checkCommit(head_sha)
                    ]);
                }
            } catch (fetchErr) {
                console.warn('[GitHub PR] Auto-fetch failed:', fetchErr);
            }
        }

        if (!baseExists || !headExists) {
            const missing = [];
            if (!baseExists) missing.push(`Base (${base_sha.substring(0, 7)})`);
            if (!headExists) missing.push(`Head (${head_sha.substring(0, 7)})`);
            throw new Error(`本地仓库缺少提交: ${missing.join(', ')}。\n\n这可能是因为 PR 来自 Fork 仓库。\n请在仓库目录运行:\ngit fetch origin refs/pull/${pr_number}/head`);
        }

        // 3. Switch to Diff Page (Commit Mode)
        if (typeof switchPage === 'function') {
            switchPage('diff');
        }

        // Wait a bit for page switch
        setTimeout(() => {
            // 4. Select Commit Mode
            if (typeof selectDiffMode === 'function') {
                selectDiffMode('commit');
            }

            // 5. Set Commit Range
            setTimeout(() => {
                if (typeof window.onSelectCommitFrom === 'function') {
                    window.onSelectCommitFrom(base_sha);
                    const fromText = document.getElementById('commitFromText');
                    if (fromText) fromText.textContent = `Base: ${base_sha.substring(0, 7)}`;
                }

                if (typeof window.onSelectCommitTo === 'function') {
                    window.onSelectCommitTo(head_sha);
                    const toText = document.getElementById('commitToText');
                    if (toText) toText.textContent = `Head: ${head_sha.substring(0, 7)}`;
                }

                // 6. Trigger Load
                if (typeof window.loadCommitRangeDiff === 'function') {
                    window.loadCommitRangeDiff();
                }

                // Show success toast
                if (typeof showToast === 'function') {
                    showToast(`已加载 PR #${pr_number}: ${title || 'No Title'}`, 'success');
                }

            }, 300); // Wait for commit mode to init

        }, 100);

    } catch (e) {
        console.error('[GitHub PR] Error:', e);
        showError(e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnContent;
    }

    function showError(msg) {
        errorDiv.textContent = msg;
        errorDiv.style.display = 'block';
    }
}

// Export to window
window.startGitHubReview = startGitHubReview;

// 加载并显示本地仓库信息
async function loadPrPageRepoInfo() {
    const card = document.getElementById('prRepoInfoCard');
    if (!card) return;

    const projectRoot = window.currentProjectRoot;
    if (!projectRoot) {
        card.style.display = 'none';
        return;
    }

    try {
        const res = await fetch('/api/git/repo-info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: projectRoot })
        });
        const data = await res.json();

        if (data.success) {
            // 仓库名和分支
            document.getElementById('repoInfoName').textContent = data.repo_name || '当前仓库';
            document.getElementById('repoInfoBranch').textContent = data.branch || '-';

            // 统计信息
            document.getElementById('repoInfoCommitCount').textContent = data.commit_count || '0';
            document.getElementById('repoInfoModified').textContent = data.modified_count || '0';
            document.getElementById('repoInfoStaged').textContent = data.staged_count || '0';
            document.getElementById('repoInfoUntracked').textContent = data.untracked_count || '0';

            // 标签
            const tagContainer = document.getElementById('repoInfoTagContainer');
            if (data.latest_tag && tagContainer) {
                document.getElementById('repoInfoLatestTag').textContent = data.latest_tag;
                tagContainer.style.display = 'flex';
            } else if (tagContainer) {
                tagContainer.style.display = 'none';
            }

            // 远程 URL
            const remoteEl = document.getElementById('repoInfoRemote');
            if (remoteEl) {
                const url = data.remote_url || '';
                remoteEl.textContent = url || '(未配置)';
                // 转换为可点击链接
                if (url.includes('github.com')) {
                    let webUrl = url.replace(/\.git$/, '').replace(/^git@github\.com:/, 'https://github.com/');
                    remoteEl.href = webUrl;
                } else {
                    remoteEl.href = '#';
                }
            }

            card.style.display = 'block';
        } else {
            card.style.display = 'none';
        }
    } catch (e) {
        console.error('[PR Page] Failed to load repo info:', e);
        card.style.display = 'none';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

window.loadPrPageRepoInfo = loadPrPageRepoInfo;

// 监听项目根目录变化
const originalSetRoot = window.setCurrentProjectRoot;
if (typeof originalSetRoot === 'function') {
    window.setCurrentProjectRoot = async function (...args) {
        const result = await originalSetRoot.apply(this, args);
        // 如果当前在 github-pr 页面，刷新仓库信息
        const prPage = document.getElementById('page-github-pr');
        if (prPage && prPage.style.display !== 'none') {
            loadPrPageRepoInfo();
        }
        return result;
    };
}

// 页面切换时加载
document.addEventListener('DOMContentLoaded', () => {
    // 观察 page-github-pr 的 display 变化
    const prPage = document.getElementById('page-github-pr');
    if (prPage) {
        const observer = new MutationObserver(() => {
            if (prPage.style.display !== 'none') {
                loadPrPageRepoInfo();
            }
        });
        observer.observe(prPage, { attributes: true, attributeFilter: ['style'] });
    }
});
