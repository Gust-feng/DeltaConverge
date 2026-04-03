/**
 * timer.js - 计时器模块
 */

let reviewStartTime = null;
let reviewTimerInterval = null;

function startReviewTimer() {
    if (reviewTimerInterval) clearInterval(reviewTimerInterval);
    reviewStartTime = Date.now();
    const timerEl = document.getElementById('reviewTimer');
    if (timerEl) timerEl.textContent = '00:00';
    
    reviewTimerInterval = setInterval(() => {
        if (!reviewStartTime) return;
        const elapsed = Date.now() - reviewStartTime;
        const seconds = Math.floor(elapsed / 1000);
        const m = Math.floor(seconds / 60).toString().padStart(2, '0');
        const s = (seconds % 60).toString().padStart(2, '0');
        if (timerEl) timerEl.textContent = `${m}:${s}`;
    }, 1000);
}

function stopReviewTimer() {
    if (reviewTimerInterval) {
        clearInterval(reviewTimerInterval);
        reviewTimerInterval = null;
    }
    
    if (reviewStartTime) {
        const elapsed = Date.now() - reviewStartTime;
        const seconds = Math.floor(elapsed / 1000);
        const m = Math.floor(seconds / 60).toString().padStart(2, '0');
        const s = (seconds % 60).toString().padStart(2, '0');
        const timerEl = document.getElementById('reviewTimer');
        if (timerEl) timerEl.textContent = `总用时 ${m}:${s}`;
    }
}

// LocalStorage helpers
function getLastSessionId() {
    try { return localStorage.getItem('lastSessionId') || null; } catch (e) { return null; }
}

function setLastSessionId(sid) {
    try { if (sid) localStorage.setItem('lastSessionId', sid); } catch (e) {}
}

function clearLastSessionId() {
    try { localStorage.removeItem('lastSessionId'); } catch (e) {}
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    stopReviewTimer();
    if (typeof stopSessionPolling === 'function') stopSessionPolling();
});

// Export to window
window.startReviewTimer = startReviewTimer;
window.stopReviewTimer = stopReviewTimer;
window.getLastSessionId = getLastSessionId;
window.setLastSessionId = setLastSessionId;
window.clearLastSessionId = clearLastSessionId;
