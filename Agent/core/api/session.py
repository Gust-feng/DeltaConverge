"""会话管理增强API模块。

对现有会话管理进行封装和扩展，提供更丰富的会话操作。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from Agent.core.state.session import SessionManager, ReviewSession


# 全局会话管理器
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取会话管理器单例。"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


class SessionAPI:
    """会话管理增强API（静态方法接口）。"""
    
    @staticmethod
    def create_session(
        session_id: str,
        project_root: Optional[str] = None,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """创建新会话。
        
        Args:
            session_id: 会话ID（需唯一）
            project_root: 关联的项目根目录
            name: 会话名称
            tags: 标签列表
            
        Returns:
            Dict: 创建的会话信息
        """
        manager = get_session_manager()
        
        # 检查是否已存在
        existing = manager.get_session(session_id)
        if existing:
            return {
                "success": False,
                "error": f"Session '{session_id}' already exists",
            }
        
        session = manager.create_session(session_id, project_root)
        
        if name:
            session.metadata.name = name
        if tags:
            session.metadata.tags = tags
        
        manager.save_session(session)
        
        return {
            "success": True,
            "session": session.to_dict(),
        }
    
    @staticmethod
    def get_session(session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话详情。
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: 会话详情，不存在返回None
        """
        session = get_session_manager().get_session(session_id)
        if session:
            return session.to_dict()
        return None
    
    @staticmethod
    def list_sessions(
        status: Optional[str] = None,
        project_root: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """列出会话（支持过滤）。
        
        Args:
            status: 按状态过滤 ("active", "completed", "archived")
            project_root: 按项目过滤
            tag: 按标签过滤
            limit: 返回条数
            offset: 偏移量
            
        Returns:
            Dict: {"sessions": List[{...}], "total": int}
        """
        all_sessions = get_session_manager().list_sessions()
        
        # 应用过滤
        filtered = []
        for s in all_sessions:
            if status and s.get("status") != status:
                continue
            if project_root and s.get("project_root") != project_root:
                continue
            # tag过滤需要读取完整会话数据
            if tag:
                full_session = get_session_manager().get_session(s["session_id"])
                if full_session and tag not in (full_session.metadata.tags or []):
                    continue
            filtered.append(s)
        
        total = len(filtered)
        paginated = filtered[offset:offset + limit]
        
        return {
            "sessions": paginated,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    
    @staticmethod
    def update_session(
        session_id: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """更新会话元数据。
        
        Args:
            session_id: 会话ID
            name: 新名称
            status: 新状态
            tags: 新标签
            
        Returns:
            Dict: {"success": bool, "session": {...}}
        """
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return {
                "success": False,
                "error": f"Session '{session_id}' not found",
            }
        
        if name is not None:
            session.metadata.name = name
        if status is not None:
            session.metadata.status = status
        if tags is not None:
            session.metadata.tags = tags
        
        session.metadata.updated_at = datetime.now().isoformat()
        manager.save_session(session)
        
        return {
            "success": True,
            "session": session.to_dict(),
        }
    
    @staticmethod
    def delete_session(session_id: str) -> Dict[str, Any]:
        """删除会话。
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: {"success": bool}
        """
        try:
            get_session_manager().delete_session(session_id)
            return {"success": True}
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    @staticmethod
    def export_session(session_id: str, format: str = "json") -> Dict[str, Any]:
        """导出会话数据。
        
        Args:
            session_id: 会话ID
            format: 导出格式 ("json", "markdown")
            
        Returns:
            Dict: {"success": bool, "content": str, "filename": str}
        """
        session = get_session_manager().get_session(session_id)
        
        if not session:
            return {
                "success": False,
                "error": f"Session '{session_id}' not found",
            }
        
        if format == "json":
            content = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
            filename = f"{session_id}.json"
        elif format == "markdown":
            content = SessionAPI._session_to_markdown(session)
            filename = f"{session_id}.md"
        else:
            return {
                "success": False,
                "error": f"Unsupported format: {format}",
            }
        
        return {
            "success": True,
            "content": content,
            "filename": filename,
        }
    
    @staticmethod
    def _session_to_markdown(session: ReviewSession) -> str:
        """将会话转换为Markdown格式。"""
        lines = []
        lines.append(f"# 会话: {session.metadata.name or session.session_id}")
        lines.append("")
        lines.append(f"- 会话ID: `{session.session_id}`")
        lines.append(f"- 创建时间: {session.metadata.created_at}")
        lines.append(f"- 更新时间: {session.metadata.updated_at}")
        lines.append(f"- 状态: {session.metadata.status}")
        if session.metadata.project_root:
            lines.append(f"- 项目路径: `{session.metadata.project_root}`")
        if session.metadata.tags:
            lines.append(f"- 标签: {', '.join(session.metadata.tags)}")
        lines.append("")
        lines.append("## 对话历史")
        lines.append("")
        
        for msg in session.conversation.messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                lines.append("### 用户")
            elif role == "assistant":
                lines.append("### 助手")
            elif role == "system":
                lines.append("### 系统")
            elif role == "tool":
                tool_name = msg.get("name", "unknown")
                lines.append(f"### 工具: {tool_name}")
            else:
                lines.append(f"### {role}")
            
            lines.append("")
            if content:
                lines.append(content[:5000])  # 限制长度
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def get_session_messages(
        session_id: str,
        limit: Optional[int] = None,
        role_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取会话消息历史。
        
        Args:
            session_id: 会话ID
            limit: 返回条数（从最新开始）
            role_filter: 按角色过滤
            
        Returns:
            Dict: {"messages": List[{...}], "count": int}
        """
        session = get_session_manager().get_session(session_id)
        
        if not session:
            return {
                "messages": [],
                "count": 0,
                "error": f"Session '{session_id}' not found",
            }
        
        messages = session.conversation.messages
        
        if role_filter:
            messages = [m for m in messages if m.get("role") == role_filter]
        
        if limit:
            messages = messages[-limit:]
        
        return {
            "messages": messages,
            "count": len(messages),
        }
    
    @staticmethod
    def add_message(
        session_id: str,
        role: str,
        content: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """向会话添加消息。
        
        Args:
            session_id: 会话ID
            role: 角色 ("user", "assistant", "system", "tool")
            content: 消息内容
            **kwargs: 额外参数（如tool_calls, tool_call_id等）
            
        Returns:
            Dict: {"success": bool}
        """
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return {
                "success": False,
                "error": f"Session '{session_id}' not found",
            }
        
        session.add_message(role, content, **kwargs)
        manager.save_session(session)
        
        return {"success": True}
    
    @staticmethod
    def clear_session_messages(session_id: str) -> Dict[str, Any]:
        """清空会话消息历史。
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: {"success": bool, "cleared_count": int}
        """
        manager = get_session_manager()
        session = manager.get_session(session_id)
        
        if not session:
            return {
                "success": False,
                "error": f"Session '{session_id}' not found",
            }
        
        count = len(session.conversation.messages)
        session.conversation._messages.clear()
        session.metadata.updated_at = datetime.now().isoformat()
        manager.save_session(session)
        
        return {
            "success": True,
            "cleared_count": count,
        }
    
    @staticmethod
    def get_session_stats() -> Dict[str, Any]:
        """获取会话统计信息。
        
        Returns:
            Dict: {
                "total_sessions": int,
                "by_status": Dict[str, int],
                "by_project": Dict[str, int],
                "total_messages": int
            }
        """
        all_sessions = get_session_manager().list_sessions()
        
        by_status: Dict[str, int] = {}
        by_project: Dict[str, int] = {}
        total_messages = 0
        
        for s in all_sessions:
            # 按状态统计
            status = s.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
            
            # 按项目统计
            project = s.get("project_root") or "unknown"
            by_project[project] = by_project.get(project, 0) + 1
            
            # 消息统计需要读取完整会话
            full_session = get_session_manager().get_session(s["session_id"])
            if full_session:
                total_messages += len(full_session.conversation.messages)
        
        return {
            "total_sessions": len(all_sessions),
            "by_status": by_status,
            "by_project": by_project,
            "total_messages": total_messages,
        }
    
    @staticmethod
    def archive_old_sessions(days: int = 30) -> Dict[str, Any]:
        """归档旧会话。
        
        Args:
            days: 超过多少天的会话被归档
            
        Returns:
            Dict: {"archived_count": int}
        """
        manager = get_session_manager()
        all_sessions = manager.list_sessions()
        
        archived_count = 0
        cutoff = datetime.now().timestamp() - (days * 24 * 3600)
        
        for s in all_sessions:
            if s.get("status") == "archived":
                continue
            
            updated_at = s.get("updated_at")
            if updated_at:
                try:
                    updated_ts = datetime.fromisoformat(updated_at).timestamp()
                    if updated_ts < cutoff:
                        session = manager.get_session(s["session_id"])
                        if session:
                            session.metadata.status = "archived"
                            manager.save_session(session)
                            archived_count += 1
                except Exception:
                    continue
        
        return {"archived_count": archived_count}


__all__ = [
    "SessionAPI",
    "get_session_manager",
]
