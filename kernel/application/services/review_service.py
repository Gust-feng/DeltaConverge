"""审查服务模块。"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from kernel.domain.models import QARequest, QAResponse, ReviewCreateRequest, WorkflowEvent, SessionDetail
from kernel.ports.stores import ArtifactStore, SessionStore
from ..event_bus import RunEventBus
from ..review_orchestrator import ReviewOrchestrator


class ReviewService:
    def __init__(
        self,
        store: SessionStore,
        artifact_store: ArtifactStore,
        event_bus: RunEventBus,
        orchestrator: ReviewOrchestrator,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        self.event_bus = event_bus
        self.orchestrator = orchestrator

    async def create_review_run(self, request: ReviewCreateRequest) -> Dict[str, object]:
        session_id = request.session_id or f"sess_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        session = self.store.ensure_session(
            session_id=session_id,
            name=request.session_name,
            project_root=request.project_root,
        )
        run = self.store.create_run(
            run_id=f"run_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
            session_id=session.id,
            prompt=request.prompt,
            model=request.model,
            enable_static_scan=request.enable_static_scan,
            diff_mode=request.diff_mode,
            commit_from=request.commit_from,
            commit_to=request.commit_to,
        )
        await self.orchestrator.start_review(request, run)
        detail = self.store.get_session_detail(session.id)
        return {"session": detail or session, "run": self.store.get_run(run.id) or run}

    async def stream_review(self, run_id: str) -> AsyncIterator[WorkflowEvent]:
        queue = self.event_bus.subscribe(run_id)
        try:
            last_seq = 0
            buffer: Dict[int, WorkflowEvent] = {}

            for event in self.store.list_events(run_id):
                yield event
                last_seq = max(last_seq, event.seq)

            if self.event_bus.is_closed(run_id):
                return

            while True:
                event = await queue.get()
                if event is None:
                    for seq in sorted(buffer.keys()):
                        if seq > last_seq:
                            yield buffer[seq]
                            last_seq = seq
                    break
                if event.seq <= last_seq:
                    continue
                if event.seq == last_seq + 1:
                    last_seq = event.seq
                    yield event
                    while (last_seq + 1) in buffer:
                        last_seq += 1
                        yield buffer.pop(last_seq)
                else:
                    buffer[event.seq] = event
        finally:
            self.event_bus.unsubscribe(run_id, queue)

    async def ask_review_qa(self, request: QARequest) -> QAResponse:
        from Agent.agents.code_reviewer import CodeReviewAgent
        from Agent.core.adapter.llm_adapter import OpenAIAdapter
        from Agent.core.api.factory import LLMFactory
        from Agent.core.state.conversation import ConversationState
        from Agent.core.stream.stream_processor import StreamProcessor
        from Agent.core.tools.runtime import ToolRuntime

        run = self.store.get_run(request.run_id)
        if not run:
            raise KeyError(f"review run not found: {request.run_id}")
        detail = self.store.get_session_detail(run.session_id)
        if not detail:
            raise KeyError(f"session not found: {run.session_id}")
        if not run.final_report_artifact_id:
            raise RuntimeError("review report is not ready")

        report_artifact = self.store.get_artifact(run.final_report_artifact_id)
        if report_artifact is None:
            raise RuntimeError("review report artifact is missing")

        report_text = self.artifact_store.read_text(report_artifact)
        project_tree = self._load_artifact_payload(detail, "project_tree")
        diff_snapshot = self._get_review_diff(run.id)
        scan_result = self.store.get_scan_result(run.id)

        llm_client, provider = LLMFactory.create(request.model)
        try:
            adapter = OpenAIAdapter(llm_client, StreamProcessor(), provider_name=provider)
            runtime = ToolRuntime()
            state = ConversationState()
            prompt = self._build_qa_system_prompt(report_text, diff_snapshot, scan_result)
            state.add_system_message(prompt)
            agent = CodeReviewAgent(
                adapter, runtime, state=state,
                file_tree=project_tree.get("tree") if isinstance(project_tree, dict) else None
            )
            answer = await agent.run(request.question, files=list(self._diff_files(diff_snapshot)))
        finally:
            await llm_client.aclose()

        self.store.add_message(
            session_id=run.session_id,
            run_id=run.id,
            role="user",
            content=request.question,
            metadata={"channel": "qa"},
        )
        message = self.store.add_message(
            session_id=run.session_id,
            run_id=run.id,
            role="assistant",
            content=answer,
            metadata={"channel": "qa"},
        )
        return QAResponse(run_id=run.id, session_id=run.session_id, answer=answer, message=message)

    def _get_review_diff(self, run_id: str) -> Dict[str, object]:
        run = self.store.get_run(run_id)
        if not run:
            return {}
        artifacts = self.store.list_artifacts(session_id=run.session_id, run_id=run.id)
        for artifact in artifacts:
            if artifact.kind == "review_diff_snapshot":
                return self.artifact_store.read_json(artifact)
        return {}

    def _load_artifact_payload(self, detail: SessionDetail, kind: str) -> Dict[str, object]:
        for artifact in detail.artifacts:
            if artifact.kind == kind:
                return self.artifact_store.read_json(artifact)
        return {}

    def _diff_files(self, diff_snapshot: Dict[str, object]) -> List[str]:
        files = []
        for item in diff_snapshot.get("diff_files", []) or []:
            if isinstance(item, dict):
                path = item.get("path") or item.get("display_path")
                if path:
                    files.append(str(path))
        return files

    def _build_qa_system_prompt(self, report_text: str, diff_snapshot: Dict[str, object], scan_result: Any) -> str:
        scan_summary = scan_result.summary if scan_result else {}
        return (
            "你是 DeltaConverge 的审查问答内核。请基于已有审查报告回答问题，"
            "优先引用报告结论、变更文件和扫描结果，不要重新做一次完整审查。\n\n"
            "## 审查报告\n"
            f"{report_text}\n\n"
            "## Diff 快照\n"
            f"{json.dumps(diff_snapshot, ensure_ascii=False, indent=2)[:12000]}\n\n"
            "## 扫描摘要\n"
            f"{json.dumps(scan_summary, ensure_ascii=False, indent=2)}"
        )
