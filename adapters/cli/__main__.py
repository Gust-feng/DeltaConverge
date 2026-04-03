from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from kernel.bootstrap import get_kernel_facade

from .runner import CLIAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deltaconverge", description="DeltaConverge minimal CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Create and stream a review run")
    review.add_argument("--prompt", required=True, help="Review prompt")
    review.add_argument("--project-root", dest="project_root", required=True, help="Project root to review")
    review.add_argument("--session-id", dest="session_id")
    review.add_argument("--session-name", dest="session_name")
    review.add_argument("--model", default="auto")
    review.add_argument("--planner-model", dest="planner_model")
    review.add_argument("--diff-mode", dest="diff_mode", default="working")
    review.add_argument("--commit-from", dest="commit_from")
    review.add_argument("--commit-to", dest="commit_to")
    review.add_argument("--tool", dest="tools", action="append", default=[])
    review.add_argument("--agent", dest="agents", action="append", default=[])
    review.add_argument("--enable-static-scan", dest="enable_static_scan", action="store_true")
    review.add_argument("--auto-approve", dest="auto_approve", action="store_true")
    review.add_argument("--no-stream", dest="stream", action="store_false")
    review.set_defaults(stream=True)

    qa = subparsers.add_parser("qa", help="Ask a question about an existing review run")
    qa.add_argument("run_id")
    qa.add_argument("question")
    qa.add_argument("--model", default="auto")
    qa.add_argument("--project-root", dest="project_root")

    sessions = subparsers.add_parser("sessions", help="List session summaries")
    sessions.add_argument("--status")
    sessions.add_argument("--project-root", dest="project_root")
    sessions.add_argument("--limit", type=int, default=50)
    sessions.add_argument("--offset", type=int, default=0)

    return parser


async def run_cli(args: argparse.Namespace) -> int:
    facade = get_kernel_facade()
    adapter = CLIAdapter(facade)

    if args.command == "review":
        def emit_event(event: Any) -> None:
            print(json.dumps({"kind": "event", "event": adapter.to_output(event)}, ensure_ascii=False), flush=True)

        result = await adapter.execute(
            "review",
            prompt=args.prompt,
            model=args.model,
            tools=args.tools,
            auto_approve=args.auto_approve,
            project_root=args.project_root,
            session_id=args.session_id,
            session_name=args.session_name,
            agents=args.agents,
            enable_static_scan=args.enable_static_scan,
            diff_mode=args.diff_mode,
            commit_from=args.commit_from,
            commit_to=args.commit_to,
            planner_model=args.planner_model,
            stream=args.stream,
            event_callback=emit_event if args.stream else None,
        )
        print(json.dumps({"kind": "result", "result": adapter.to_output(result)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "qa":
        result = await adapter.execute(
            "qa",
            run_id=args.run_id,
            question=args.question,
            model=args.model,
            project_root=args.project_root,
        )
        print(json.dumps(adapter.to_output(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "sessions":
        result = await adapter.execute(
            "sessions",
            status=args.status,
            project_root=args.project_root,
            limit=args.limit,
            offset=args.offset,
        )
        print(json.dumps(adapter.to_output(result), ensure_ascii=False, indent=2))
        return 0

    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"kind": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
