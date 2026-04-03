from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from kernel.domain.models import (
    ArtifactRef,
    MessageRecord,
    ReviewRun,
    ScanResult,
    SessionDetail,
    SessionSummary,
    WorkflowEvent,
)


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class FileArtifactStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_text(
        self,
        *,
        session_id: str,
        run_id: Optional[str],
        kind: str,
        content: str,
        extension: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef:
        artifact_id = uuid.uuid4().hex
        created_at = utc_now()
        run_segment = run_id or "session"
        rel_path = f"{session_id}/{run_segment}/{kind}-{artifact_id}.{extension.lstrip('.')}"
        target = self.base_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ArtifactRef(
            id=artifact_id,
            kind=kind,
            session_id=session_id,
            run_id=run_id,
            rel_path=rel_path.replace("\\", "/"),
            mime_type=mime_type,
            size_bytes=target.stat().st_size,
            created_at=created_at,
            metadata=dict(metadata or {}),
        )

    def save_json(
        self,
        *,
        session_id: str,
        run_id: Optional[str],
        kind: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef:
        return self.save_text(
            session_id=session_id,
            run_id=run_id,
            kind=kind,
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            extension="json",
            mime_type="application/json",
            metadata=metadata,
        )

    def read_text(self, artifact: ArtifactRef) -> str:
        return (self.base_dir / artifact.rel_path).read_text(encoding="utf-8")

    def read_json(self, artifact: ArtifactRef) -> Dict[str, Any]:
        return json.loads(self.read_text(artifact))


class SQLiteKernelStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        self._event_lock = threading.Lock()

    def _get_next_seq(self, conn: sqlite3.Connection, run_id: str) -> int:
        """获取下一个seq值。
        
        注意: 此方法必须在事务内调用,且调用方需持有_event_lock。
        """
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["next_seq"])

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    project_root TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    latest_run_id TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    enable_static_scan INTEGER NOT NULL,
                    diff_mode TEXT,
                    commit_from TEXT,
                    commit_to TEXT,
                    error_message TEXT,
                    final_report_artifact_id TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    stage TEXT,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    kind TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS scan_results (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    artifact_id TEXT,
                    created_at TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    issues_json TEXT NOT NULL,
                    linked_json TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY(artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
                );
                """
            )

    def _row_to_session_summary(self, row: sqlite3.Row) -> SessionSummary:
        return SessionSummary(
            id=row["id"],
            name=row["name"],
            project_root=row["project_root"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=json.loads(row["tags_json"] or "[]"),
            latest_run_id=row["latest_run_id"],
            last_error=row["last_error"],
        )

    def _row_to_run(self, row: sqlite3.Row) -> ReviewRun:
        return ReviewRun(
            id=row["id"],
            session_id=row["session_id"],
            prompt=row["prompt"],
            model=row["model"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            enable_static_scan=bool(row["enable_static_scan"]),
            diff_mode=row["diff_mode"],
            commit_from=row["commit_from"],
            commit_to=row["commit_to"],
            error_message=row["error_message"],
            final_report_artifact_id=row["final_report_artifact_id"],
        )

    def _row_to_message(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=row["id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _row_to_event(self, row: sqlite3.Row) -> WorkflowEvent:
        return WorkflowEvent(
            id=row["id"],
            run_id=row["run_id"],
            session_id=row["session_id"],
            seq=row["seq"],
            type=row["type"],
            stage=row["stage"],
            created_at=row["created_at"],
            payload=json.loads(row["payload_json"] or "{}"),
        )

    def _row_to_artifact(self, row: sqlite3.Row) -> ArtifactRef:
        return ArtifactRef(
            id=row["id"],
            kind=row["kind"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            rel_path=row["rel_path"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def create_session(
        self,
        *,
        session_id: str,
        name: Optional[str],
        project_root: Optional[str],
        tags: Optional[List[str]] = None,
        status: str = "active",
    ) -> SessionSummary:
        now = utc_now()
        summary = SessionSummary(
            id=session_id,
            name=name or session_id,
            project_root=project_root,
            status=status,
            created_at=now,
            updated_at=now,
            tags=list(tags or []),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, name, project_root, status, created_at, updated_at, tags_json, latest_run_id, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    summary.id,
                    summary.name,
                    summary.project_root,
                    summary.status,
                    summary.created_at,
                    summary.updated_at,
                    json.dumps(summary.tags, ensure_ascii=False),
                ),
            )
        return summary

    def ensure_session(
        self,
        *,
        session_id: str,
        name: Optional[str],
        project_root: Optional[str],
    ) -> SessionSummary:
        existing = self.get_session_summary(session_id)
        if existing:
            sets: List[str] = []
            params: List[Any] = []
            if name and existing.name != name:
                sets.append("name = ?")
                params.append(name)
            if project_root and existing.project_root != project_root:
                sets.append("project_root = ?")
                params.append(project_root)
            if sets:
                sets.append("updated_at = ?")
                params.append(utc_now())
                params.append(session_id)
                with self._connect() as conn:
                    conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)
                refreshed = self.get_session_summary(session_id)
                if refreshed:
                    return refreshed
            return existing
        return self.create_session(session_id=session_id, name=name, project_root=project_root)

    def get_session_summary(self, session_id: str) -> Optional[SessionSummary]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session_summary(row) if row else None

    def get_session_detail(self, session_id: str) -> Optional[SessionDetail]:
        summary = self.get_session_summary(session_id)
        if not summary:
            return None
        latest_run = self.get_run(summary.latest_run_id) if summary.latest_run_id else None
        artifacts = self.list_artifacts(session_id=session_id, run_id=None)
        return SessionDetail(
            summary=summary,
            latest_run=latest_run,
            artifacts=artifacts,
            latest_report_artifact_id=latest_run.final_report_artifact_id if latest_run else None,
        )

    def list_sessions(
        self,
        *,
        status: Optional[str] = None,
        project_root: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SessionSummary]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if project_root:
            clauses.append("project_root = ?")
            params.append(project_root)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([int(limit), int(offset)])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_session_summary(row) for row in rows]

    def update_session(
        self,
        session_id: str,
        *,
        name: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        last_error: Optional[str] = None,
        latest_run_id: Optional[str] = None,
    ) -> Optional[SessionSummary]:
        existing = self.get_session_summary(session_id)
        if not existing:
            return None
        sets = ["updated_at = ?"]
        params: List[Any] = [utc_now()]
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if tags is not None:
            sets.append("tags_json = ?")
            params.append(json.dumps(tags, ensure_ascii=False))
        if last_error is not None:
            sets.append("last_error = ?")
            params.append(last_error)
        if latest_run_id is not None:
            sets.append("latest_run_id = ?")
            params.append(latest_run_id)
        params.append(session_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)
        return self.get_session_summary(session_id)

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        model: str,
        enable_static_scan: bool,
        diff_mode: Optional[str],
        commit_from: Optional[str],
        commit_to: Optional[str],
    ) -> ReviewRun:
        now = utc_now()
        run = ReviewRun(
            id=run_id,
            session_id=session_id,
            prompt=prompt,
            model=model,
            status="created",
            created_at=now,
            updated_at=now,
            enable_static_scan=enable_static_scan,
            diff_mode=diff_mode,
            commit_from=commit_from,
            commit_to=commit_to,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, session_id, prompt, model, status, created_at, updated_at, enable_static_scan,
                    diff_mode, commit_from, commit_to, error_message, final_report_artifact_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    run.id,
                    run.session_id,
                    run.prompt,
                    run.model,
                    run.status,
                    run.created_at,
                    run.updated_at,
                    int(run.enable_static_scan),
                    run.diff_mode,
                    run.commit_from,
                    run.commit_to,
                ),
            )
        self.update_session(session_id, latest_run_id=run_id)
        return run

    def get_run(self, run_id: Optional[str]) -> Optional[ReviewRun]:
        if not run_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        final_report_artifact_id: Optional[str] = None,
    ) -> Optional[ReviewRun]:
        existing = self.get_run(run_id)
        if not existing:
            return None
        sets = ["updated_at = ?"]
        params: List[Any] = [utc_now()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        if final_report_artifact_id is not None:
            sets.append("final_report_artifact_id = ?")
            params.append(final_report_artifact_id)
        params.append(run_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params)
        return self.get_run(run_id)

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageRecord:
        created_at = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (session_id, run_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    run_id,
                    role,
                    content,
                    created_at,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        self.update_session(session_id)
        return MessageRecord(
            id=int(cursor.lastrowid),
            session_id=session_id,
            run_id=run_id,
            role=role,
            content=content,
            created_at=created_at,
            metadata=dict(metadata or {}),
        )

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, int(limit), int(offset)),
            ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def append_event(
        self,
        *,
        run_id: str,
        session_id: str,
        event_type: str,
        stage: Optional[str],
        payload: Dict[str, Any],
    ) -> WorkflowEvent:
        """追加事件到事件流。
        
        使用_event_lock保证并发安全。
        在极少数情况下(如唯一索引冲突),会自动重试最多3次。
        
        修复P0问题: seq生成并发不安全。
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self._event_lock:
                    created_at = utc_now()
                    with self._connect() as conn:
                        next_seq = self._get_next_seq(conn, run_id)
                        cursor = conn.execute(
                            """
                            INSERT INTO events (run_id, session_id, seq, type, stage, created_at, payload_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                run_id,
                                session_id,
                                next_seq,
                                event_type,
                                stage,
                                created_at,
                                json.dumps(payload, ensure_ascii=False),
                            ),
                        )
                    self.update_session(session_id)
                    return WorkflowEvent(
                        id=int(cursor.lastrowid),
                        run_id=run_id,
                        session_id=session_id,
                        seq=next_seq,
                        type=event_type,
                        created_at=created_at,
                        stage=stage,
                        payload=dict(payload),
                    )
            except sqlite3.IntegrityError as e:
                # 如果是seq冲突,重试
                if "idx_events_run_seq" in str(e) or "UNIQUE constraint failed" in str(e):
                    last_error = e
                    # 短暂等待后重试
                    import time
                    time.sleep(0.01 * (attempt + 1))  # 10ms, 20ms, 30ms
                    continue
                # 其他完整性错误直接抛出
                raise
        
        # 重试耗尽,抛出最后的错误
        raise RuntimeError(
            f"Failed to append event after {max_retries} retries due to seq conflict"
        ) from last_error

    def list_events(
        self,
        run_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[WorkflowEvent]:
        query = "SELECT * FROM events WHERE run_id = ? ORDER BY seq ASC"
        params: List[Any] = [run_id]
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def register_artifact(self, artifact: ArtifactRef) -> ArtifactRef:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    id, session_id, run_id, kind, rel_path, mime_type, size_bytes, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.id,
                    artifact.session_id,
                    artifact.run_id,
                    artifact.kind,
                    artifact.rel_path,
                    artifact.mime_type,
                    artifact.size_bytes,
                    artifact.created_at,
                    json.dumps(artifact.metadata, ensure_ascii=False),
                ),
            )
        self.update_session(artifact.session_id)
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRef]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts(
        self,
        *,
        session_id: str,
        run_id: Optional[str] = None,
    ) -> List[ArtifactRef]:
        query = "SELECT * FROM artifacts WHERE session_id = ?"
        params: List[Any] = [session_id]
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def upsert_scan_result(self, result: ScanResult) -> ScanResult:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_results (run_id, session_id, artifact_id, created_at, summary_json, issues_json, linked_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    artifact_id = excluded.artifact_id,
                    created_at = excluded.created_at,
                    summary_json = excluded.summary_json,
                    issues_json = excluded.issues_json,
                    linked_json = excluded.linked_json
                """,
                (
                    result.run_id,
                    result.session_id,
                    result.artifact_id,
                    result.created_at,
                    json.dumps(result.summary, ensure_ascii=False),
                    json.dumps(result.issues_by_severity, ensure_ascii=False),
                    json.dumps(result.linked, ensure_ascii=False),
                ),
            )
        return result

    def get_scan_result(self, run_id: str) -> Optional[ScanResult]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scan_results WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            return None
        return ScanResult(
            run_id=row["run_id"],
            session_id=row["session_id"],
            summary=json.loads(row["summary_json"] or "{}"),
            issues_by_severity=json.loads(row["issues_json"] or "{}"),
            linked=json.loads(row["linked_json"] or "{}"),
            created_at=row["created_at"],
            artifact_id=row["artifact_id"],
        )
