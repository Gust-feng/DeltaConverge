from typing import Any, Dict, List

from Agent.tool.registry import builtin_tool_names, get_tool_schemas


def resolve_tools(tool_names: List[str], auto_approve: bool) -> Dict[str, Any]:
    schemas = get_tool_schemas(tool_names)
    builtin_whitelist = set(builtin_tool_names())
    auto_approve_list = tool_names if auto_approve else [n for n in tool_names if n in builtin_whitelist]
    return {"schemas": schemas, "auto_approve": auto_approve_list}

