/**
 * Git 提交历史管理模块
 */

const GitHistory = {
    currentProjectRoot: null,
    commits: [],
    currentOffset: 0,
    pageSize: 20,
    hasMore: true,
    currentBranch: null,

    /**
     * 初始化并加载 Git 历史
     */
    async init(projectRoot) {
        if (!projectRoot) {
            this.hide();
            this.renderEmpty();
            return;
        }

        // 显示 Git 历史区域
        this.show();

        this.currentProjectRoot = projectRoot;
        this.commits = [];
        this.currentOffset = 0;
        this.hasMore = true;

        // 加载当前分支
        await this.loadCurrentBranch();

        // 加载提交历史
        await this.load();
    },

    /**
     * 显示 Git 历史区域
     */
    show() {
        const section = document.getElementById('git-history-section');
        console.log('[GitHistory] show() - section element:', section);
        if (section) {
            section.style.display = 'block';
            console.log('[GitHistory] Section display set to block');
        } else {
            console.error('[GitHistory] git-history-section element not found!');
        }
    },

    /**
     * 隐藏 Git 历史区域
     */
    hide() {
        const section = document.getElementById('git-history-section');
        console.log('[GitHistory] hide() - section element:', section);
        if (section) {
            section.style.display = 'none';
            console.log('[GitHistory] Section display set to none');
        }
    },

    /**
     * 加载当前分支
     */
    async loadCurrentBranch() {
        try {
            const resp = await fetch(`/api/git/branch?project_root=${encodeURIComponent(this.currentProjectRoot)}`);
            const data = await resp.json();

            if (data.success) {
                this.currentBranch = data.branch;
                this.updateBranchDisplay();
            }
        } catch (error) {
            console.error('[GitHistory] Failed to load branch:', error);
        }
    },

    /**
     * 加载提交历史
     */
    async load() {
        if (!this.currentProjectRoot) return;

        try {
            const resp = await fetch('/api/git/commits', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_root: this.currentProjectRoot,
                    limit: this.pageSize,
                })
            });

            const data = await resp.json();

            if (data.success) {
                this.commits = data.commits || [];
                this.hasMore = this.commits.length >= this.pageSize;
                this.render();
            } else {
                this.renderError(data.error || '加载失败');
            }
        } catch (error) {
            console.error('[GitHistory] Load error:', error);
            this.renderError(error.message);
        }
    },

    /**
     * 加载更多提交
     */
    async loadMore() {
        if (!this.hasMore || !this.currentProjectRoot) return;

        const button = document.getElementById('git-load-more');
        if (button) {
            button.disabled = true;
            button.textContent = '加载中...';
        }

        try {
            const resp = await fetch('/api/git/commits', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_root: this.currentProjectRoot,
                    limit: this.pageSize,
                    skip: this.commits.length,  // 跳过已加载的提交数量
                })
            });

            const data = await resp.json();

            if (data.success && data.commits) {
                const newCommits = data.commits || [];
                if (newCommits.length > 0) {
                    this.commits = [...this.commits, ...newCommits];
                    this.hasMore = newCommits.length >= this.pageSize;
                    this.render();
                } else {
                    this.hasMore = false;
                    if (button) {
                        button.style.display = 'none';
                    }
                }
            }
        } catch (error) {
            console.error('[GitHistory] Load more error:', error);
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = '加载更多...';
            }
        }
    },

    /**
     * 更新分支显示
     */
    updateBranchDisplay() {
        const branchEl = document.getElementById('git-current-branch');
        if (branchEl && this.currentBranch) {
            branchEl.textContent = `● ${this.currentBranch}`;
            branchEl.style.display = 'inline-block';
        }
    },

    /**
     * 渲染提交列表
     */
    render() {
        const container = document.getElementById('git-commit-list');
        if (!container) return;

        if (this.commits.length === 0) {
            this.renderEmpty();
            return;
        }

        container.innerHTML = '';

        this.commits.forEach((commit, index) => {
            const isLast = index === this.commits.length - 1;
            const commitEl = this.renderCommit(commit, isLast);
            container.appendChild(commitEl);
        });

        // 更新"加载更多"按钮
        const loadMoreBtn = document.getElementById('git-load-more');
        if (loadMoreBtn) {
            loadMoreBtn.style.display = this.hasMore ? 'block' : 'none';
        }
    },

    /**
     * 渲染单个提交
     */
    renderCommit(commit, isLast) {
        const div = document.createElement('div');
        div.className = 'git-commit-item';
        div.dataset.hash = commit.hash;

        // 左侧：分支图
        const graph = document.createElement('div');
        graph.className = 'commit-graph';

        const dot = document.createElement('div');
        dot.className = 'commit-dot';
        if (commit.is_merge) {
            dot.classList.add('merge-commit');
        }

        graph.appendChild(dot);

        if (!isLast) {
            const line = document.createElement('div');
            line.className = 'commit-line';
            graph.appendChild(line);
        }

        // 右侧：提交信息
        const info = document.createElement('div');
        info.className = 'commit-info';

        const header = document.createElement('div');
        header.className = 'commit-header';

        const hash = document.createElement('span');
        hash.className = 'commit-hash';
        hash.textContent = commit.short_hash || commit.hash.substring(0, 7);

        const time = document.createElement('span');
        time.className = 'commit-time';
        time.textContent = commit.relative_date;

        header.appendChild(hash);
        header.appendChild(time);

        const message = document.createElement('div');
        message.className = 'commit-message';
        // 使用 marked.js 渲染 Markdown（breaks: true 让单换行生成 <br>）
        if (typeof marked !== 'undefined' && marked.parse) {
            message.innerHTML = marked.parse(commit.message || '', { breaks: true });
        } else {
            message.textContent = commit.message;
        }

        const author = document.createElement('div');
        author.className = 'commit-author';
        author.textContent = `by ${commit.author}`;

        // Refs (分支/标签)
        if (commit.refs) {
            const refs = document.createElement('div');
            refs.className = 'commit-refs';
            refs.textContent = commit.refs;
            info.appendChild(refs);
        }

        info.appendChild(header);
        info.appendChild(message);
        info.appendChild(author);

        div.appendChild(graph);
        div.appendChild(info);

        // 点击事件（可选：显示详情）
        div.addEventListener('click', () => {
            console.log('[GitHistory] Clicked commit:', commit.hash);
            // TODO: 显示提交详情
        });

        return div;
    },

    /**
     * 渲染空状态
     */
    renderEmpty() {
        const container = document.getElementById('git-commit-list');
        if (!container) return;

        container.innerHTML = `
            <div class="empty-state" style="padding: 2rem; text-align: center;">
                <p style="color: var(--text-muted);">没有找到 Git 提交历史</p>
                <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem;">
                    请确保当前项目是一个 Git 仓库
                </p>
            </div>
        `;

        const loadMoreBtn = document.getElementById('git-load-more');
        if (loadMoreBtn) {
            loadMoreBtn.style.display = 'none';
        }
    },

    /**
     * 渲染错误状态
     */
    renderError(errorMsg) {
        const container = document.getElementById('git-commit-list');
        if (!container) return;

        container.innerHTML = `
            <div class="empty-state" style="padding: 2rem; text-align: center;">
                <p style="color: var(--danger);">加载失败</p>
                <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem;">
                    ${errorMsg || '未知错误'}
                </p>
            </div>
        `;
    },

    /**
     * 刷新历史
     */
    async refresh() {
        this.commits = [];
        this.currentOffset = 0;
        this.hasMore = true;
        await this.load();
    }
};

// 导出到 window 对象（供其他模块使用）
window.GitHistory = GitHistory;
console.log('[GitHistory] Module loaded and exported to window');

// 全局函数（供 HTML 调用）
window.refreshGitHistory = async function () {
    await GitHistory.refresh();
};

window.loadMoreGitCommits = async function () {
    await GitHistory.loadMore();
};

