import { useEffect, useRef } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

export const PROXIMITY_THRESHOLD = 150;
export const GLOW_INTENSITY = 8;

/**
 * 1:1 复刻 rule-growth.js:1269-1321 的 “?” 按钮与鼠标光束。
 * 视觉公式完全一致；React 生命周期内只绑定一次，卸载时移除监听并清理内联样式。
 */
export function HintsHelpButton({ onClick }: { onClick: (event: ReactMouseEvent<HTMLButtonElement>) => void }) {
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const hintsHelpBtn = buttonRef.current;
    if (!hintsHelpBtn) return;

    const handleMouseMove = (event: MouseEvent) => {
      const rect = hintsHelpBtn.getBoundingClientRect();
      const btnCenterX = rect.left + rect.width / 2;
      const btnCenterY = rect.top + rect.height / 2;

      const dx = event.clientX - btnCenterX;
      const dy = event.clientY - btnCenterY;
      const distance = Math.sqrt(dx * dx + dy * dy);

      if (distance <= rect.width / 2) {
        hintsHelpBtn.style.boxShadow = `0 0 12px rgba(59, 130, 246, 0.6)`;
        hintsHelpBtn.style.filter = `brightness(1.1)`;
      } else if (distance < PROXIMITY_THRESHOLD) {
        const angle = Math.atan2(dy, dx);
        const glowX = Math.cos(angle) * GLOW_INTENSITY;
        const glowY = Math.sin(angle) * GLOW_INTENSITY;
        const intensity = 1 - distance / PROXIMITY_THRESHOLD;
        const glowColor = `rgba(59, 130, 246, ${intensity * 0.8})`;
        const glowSpread = Math.round(4 + intensity * 6);

        hintsHelpBtn.style.boxShadow = `${glowX}px ${glowY}px ${glowSpread}px ${glowColor}`;
        hintsHelpBtn.style.filter = `brightness(${1 + intensity * 0.2})`;
      } else {
        hintsHelpBtn.style.boxShadow = "none";
        hintsHelpBtn.style.filter = "none";
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      hintsHelpBtn.style.boxShadow = "";
      hintsHelpBtn.style.filter = "";
    };
  }, []);

  return (
    <button ref={buttonRef} id="hintsHelpBtn" className="hints-help-btn" type="button" onClick={onClick}>
      <span className="help-text">?</span>
    </button>
  );
}
