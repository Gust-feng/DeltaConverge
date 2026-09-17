from __future__ import annotations

import inspect
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, List

from kernel.domain.models import QARequest, ReviewCreateRequest

from .contract import CLICommandContract, DEFAULT_CLI_COMMANDS


def serialize_cli_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: serialize_cli_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): serialize_cli_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_cli_value(item) for item in value]
    return value


class CLIAdapter:
    def __init__(self, facade: Any, commands: Iterable[CLICommandContract] = DEFAULT_CLI_COMMANDS) -> None:
        self.facade = facade
        self._commands = {command.command: command for command in commands}

    def list_commands(self) -> List[CLICommandContract]:
        return list(self._commands.values())

    async def execute(self, command: str, /, **kwargs: Any) -> Any:
        contract = self._commands.get(command)
        if not contract:
            raise KeyError(f"unknown command: {command}")

        if command == "review":
            request = ReviewCreateRequest(
                prompt=str(kwargs["prompt"]),
                model=str(kwargs.get("model") or "auto"),
                tools=list(kwargs.get("tools") or []),
                auto_approve=bool(kwargs.get("auto_approve", False)),
                project_root=kwargs.get("project_root"),
                session_id=kwargs.get("session_id"),
                session_name=kwargs.get("session_name"),
                agents=list(kwargs.get("agents") or []),
                enable_static_scan=bool(kwargs.get("enable_static_scan", False)),
                diff_mode=kwargs.get("diff_mode"),
                commit_from=kwargs.get("commit_from"),
                commit_to=kwargs.get("commit_to"),
                planner_model=kwargs.get("planner_model"),
            )
            result = await self.facade.create_review_run(request)
            if kwargs.get("stream"):
                run_id = self._extract_run_id(result)
                events = []
                event_callback = kwargs.get("event_callback")
                if run_id:
                    async for event in self.facade.stream_review(run_id):
                        if callable(event_callback):
                            event_callback(event)
                        events.append(event)
                return {"result": result, "events": events}
            return result

        if command == "qa":
            request = QARequest(
                run_id=str(kwargs["run_id"]),
                question=str(kwargs["question"]),
                model=str(kwargs.get("model") or "auto"),
                project_root=kwargs.get("project_root"),
            )
            return await self.facade.ask_review_qa(request)

        if command == "sessions":
            return self.facade.list_sessions(
                status=kwargs.get("status"),
                project_root=kwargs.get("project_root"),
                limit=int(kwargs.get("limit", 50)),
                offset=int(kwargs.get("offset", 0)),
            )

        method = getattr(self.facade, contract.facade_method)
        value = method(**kwargs)
        if inspect.isawaitable(value):
            return await value
        return value

    def to_output(self, value: Any) -> Any:
        return serialize_cli_value(value)

    def _extract_run_id(self, result: Any) -> str | None:
        if not isinstance(result, dict):
            return None
        run = result.get("run")
        if isinstance(run, dict):
            run_id = run.get("id")
            return str(run_id) if run_id else None
        run_id = getattr(run, "id", None)
        return str(run_id) if run_id else None
