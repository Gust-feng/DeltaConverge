#!/usr/bin/env python
"""DeltaConverge 新内核 CLI 入口。

用法:
    python review.py --help
    python review.py "请审查当前的代码变更"
    python review.py "审查HEAD~1..HEAD" --diff-mode commit --commit-from HEAD~1 --commit-to HEAD
    python review.py "审查" --diff-mode working --enable-scan
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="review",
        description="DeltaConverge 代码审查 CLI (新内核)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 审查工作区变更
  python review.py "请审查当前代码变更"

  # 审查指定提交范围
  python review.py "审查最近一次提交" --diff-mode commit --commit-from HEAD~1 --commit-to HEAD

  # 审查并启用静态扫描
  python review.py "全面审查" --enable-scan

  # 指定模型
  python review.py "审查" --model deepseek
""",
    )
    parser.add_argument("prompt", nargs="?", default="请对当前代码变更进行审查，输出高风险问题与修复建议。", help="审查提示词")
    parser.add_argument("--project-root", "-p", dest="project_root", default=str(PROJECT_ROOT), help="项目根目录")
    parser.add_argument("--model", "-m", default="auto", help="LLM 模型 (默认: auto)")
    parser.add_argument("--diff-mode", "-d", dest="diff_mode", default="working", choices=["working", "staged", "commit", "auto"], help="Diff 模式")
    parser.add_argument("--commit-from", dest="commit_from", help="起始提交 (commit 模式)")
    parser.add_argument("--commit-to", dest="commit_to", help="结束提交 (commit 模式)")
    parser.add_argument("--enable-scan", dest="enable_scan", action="store_true", help="启用静态扫描")
    parser.add_argument("--no-stream", dest="no_stream", action="store_true", help="禁用流式输出")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON 格式输出")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    return parser.parse_args()


async def run_review(args: argparse.Namespace) -> int:
    from kernel.bootstrap import get_kernel_facade
    from kernel.domain.models import ReviewCreateRequest

    facade = get_kernel_facade()

    request = ReviewCreateRequest(
        prompt=args.prompt,
        model=args.model,
        project_root=args.project_root,
        diff_mode=args.diff_mode,
        commit_from=args.commit_from,
        commit_to=args.commit_to,
        enable_static_scan=args.enable_scan,
        agents=["intent", "planner", "reviewer"],
    )

    if not args.no_stream and not args.json_output:
        print(f"🔍 正在审查: {args.project_root}")
        print(f"   模式: {args.diff_mode}", end="")
        if args.diff_mode == "commit":
            print(f" ({args.commit_from}..{args.commit_to})")
        else:
            print()
        print()

    result = await facade.create_review_run(request)
    run = result["run"]
    run_id = run.id

    if args.verbose:
        print(f"📋 Run ID: {run_id}")

    # 流式输出
    event_count = 0
    last_stage = None
    final_report = None

    async for event in facade.stream_review(run_id):
        event_count += 1

        if args.json_output:
            import json
            print(json.dumps({
                "seq": event.seq,
                "type": event.type,
                "stage": event.stage,
                "payload": event.payload,
            }, ensure_ascii=False))
            continue

        if not args.no_stream:
            # 显示阶段进度
            if event.type == "stage.started" and event.stage != last_stage:
                last_stage = event.stage
                stage_names = {
                    "diff_collection": "📁 采集变更",
                    "diff_snapshot": "💾 保存快照",
                    "planner": "📝 规划审查",
                    "fusion": "🔗 融合上下文",
                    "reviewer": "🔎 执行审查",
                    "context_provider": "📦 准备上下文",
                    "context_bundle": "📦 打包上下文",
                }
                name = stage_names.get(event.stage, f"⚙️ {event.stage}")
                print(f"\r{name}...", end="", flush=True)

            # 显示审查进度
            if event.type == "review.delta" and event.payload:
                content = event.payload.get("content")
                if content and isinstance(content, str):
                    # 流式输出内容片段
                    if last_stage == "reviewer":
                        print(f"\r{' ' * 40}\r", end="")  # 清除阶段提示
                        print(content, end="", flush=True)

        if event.type == "review.completed":
            break
        if event.type == "review.failed":
            error = event.payload.get("error") if event.payload else "Unknown error"
            print(f"\n❌ 审查失败: {error}")
            return 1

    # 获取最终报告
    run_final = facade.get_review_run(run_id)
    if run_final and run_final.final_report_artifact_id:
        detail = facade.get_session_detail(run_final.session_id)
        if detail:
            for artifact in detail.artifacts:
                if artifact.id == run_final.final_report_artifact_id:
                    final_report = facade.artifact_store.read_text(artifact)
                    break

    if not args.json_output:
        print()  # 换行
        print()
        if final_report:
            print("=" * 60)
            print("📄 审查报告")
            print("=" * 60)
            print(final_report)
        print()
        print(f"✅ 审查完成 (共 {event_count} 个事件)")

    return 0


def load_env_file(env_path: Path) -> None:
    """加载 .env 文件中的环境变量。"""
    if not env_path.exists():
        return
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("//") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    # 移除引号
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    os.environ[key] = value  # 强制覆盖
    except Exception:
        pass


def main() -> int:
    args = parse_args()

    # 加载环境变量（优先级：主项目 -> 当前项目）
    main_env = Path("z:/Agent代码审查/.env")
    project_env = Path(args.project_root) / ".env"
    load_env_file(main_env)
    load_env_file(project_env)

    try:
        return asyncio.run(run_review(args))
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        return 130
    except Exception as exc:
        print(f"\n❌ 错误: {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
