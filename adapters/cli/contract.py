from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(slots=True)
class CLIRunMode:
    name: str
    description: str


@dataclass(slots=True)
class CLICommandContract:
    command: str
    description: str
    facade_method: str
    positional_args: List[str] = field(default_factory=list)
    option_args: Dict[str, str] = field(default_factory=dict)
    stream: bool = False


DEFAULT_CLI_COMMANDS = [
    CLICommandContract(
        command="review",
        description="创建并启动一次代码审查运行",
        facade_method="create_review_run",
        option_args={
            "--project-root": "project_root",
            "--model": "model",
            "--diff-mode": "diff_mode",
            "--enable-static-scan": "enable_static_scan",
            "--session-id": "session_id",
        },
        stream=True,
    ),
    CLICommandContract(
        command="qa",
        description="基于已有审查运行进行问答",
        facade_method="ask_review_qa",
        positional_args=["run_id", "question"],
    ),
    CLICommandContract(
        command="sessions",
        description="列出会话摘要",
        facade_method="list_sessions",
    ),
    CLICommandContract(
        command="config_doctor",
        description="输出配置诊断信息",
        facade_method="get_config_doctor",
    ),
]
