from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from kernel.domain.models import LegacyImportResult
from kernel.infrastructure.persistence import FileArtifactStore, SQLiteKernelStore


class LegacySessionImporter:
    def __init__(self, store: SQLiteKernelStore, artifact_store: FileArtifactStore) -> None:
        self.store = store
        self.artifact_store = artifact_store

    def import_file(self, path: Path) -> LegacyImportResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        session_id = str(data.get("session_id") or f"legacy-{path.stem}")
        metadata = data.get("metadata") or {}

        session = self.store.ensure_session(
            session_id=session_id,
            name=metadata.get("name") or f"legacy-{session_id}",
            project_root=metadata.get("project_root"),
        )
        self.store.update_session(
            session.id,
            status=str(metadata.get("status") or "completed"),
            tags=list(metadata.get("tags") or ["legacy"]),
        )

        run = self.store.create_run(
            run_id=f"legacy-run-{session_id}",
            session_id=session.id,
            prompt=str(data.get("prompt") or "Legacy imported review run"),
            model=str(metadata.get("model") or "legacy"),
            enable_static_scan=False,
            diff_mode=(data.get("diff_options") or {}).get("diff_mode"),
            commit_from=(data.get("diff_options") or {}).get("commit_from"),
            commit_to=(data.get("diff_options") or {}).get("commit_to"),
        )

        imported_messages = 0
        for message in data.get("messages") or []:
            self.store.add_message(
                session_id=session.id,
                run_id=run.id,
                role=str(message.get("role") or "assistant"),
                content=str(message.get("content") or ""),
                metadata={"channel": "legacy"},
            )
            imported_messages += 1

        imported_events = 0
        for event in data.get("workflow_events") or []:
            mapped_type, stage, payload = self._map_legacy_event(event)
            self.store.append_event(
                run_id=run.id,
                session_id=session.id,
                event_type=mapped_type,
                stage=stage,
                payload=payload,
            )
            imported_events += 1

        imported_artifacts = 0

        diff_payload = {
            "diff_files": data.get("diff_files") or [],
            "diff_units": data.get("diff_units") or [],
        }
        if diff_payload["diff_files"] or diff_payload["diff_units"]:
            artifact = self.artifact_store.save_json(
                session_id=session.id,
                run_id=run.id,
                kind="review_diff_snapshot",
                payload=diff_payload,
                metadata={"source": "legacy_import"},
            )
            self.store.register_artifact(artifact)
            imported_artifacts += 1

        project_tree = data.get("project_file_tree")
        if project_tree:
            artifact = self.artifact_store.save_json(
                session_id=session.id,
                run_id=run.id,
                kind="project_tree",
                payload={"tree": project_tree},
                metadata={"source": "legacy_import"},
            )
            self.store.register_artifact(artifact)
            imported_artifacts += 1

        report_content = self._extract_report(data)
        if report_content:
            artifact = self.artifact_store.save_text(
                session_id=session.id,
                run_id=run.id,
                kind="final_report",
                content=report_content,
                extension="md",
                mime_type="text/markdown",
                metadata={"source": "legacy_import"},
            )
            self.store.register_artifact(artifact)
            self.store.update_run(run.id, status="completed", final_report_artifact_id=artifact.id)
            imported_artifacts += 1

        details = self.store.get_session_detail(session.id)
        if details is None:
            raise RuntimeError(f"legacy import failed for session {session.id}")

        return LegacyImportResult(
            session=details.summary,
            run=details.latest_run,
            imported_messages=imported_messages,
            imported_events=imported_events,
            imported_artifacts=imported_artifacts,
        )

    def _extract_report(self, data: Dict[str, Any]) -> Optional[str]:
        for message in reversed(data.get("messages") or []):
            if str(message.get("role") or "").strip() == "assistant":
                content = str(message.get("content") or "").strip()
                if content:
                    return content
        return None

    def _map_legacy_event(self, event: Dict[str, object]) -> tuple[str, Optional[str], Dict[str, object]]:
        event_type = str(event.get("type") or "legacy_event")
        stage = str(event.get("stage")) if event.get("stage") is not None else None
        payload = {str(key): value for key, value in event.items() if key not in {"type", "stage", "timestamp"}}

        if event_type == "pipeline_stage_start":
            return "stage.started", stage, payload
        if event_type == "pipeline_stage_end":
            return "stage.finished", stage, payload
        if event_type.startswith("static_scan") or event_type.startswith("scanner"):
            return "scan.progress", "scan", {"legacy_type": event_type, **payload}
        return "review.delta", stage, {"legacy_type": event_type, **payload}
