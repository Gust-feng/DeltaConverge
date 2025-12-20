from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path

from Agent.core.state.conversation import ConversationState

logger = logging.getLogger(__name__)


class SessionError(Exception):
    """会话操作异常基类。"""
    pass


class SessionNotFoundError(SessionError):
    """会话未找到异常。"""
    pass


class SessionOperationError(SessionError):
    """会话操作失败异常。"""
    pass


@dataclass
class SessionMetadata:
    created_at: str
    updated_at: str
    name: str | None = None
    project_root: str | None = None
    status: str = "active"  # active, completed, archived
    tags: List[str] = field(default_factory=list)


class ReviewSession:
    """代表一次持久化的审查会话。"""

    def __init__(
        self,
        session_id: str,
        project_root: str | None = None,
        metadata: SessionMetadata | None = None
    ) -> None:
        self.session_id = session_id
        self.conversation = ConversationState()
        self.workflow_events: List[Dict[str, Any]] = []  # 保存工作流事件
        self.diff_files: List[Dict[str, Any]] = []  # 保存变更文件快照
        self.diff_units: List[Dict[str, Any]] = []
        self.static_scan_linked: Dict[str, Any] = {}
        
        now = datetime.now().isoformat()
        self.metadata = metadata or SessionMetadata(
            created_at=now,
            updated_at=now,
            name=session_id,
            project_root=project_root
        )

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """通用消息添加接口，自动更新元数据。"""
        if role == "user":
            self.conversation.add_user_message(content)
        elif role == "system":
            self.conversation.add_system_message(content)
        elif role == "assistant":
            self.conversation.add_assistant_message(content, tool_calls=kwargs.get("tool_calls", []), reasoning=kwargs.get("reasoning"))
        elif role == "tool":
            self.conversation.add_tool_result({
                "tool_call_id": kwargs.get("tool_call_id"),
                "name": kwargs.get("name"),
                "content": content,
                "error": kwargs.get("error")
            })
        
        self.metadata.updated_at = datetime.now().isoformat()

    def add_workflow_event(self, event: Dict[str, Any]) -> None:
        """添加工作流事件（思考、工具调用等）。
        
        优化：合并连续的同类型 thought/chunk 事件以减少存储体积。
        """
        evt_type = event.get("type")
        evt_stage = event.get("stage")
        evt_content = event.get("content")
        
        # 对于 thought 和 chunk 类型，尝试合并到上一个同类型事件
        if evt_type in ("thought", "chunk") and evt_content and self.workflow_events:
            last_evt = self.workflow_events[-1]
            if (
                last_evt.get("type") == evt_type and
                last_evt.get("stage") == evt_stage and
                "content" in last_evt
            ):
                old_content = str(last_evt.get("content") or "")
                new_part = str(evt_content or "")
                last_evt["content"] = old_content + new_part
                last_evt["timestamp"] = datetime.now().isoformat()
                return
        
        # 无法合并，添加为新事件
        event_with_time = {
            **event,
            "timestamp": datetime.now().isoformat()
        }
        self.workflow_events.append(event_with_time)

    def to_dict(self) -> Dict[str, Any]:
        """序列化会话数据。"""
        return {
            "session_id": self.session_id,
            "metadata": asdict(self.metadata),
            "messages": self.conversation.messages,
            "workflow_events": self.workflow_events,
            "diff_files": self.diff_files,
            "diff_units": self.diff_units,
            "static_scan_linked": self.static_scan_linked,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReviewSession:
        """反序列化会话数据。"""
        meta_data = data.get("metadata", {})
        metadata = SessionMetadata(**meta_data)
        
        session = cls(
            session_id=data["session_id"],
            metadata=metadata
        )
        
        # 使用专用的恢复方法恢复消息历史
        # 这样可以保持消息格式的一致性，不会因为重新添加而改变格式
        messages = data.get("messages", [])
        session.conversation.restore_messages(messages)
        
        # 恢复工作流事件
        session.workflow_events = data.get("workflow_events", [])
        
        # 恢复变更文件快照
        session.diff_files = data.get("diff_files", [])

        # 恢复变更单元快照
        session.diff_units = data.get("diff_units", [])

        # 恢复静态扫描关联
        session.static_scan_linked = data.get("static_scan_linked", {})
                
        return session


class SessionManager:
    """会话生命周期管理与持久化。"""

    def __init__(self, storage_dir: str | None = None) -> None:
        agent_root = Path(__file__).resolve().parents[2]
        if storage_dir is None:
            self.storage_dir = (agent_root / "data" / "sessions").resolve()
        else:
            p = Path(storage_dir)
            self.storage_dir = (p if p.is_absolute() else (agent_root / p)).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, ReviewSession] = {}
        self._lock = threading.RLock()

    def create_session(self, session_id: str, project_root: str | None = None) -> ReviewSession:
        with self._lock:
            session = ReviewSession(session_id, project_root)
            self._sessions[session_id] = session
            self.save_session(session)
            return session

    def get_session(self, session_id: str) -> ReviewSession | None:
        """获取会话（带锁保护）。"""
        with self._lock:
            return self._get_session_no_lock(session_id)
    
    def _get_session_no_lock(self, session_id: str) -> ReviewSession | None:
        """获取会话（不带锁保护，仅供内部调用）。"""
        if session_id in self._sessions:
            return self._sessions[session_id]
        
        # 尝试从磁盘加载
        path = self.storage_dir / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session = ReviewSession.from_dict(data)
                self._sessions[session_id] = session
                return session
            except Exception as e:
                logger.error(f"Failed to load session {session_id}: {e}")
                return None
        return None

    def save_session(self, session: ReviewSession) -> None:
        with self._lock:
            try:
                # 创建存储目录（如果不存在）
                self.storage_dir.mkdir(parents=True, exist_ok=True)
                
                path = self.storage_dir / f"{session.session_id}.json"
                
                # 创建会话目录（如果不存在）
                path.parent.mkdir(parents=True, exist_ok=True)
                
                # 保存会话数据
                path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                # 统一异常处理，确保所有操作都被尝试
                logger.error(f"Failed to save session {session.session_id}: {e}")
                
                # 尝试使用临时目录作为备选方案
                try:
                    import tempfile
                    temp_dir = tempfile.gettempdir()
                    temp_path = Path(temp_dir) / f"session_{session.session_id}.json"
                    temp_path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.warning(f"Session {session.session_id} saved to temporary directory: {temp_path.name}")
                except Exception as temp_err:
                    logger.error(f"Failed to save session {session.session_id} to temporary directory: {temp_err}")

    def delete_session(self, session_id: str) -> None:
        """删除会话。"""
        with self._lock:
            # 删除内存中的会话
            if session_id in self._sessions:
                del self._sessions[session_id]
            
            # 删除磁盘上的会话文件
            path = self.storage_dir / f"{session_id}.json"
            if path.exists():
                try:
                    path.unlink()
                except Exception as first_err:
                    # Retry logic with a small delay
                    import time
                    time.sleep(0.2)
                    try:
                        path.unlink()
                    except Exception:
                        # Fallback: Try to rename if delete fails (e.g. file locking issues)
                        try:
                            trash_path = path.with_name(f"{path.name}.deleted_{int(time.time())}")
                            path.rename(trash_path)
                            logger.warning(f"Renamed session file {path.name} to {trash_path.name} due to deletion error")
                        except Exception as final_err:
                            logger.error(f"Failed to delete or rename session file {path.name}: {final_err}")
                            # 包装错误信息，避免泄露内部错误细节
                            raise SessionOperationError(f"Failed to delete session {session_id}") from first_err

    def rename_session(self, session_id: str, new_name: str) -> ReviewSession | None:
        """重命名会话。"""
        with self._lock:
            session = self._get_session_no_lock(session_id)
            if session:
                session.metadata.name = new_name
                session.metadata.updated_at = datetime.now().isoformat()
                self.save_session(session)
            return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话摘要。"""
        with self._lock:
            sessions = []
            # 遍历内存和磁盘
            # 为简单起见，这里只遍历磁盘
            for path in self.storage_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    meta = data.get("metadata", {})
                    sessions.append({
                        "session_id": data["session_id"],
                        "name": meta.get("name", data["session_id"]),
                        "created_at": meta.get("created_at"),
                        "updated_at": meta.get("updated_at"),
                        "project_root": meta.get("project_root"),
                        "status": meta.get("status")
                    })
                except Exception as e:
                    logger.error(f"Failed to read session file {path}: {e}")
                    continue
            return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)
