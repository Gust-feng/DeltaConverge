"""Diff 采集 Stage。

负责：
1. 设置项目根目录和会话上下文变量
2. 根据 diff_mode 采集 DiffContext
3. 保存 diff 快照制品
4. 启动旁路静态扫描（如果启用）
5. 设置规则层事件回调
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter
from kernel.ports.stores import ArtifactStore, SessionStore, ScanServicePort
from kernel.ports.git import GitPort, DiffMode as PortDiffMode
from kernel.ports.diff import DiffPort

from ..emitter import sanitize_payload


class DiffStage:
    """Diff 采集与环境初始化。"""

    def __init__(
        self,
        *,
        store: SessionStore,
        artifact_store: ArtifactStore,
        git_port: GitPort | None = None,
        diff_port: DiffPort | None = None,
        scan_service: ScanServicePort | None = None,
    ) -> None:
        if git_port is None:
            from kernel.infrastructure import LegacyGitAdapter
            git_port = LegacyGitAdapter()
        if diff_port is None:
            from kernel.infrastructure import LegacyDiffAdapter
            diff_port = LegacyDiffAdapter(git_adapter=git_port)
        self.store = store
        self.artifact_store = artifact_store
        self.git_port = git_port
        self.diff_port = diff_port
        self.scan_service = scan_service

    @property
    def name(self) -> str:
        return "diff_collection"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        from Agent.core.context.runtime_context import set_project_root, set_session_id
        from Agent.DIFF.rule.context_decision import set_rule_event_callback

        # 1. 设置全局上下文（保留以兼容旧工具）
        set_project_root(ctx.project_root)
        set_session_id(ctx.session_id)

        # 2. 设置规则层事件回调
        def _rule_callback(event: Dict[str, Any]) -> None:
            payload = {k: sanitize_payload(v) for k, v in event.items() if k != "type"}
            emit.delta("rule", legacy_type=str(event.get("type") or ""), **payload)

        set_rule_event_callback(_rule_callback)

        # 3. 采集 Diff（使用 Port 接口）
        request = ctx.request
        if request.diff_mode == "commit":
            # 使用 GitPort 获取 diff 文本
            diff_text = self.git_port.get_diff_text(
                mode=PortDiffMode.COMMIT,
                cwd=ctx.project_root,
                base_ref=request.commit_from,
                head_ref=request.commit_to,
            )
            # 使用 DiffPort 构建上下文
            ctx.diff_ctx = self.diff_port.build_diff_context(
                diff_text,
                project_root=ctx.project_root,
            )
        else:
            # 使用 DiffPort 直接采集
            mode_map = {
                "working": PortDiffMode.WORKING,
                "staged": PortDiffMode.STAGED,
                "unstaged": PortDiffMode.UNSTAGED,
                "pr": PortDiffMode.BRANCH,
                "auto": PortDiffMode.WORKING,
            }
            mode = mode_map.get(request.diff_mode, PortDiffMode.WORKING)
            ctx.diff_ctx = self.diff_port.collect_diff_context(
                mode=mode,
                project_root=ctx.project_root,
            )

        # 4. 保存 diff 快照制品
        self._save_diff_snapshot(ctx, emit)

        # 5. 启动旁路静态扫描
        if request.enable_static_scan:
            self._start_static_scan(ctx, emit)

    # ------------------------------------------------------------------

    def _save_diff_snapshot(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        diff_ctx = ctx.diff_ctx
        review_files = diff_ctx.review_index.get("files", []) if diff_ctx.review_index else []

        diff_files_snapshot: List[Dict[str, Any]] = []
        if isinstance(review_files, list) and review_files:
            for f in review_files:
                p = f.get("path", "") if isinstance(f, dict) else ""
                if p:
                    diff_files_snapshot.append({
                        "path": p,
                        "display_path": p,
                        "change_type": (f.get("change_type") if isinstance(f, dict) else None) or "modify",
                    })
        if not diff_files_snapshot:
            for fp in diff_ctx.files or []:
                diff_files_snapshot.append({"path": str(fp), "display_path": str(fp), "change_type": "modify"})

        diff_units_snapshot: List[Dict[str, Any]] = []
        for u in diff_ctx.units or []:
            if not isinstance(u, dict):
                continue
            diff_units_snapshot.append({
                "unit_id": u.get("unit_id") or u.get("id"),
                "file_path": u.get("file_path"),
                "change_type": u.get("change_type") or u.get("patch_type"),
                "hunk_range": u.get("hunk_range") or {},
                "unified_diff": u.get("unified_diff") or "",
                "unified_diff_with_lines": u.get("unified_diff_with_lines"),
                "tags": u.get("tags") or [],
                "rule_context_level": u.get("rule_context_level"),
                "rule_confidence": u.get("rule_confidence"),
            })

        artifact = self.artifact_store.save_json(
            session_id=ctx.session_id,
            run_id=ctx.run.id,
            kind="review_diff_snapshot",
            payload={"diff_files": diff_files_snapshot, "diff_units": diff_units_snapshot},
            metadata={"source": "diff_stage"},
        )
        self.store.register_artifact(artifact)
        emit.stage_finished(
            "diff_snapshot",
            artifact_id=artifact.id,
            unit_count=len(diff_units_snapshot),
        )

    def _start_static_scan(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        from Agent.DIFF.static_scan_service import run_static_scan, get_unique_files_from_diff_context

        files_to_scan = get_unique_files_from_diff_context(ctx.diff_ctx)
        if not files_to_scan:
            return

        def _scan_callback(event: Dict[str, Any]) -> None:
            event_type = str(event.get("type") or "")
            payload = {k: sanitize_payload(v) for k, v in event.items() if k != "type"}

            if event_type == "static_scan_start":
                ctx.scan_started = True
                emit.scan_event("scan.started", **payload)
            elif event_type == "static_scan_complete":
                ctx.scan_complete = True
                if ctx.scan_done_event:
                    ctx.scan_done_event.set()
                self._persist_scan_result(ctx)
                emit.scan_event("scan.finished", **payload)
            else:
                emit.scan_event("scan.progress", legacy_type=event_type, **payload)

        ctx.scan_done_event = asyncio.Event()
        ctx.static_scan_task = asyncio.create_task(
            run_static_scan(
                files=files_to_scan,
                units=ctx.diff_ctx.units,
                callback=_scan_callback,
                project_root=ctx.project_root,
                session_id=ctx.session_id,
            )
        )

    def _persist_scan_result(self, ctx: PipelineContext) -> None:
        from kernel.infrastructure.scan import (
            build_scan_artifact_payload,
            build_scan_result,
            read_legacy_scan_cache,
        )
        from kernel.infrastructure.persistence import utc_now

        snapshot = read_legacy_scan_cache(ctx.session_id, scan_service=self.scan_service)
        if not snapshot.has_data:
            return

        artifact = self.artifact_store.save_json(
            session_id=ctx.session_id,
            run_id=ctx.run.id,
            kind="scan_result",
            payload=build_scan_artifact_payload(snapshot),
            metadata={"source": "static_scan_cache"},
        )
        self.store.register_artifact(artifact)
        self.store.upsert_scan_result(
            build_scan_result(
                ctx.run.id, ctx.session_id, snapshot,
                created_at=utc_now(), artifact_id=artifact.id,
            )
        )
