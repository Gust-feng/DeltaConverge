/**
 * progress.js - 进度面板模块
 */

function setProgressStep(stepName, status = 'active', data = null) {
    const stepEl = document.querySelector(`.progress-step[data-step="${stepName}"]`);
    if (!stepEl) return;
    
    stepEl.classList.remove('pending', 'active', 'completed', 'error');
    stepEl.classList.add(status);
    
    if (data) {
        updateStepData(stepEl, data);
    }
}

function resetProgressSteps() {
    const steps = document.querySelectorAll('.progress-step');
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
        reportContainer.innerHTML = '<div class="waiting-state"><p>等待审查结果...</p></div>';
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
    const workflowPanel = document.getElementById('workflowPanel');
    if (workflowPanel) {
        workflowPanel.classList.toggle('collapsed');
    }
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
        reportContainer.innerHTML = marked.parse(reportContent);
    }
    
    if (score !== null) {
        animateScore(score);
    }
    
    markAllStepsCompleted();
}

function markAllStepsCompleted() {
    const steps = document.querySelectorAll('.progress-step');
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
