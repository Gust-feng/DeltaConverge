/**
 * progress.js - 进度面板模块
 */

function setProgressStep(stepName, status = 'active', data = null) {
    const stepEl = document.querySelector(`.step-item[data-step="${stepName}"]`);
    if (!stepEl) return;

    stepEl.classList.remove('pending', 'active', 'completed', 'error');
    stepEl.classList.add(status);

    if (data) {
        updateStepData(stepEl, data);
    }
}

function resetProgressSteps() {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach(step => {
        step.classList.remove('active', 'completed', 'error');
        step.classList.add('pending');
    });
}

function updateStepData(stepElement, data) {
    const dataEl = stepElement.querySelector('.step-data');
    if (!dataEl) return;

    if (typeof data === 'string') {
        dataEl.textContent = data;
    } else if (typeof data === 'object') {
        let html = '';
        for (const [key, val] of Object.entries(data)) {
            html += `<span class="data-item"><span class="data-key">${escapeHtml(key)}:</span> ${escapeHtml(String(val))}</span>`;
        }
        dataEl.innerHTML = html;
    }
}

function resetProgress() {
    resetProgressSteps();

    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');

    if (workflowEntries) workflowEntries.innerHTML = '';
    if (monitorContent) monitorContent.innerHTML = '';
    if (reportContainer) {
        if (reportContainer.dataset && reportContainer.dataset.reportPlaceholder === 'hero' && reportContainer.querySelector('.hero-animation')) {
            return;
        }
        if (reportContainer.dataset) reportContainer.dataset.reportPlaceholder = 'hero';
        reportContainer.innerHTML = `
            <div class="empty-state">
                <div class="hero-animation" style="display:flex;">
                    <svg class="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
                        <path class="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" stroke-width="0.8"></path>
                        <path class="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" stroke-width="1.2"></path>
                        <circle class="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" stroke-width="1.5"></circle>
                        <line class="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" stroke-width="1"></line>
                        <line class="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" stroke-width="1"></line>
                    </svg>
                </div>
            </div>
        `;
    }
}

function toggleProgressPanel(show) {
    const progressPanel = document.getElementById('progressPanel');
    if (!progressPanel) return;

    if (show === undefined) {
        progressPanel.classList.toggle('collapsed');
    } else {
        progressPanel.classList.toggle('collapsed', !show);
    }
}

function toggleLogSummary() {
    // workflowPanel 已移除，各阶段直接暴露，无需折叠
    // 此函数保留以兼容现有调用，但不执行任何操作
}

function toggleMonitorPanel() {
    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        monitorPanel.classList.toggle('collapsed');
    }
}

async function triggerCompletionTransition(reportContent, score = null, alreadySwitched = false) {
    if (!alreadySwitched) {
        setLayoutState(LayoutState.COMPLETED);
    }

    setProgressStep('reviewing', 'completed');

    const reportContainer = document.getElementById('reportContainer');
    if (reportContainer && reportContent) {
        if (reportContainer.dataset) {
            delete reportContainer.dataset.reportPlaceholder;
        }
        reportContainer.innerHTML = marked.parse(reportContent);
    }

    if (score !== null) {
        animateScore(score);
    }

    markAllStepsCompleted();
}

function markAllStepsCompleted() {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach(step => {
        step.classList.remove('pending', 'active', 'error');
        step.classList.add('completed');
    });
}

function animateScore(targetScore, duration = 1000) {
    const scoreEl = document.getElementById('reviewScore');
    if (!scoreEl) return;

    const startScore = 0;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        const easeOut = 1 - Math.pow(1 - progress, 3);
        const currentScore = Math.round(startScore + (targetScore - startScore) * easeOut);

        scoreEl.textContent = currentScore;

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// Export to window
window.setProgressStep = setProgressStep;
window.resetProgressSteps = resetProgressSteps;
window.updateStepData = updateStepData;
window.resetProgress = resetProgress;
window.toggleProgressPanel = toggleProgressPanel;
window.toggleLogSummary = toggleLogSummary;
window.toggleMonitorPanel = toggleMonitorPanel;
window.triggerCompletionTransition = triggerCompletionTransition;
window.markAllStepsCompleted = markAllStepsCompleted;
window.animateScore = animateScore;
