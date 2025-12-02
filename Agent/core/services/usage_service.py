from typing import Any, Dict, Tuple


class UsageService:
    def __init__(self) -> None:
        self._call_usage: Dict[int, Dict[str, int]] = {}

    def reset(self) -> None:
        self._call_usage.clear()

    def update(self, usage: Dict[str, Any], call_index: int | None) -> Tuple[Dict[str, int], Dict[str, int]]:
        def _to_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        in_tok = _to_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
        out_tok = _to_int(usage.get("output_tokens") or usage.get("completion_tokens"))
        total_tok = _to_int(usage.get("total_tokens"))
        try:
            idx = int(call_index) if call_index is not None else 1
        except (TypeError, ValueError):
            idx = 1
        current = self._call_usage.get(idx, {"in": 0, "out": 0, "total": 0})
        current["in"] = max(current["in"], in_tok)
        current["out"] = max(current["out"], out_tok)
        current["total"] = max(current["total"], total_tok)
        self._call_usage[idx] = current

        session_totals = {
            "in": sum(v["in"] for v in self._call_usage.values()),
            "out": sum(v["out"] for v in self._call_usage.values()),
            "total": sum(v["total"] for v in self._call_usage.values()),
        }
        return current, session_totals

    def session_totals(self) -> Dict[str, int]:
        return {
            "in": sum(v["in"] for v in self._call_usage.values()),
            "out": sum(v["out"] for v in self._call_usage.values()),
            "total": sum(v["total"] for v in self._call_usage.values()),
        }

