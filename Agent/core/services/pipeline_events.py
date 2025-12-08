import time
from typing import Any, Callable, Dict, List, Optional


class PipelineEvents:
    def __init__(self, callback: Callable[[Dict[str, Any]], None] | None) -> None:
        self.callback = callback

    def emit(self, evt: Dict[str, Any]) -> None:
        if not self.callback:
            return
        try:
            self.callback(evt)
        except Exception:
            pass

    def stage_start(self, stage: str) -> None:
        self.emit({"type": "pipeline_stage_start", "stage": stage})

    def stage_end(self, stage: str, **summary: Any) -> None:
        evt: Dict[str, Any] = {"type": "pipeline_stage_end", "stage": stage}
        if summary:
            evt["summary"] = summary
        self.emit(evt)

    def bundle_item(self, item: Dict[str, Any]) -> None:
        self.emit({
            "type": "bundle_item",
            "unit_id": item.get("unit_id"),
            "final_context_level": item.get("final_context_level"),
            "location": (item.get("meta") or {}).get("location"),
        })


    # =========================================================================
    # 扫描器进度事件 (Requirements 1.1, 1.2, 1.4, 2.1)
    # =========================================================================

    def scanner_start(self, scanner_name: str, file_path: Optional[str] = None) -> None:
        """发送扫描器开始执行事件。
        
        Args:
            scanner_name: 扫描器名称（如 flake8, pylint）
            file_path: 正在扫描的文件路径
        """
        self.emit({
            "type": "scanner_progress",
            "status": "start",
            "scanner": scanner_name,
            "file": file_path,
            "timestamp": time.time()
        })

    def scanner_complete(
        self,
        scanner_name: str,
        duration_ms: float,
        issue_count: int,
        error_count: int = 0
    ) -> None:
        """发送扫描器执行完成事件。
        
        Args:
            scanner_name: 扫描器名称
            duration_ms: 执行耗时（毫秒）
            issue_count: 发现的问题总数
            error_count: 错误级别问题数
        """
        self.emit({
            "type": "scanner_progress",
            "status": "complete",
            "scanner": scanner_name,
            "duration_ms": duration_ms,
            "issue_count": issue_count,
            "error_count": error_count
        })

    def scanner_error(self, scanner_name: str, error: str) -> None:
        """发送扫描器执行错误事件。
        
        Args:
            scanner_name: 扫描器名称
            error: 错误信息
        """
        self.emit({
            "type": "scanner_progress",
            "status": "error",
            "scanner": scanner_name,
            "error": error
        })

    def scanner_issues_summary(
        self,
        total_issues: int,
        critical_issues: List[Dict[str, Any]],
        filtered_count: int,
        original_count: int
    ) -> None:
        """发送扫描器问题汇总事件。
        
        Args:
            total_issues: 总问题数
            critical_issues: 严重问题列表（已过滤）
            filtered_count: 过滤后的问题数
            original_count: 原始问题数
        """
        # 按严重程度统计
        by_severity = {
            "error": sum(1 for i in critical_issues if i.get("severity") == "error"),
            "warning": sum(1 for i in critical_issues if i.get("severity") == "warning"),
            "info": sum(1 for i in critical_issues if i.get("severity") == "info")
        }
        
        self.emit({
            "type": "scanner_issues_summary",
            "total_issues": total_issues,
            "critical_issues": critical_issues,
            "filtered_count": filtered_count,
            "original_count": original_count,
            "by_severity": by_severity
        })

    # =========================================================================
    # 扫描器初始化事件 (Requirements 1.1, 1.2, 4.3)
    # =========================================================================

    def scanner_init_start(self, language: str) -> None:
        """发送扫描器初始化开始事件。
        
        Args:
            language: 正在初始化扫描器的语言
        
        Requirements: 4.3
        """
        self.emit({
            "type": "scanner_init",
            "status": "start",
            "language": language,
            "timestamp": time.time()
        })

    def scanner_init_complete(
        self,
        language: str,
        duration_ms: float,
        scanner_count: int,
        scanners: List[str]
    ) -> None:
        """发送扫描器初始化完成事件。
        
        Args:
            language: 初始化完成的语言
            duration_ms: 初始化耗时（毫秒）
            scanner_count: 初始化的扫描器数量
            scanners: 扫描器名称列表
        
        Requirements: 4.3
        """
        self.emit({
            "type": "scanner_init",
            "status": "complete",
            "language": language,
            "duration_ms": duration_ms,
            "scanner_count": scanner_count,
            "scanners": scanners
        })
