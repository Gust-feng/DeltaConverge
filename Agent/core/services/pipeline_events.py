from typing import Any, Callable, Dict


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

