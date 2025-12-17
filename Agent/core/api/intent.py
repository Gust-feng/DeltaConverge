"""意图分析API模块。

提供意图分析缓存的读取、写入、状态检查等功能。
与IntentAgent集成，支持触发分析和流式进度反馈。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from pydantic import BaseModel


# --- Data Models ---

@dataclass
class IntentCacheData:
    """意图缓存数据结构。"""
    project_name: str           # 项目名称
    project_root: str           # 项目根路径
    content: str                # Markdown格式的分析内容
    created_at: str             # ISO格式创建时间
    updated_at: str             # ISO格式更新时间
    source: str                 # 来源: "agent" | "manual"


class IntentStatusResponse(BaseModel):
    """意图状态响应。"""
    exists: bool                # 缓存是否存在
    project_name: str           # 项目名称
    created_at: Optional[str] = None   # 创建时间
    updated_at: Optional[str] = None   # 更新时间
    source: Optional[str] = None       # 来源


class IntentUpdateRequest(BaseModel):
    """意图更新请求。"""
    content: str                # 新的Markdown内容


class IntentAnalyzeRequest(BaseModel):
    """意图分析请求。"""
    project_root: str           # 项目根路径
    force_refresh: bool = False # 是否强制刷新


# --- IntentAPI Class ---

class IntentAPI:
    """意图分析API（静态方法接口）。"""
    
    @staticmethod
    def _get_preferred_cache_dir() -> Path:
        """获取意图缓存目录路径（首选）。"""
        # Preferred layout: Agent/data/Analysis
        return (Path(__file__).resolve().parents[2] / "data" / "Analysis").resolve()

    @staticmethod
    def _get_cache_dir() -> Path:
        """获取意图缓存目录路径（唯一）。"""
        return IntentAPI._get_preferred_cache_dir()

    @staticmethod
    def _get_cache_path(project_name: str) -> Path:
        """获取指定项目的缓存文件路径。"""
        return IntentAPI._get_preferred_cache_path(project_name)

    @staticmethod
    def _get_preferred_cache_path(project_name: str) -> Path:
        return IntentAPI._get_preferred_cache_dir() / f"{project_name}.json"

    @staticmethod
    def _extract_project_name(project_root: str) -> str:
        """从项目路径提取项目名称。"""
        root = str(project_root or "").strip()
        if not root:
            return ""
        root = root.rstrip("/\\")
        try:
            return Path(root).name
        except Exception:
            # Fallback: avoid any filesystem interaction
            parts = root.replace("\\", "/").split("/")
            return parts[-1] if parts else ""

    @staticmethod
    def check_intent_status(project_root: str) -> Dict[str, Any]:
        """检查项目是否存在意图缓存。
        
        Args:
            project_root: 项目根路径
            
        Returns:
            Dict: {
                "exists": bool,
                "project_name": str,
                "created_at": Optional[str],
                "updated_at": Optional[str],
                "source": Optional[str]
            }
        """
        project_name = IntentAPI._extract_project_name(project_root)
        cache_path = IntentAPI._get_cache_path(project_name)

        if not cache_path.exists():
            return {
                "exists": False,
                "project_name": project_name,
                "created_at": None,
                "updated_at": None,
                "source": None,
            }
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 支持两种格式：扁平结构（IntentCacheData）和嵌套结构（Agent原始输出）
            created_at = data.get("created_at") or data.get("timestamp")
            updated_at = data.get("updated_at")
            source = data.get("source") or ("agent" if "response" in data else None)
            
            return {
                "exists": True,
                "project_name": project_name,
                "created_at": created_at,
                "updated_at": updated_at,
                "source": source,
            }
        except Exception:
            return {
                "exists": False,
                "project_name": project_name,
                "created_at": None,
                "updated_at": None,
                "source": None,
            }
    
    @staticmethod
    def get_intent_cache(project_root: str) -> Dict[str, Any]:
        """获取项目的意图分析缓存。
        
        Args:
            project_root: 项目根路径
            
        Returns:
            Dict: {
                "found": bool,
                "project_name": str,
                "content": Optional[str],
                "created_at": Optional[str],
                "updated_at": Optional[str],
                "source": Optional[str],
                "error": Optional[str]
            }
        """
        project_name = IntentAPI._extract_project_name(project_root)
        cache_path = IntentAPI._get_cache_path(project_name)

        if not cache_path.exists():
            return {
                "found": False,
                "project_name": project_name,
                "content": None,
                "created_at": None,
                "updated_at": None,
                "source": None,
            }
        
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 支持两种格式：扁平结构（IntentCacheData）和嵌套结构（Agent原始输出）
            content = data.get("content")
            if not content and "response" in data:
                # 尝试从嵌套结构中获取
                response = data.get("response", {})
                if isinstance(response, dict):
                    content = response.get("content")
            
            created_at = data.get("created_at") or data.get("timestamp")
            updated_at = data.get("updated_at")
            source = data.get("source") or ("agent" if "response" in data else None)
            
            return {
                "found": True,
                "project_name": project_name,
                "content": content or "",
                "created_at": created_at,
                "updated_at": updated_at,
                "source": source,
            }
        except Exception as e:
            return {
                "found": False,
                "project_name": project_name,
                "content": None,
                "created_at": None,
                "updated_at": None,
                "source": None,
                "error": str(e),
            }

    @staticmethod
    def update_intent_cache(project_root: str, content: str) -> Dict[str, Any]:
        """更新意图缓存内容。
        
        Args:
            project_root: 项目根路径
            content: 新的Markdown内容
            
        Returns:
            Dict: {
                "success": bool,
                "project_name": str,
                "updated_at": Optional[str],
                "error": Optional[str]
            }
        """
        # 验证内容非空
        if not content or not content.strip():
            return {
                "success": False,
                "project_name": IntentAPI._extract_project_name(project_root),
                "updated_at": None,
                "error": "Content cannot be empty",
            }
        
        project_name = IntentAPI._extract_project_name(project_root)
        cache_path = IntentAPI._get_preferred_cache_path(project_name)

        # 确保缓存目录存在
        cache_dir = IntentAPI._get_preferred_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now().isoformat()
        
        # 读取现有缓存或创建新的
        existing_data = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception:
                pass
        
        # 更新数据
        cache_data = IntentCacheData(
            project_name=project_name,
            project_root=str(Path(project_root).resolve()),
            content=content,
            created_at=existing_data.get("created_at", now),
            updated_at=now,
            source="manual",  # 手动更新标记为manual
        )
        
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(asdict(cache_data), f, ensure_ascii=False, indent=2)
            
            return {
                "success": True,
                "project_name": project_name,
                "updated_at": now,
            }
        except Exception as e:
            return {
                "success": False,
                "project_name": project_name,
                "updated_at": None,
                "error": str(e),
            }
    
    @staticmethod
    def save_intent_cache(
        project_root: str,
        content: str,
        source: str = "agent"
    ) -> Dict[str, Any]:
        """保存意图缓存（内部方法，用于Agent分析结果保存）。
        
        Args:
            project_root: 项目根路径
            content: Markdown内容
            source: 来源标记 ("agent" | "manual")
            
        Returns:
            Dict: {"success": bool, "project_name": str, ...}
        """
        # 验证内容非空
        if not content or not content.strip():
            return {
                "success": False,
                "project_name": IntentAPI._extract_project_name(project_root),
                "error": "Content cannot be empty",
            }
        
        project_name = IntentAPI._extract_project_name(project_root)
        cache_path = IntentAPI._get_preferred_cache_path(project_name)

        # 确保缓存目录存在
        cache_dir = IntentAPI._get_preferred_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        now = datetime.now().isoformat()
        
        cache_data = IntentCacheData(
            project_name=project_name,
            project_root=str(Path(project_root).resolve()),
            content=content,
            created_at=now,
            updated_at=now,
            source=source,
        )
        
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(asdict(cache_data), f, ensure_ascii=False, indent=2)

            IntentAPI._cleanup_legacy_caches(project_name)
            
            return {
                "success": True,
                "project_name": project_name,
                "created_at": now,
            }
        except Exception as e:
            return {
                "success": False,
                "project_name": project_name,
                "error": str(e),
            }

    @staticmethod
    def _collect_project_overview(project_root: str) -> Dict[str, Any]:
        """收集项目概览数据用于意图分析。
        
        Args:
            project_root: 项目根路径
            
        Returns:
            Dict: 项目概览数据，包含文件列表、README、Git信息等
        """
        from Agent.core.api.project import ProjectAPI
        
        overview: Dict[str, Any] = {
            "project_root": project_root,
        }
        
        # 获取项目基本信息
        try:
            project_info = ProjectAPI.get_project_info(project_root)
            overview["project_info"] = project_info
        except Exception as e:
            overview["project_info"] = {"error": str(e)}
        
        # 获取文件树（限制深度为2以控制大小）
        try:
            file_tree = ProjectAPI.get_file_tree(project_root, max_depth=2)
            overview["file_tree"] = file_tree
        except Exception as e:
            overview["file_tree"] = {"error": str(e)}
        
        # 获取README内容
        try:
            readme = ProjectAPI.get_readme_content(project_root)
            overview["readme"] = readme
        except Exception as e:
            overview["readme"] = {"error": str(e)}
        
        # 获取Git信息
        try:
            git_info = ProjectAPI.get_git_info(project_root)
            overview["git_info"] = git_info
        except Exception as e:
            overview["git_info"] = {"error": str(e)}
        
        # 获取依赖信息
        try:
            dependencies = ProjectAPI.get_dependencies(project_root)
            overview["dependencies"] = dependencies
        except Exception as e:
            overview["dependencies"] = {"error": str(e)}
        
        return overview

    @staticmethod
    async def run_intent_analysis(
        project_root: str,
        stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        force_refresh: bool = False,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """运行意图分析并返回结果。
        
        Args:
            project_root: 项目根路径
            stream_callback: 可选的流式回调函数，用于接收进度事件
            force_refresh: 是否强制刷新（忽略现有缓存）
            
        Returns:
            Dict: {
                "success": bool,
                "project_name": str,
                "content": Optional[str],
                "error": Optional[str],
                "cached": bool  # 是否来自缓存
            }
        """
        project_name = IntentAPI._extract_project_name(project_root)
        
        # 检查缓存是否启用
        cache_enabled = True
        try:
            from Agent.core.api.config import get_intent_cache_enabled
            cache_enabled = get_intent_cache_enabled()
        except Exception:
            pass
        
        # 检查缓存（除非强制刷新或缓存被禁用）
        if not force_refresh and cache_enabled:
            cache_result = IntentAPI.get_intent_cache(project_root)
            if cache_result.get("found"):
                if stream_callback:
                    stream_callback({
                        "type": "progress",
                        "stage": "cache_hit",
                        "message": f"使用已有缓存: {project_name}",
                    })
                return {
                    "success": True,
                    "project_name": project_name,
                    "content": cache_result.get("content"),
                    "cached": True,
                }
        
        # 验证项目路径
        project_path = Path(project_root).resolve()
        if not project_path.is_dir():
            error_msg = f"项目目录不存在: {project_root}"
            if stream_callback:
                stream_callback({
                    "type": "error",
                    "message": error_msg,
                })
            return {
                "success": False,
                "project_name": project_name,
                "content": None,
                "error": error_msg,
                "cached": False,
            }
        
        # 收集项目概览
        
        try:
            overview = IntentAPI._collect_project_overview(str(project_path))
        except Exception as e:
            error_msg = f"收集项目信息失败: {str(e)}"
            if stream_callback:
                stream_callback({
                    "type": "error",
                    "message": error_msg,
                })
            return {
                "success": False,
                "project_name": project_name,
                "content": None,
                "error": error_msg,
                "cached": False,
            }
        
        # 创建LLM适配器和IntentAgent
        
        try:
            from Agent.core.api.factory import LLMFactory
            from Agent.core.adapter.llm_adapter import OpenAIAdapter
            from Agent.core.stream.stream_processor import StreamProcessor
            from Agent.agents.intent_agent import IntentAgent
            
            # 创建LLM客户端 - 删除回退机制，该怎么样就怎么样，不能让用户无感知使用其他模型
            if not model:
                raise ValueError("未指定模型，请先选择模型")
            client, provider_name = LLMFactory.create(preference=model)
            
            # 创建适配器
            stream_processor = StreamProcessor()
            adapter = OpenAIAdapter(
                client=client,
                stream_processor=stream_processor,
                provider_name=provider_name,
            )
            
            # 创建IntentAgent
            agent = IntentAgent(adapter=adapter)
            
        except Exception as e:
            error_msg = f"初始化Agent失败: {str(e)}"
            if stream_callback:
                stream_callback({
                    "type": "error",
                    "message": error_msg,
                })
            return {
                "success": False,
                "project_name": project_name,
                "content": None,
                "error": error_msg,
                "cached": False,
            }
        
        # 执行分析
        
        # 创建流式观察者（用于转发LLM输出）
        def llm_observer(evt: Dict[str, Any]) -> None:
            if stream_callback:
                # 处理思考内容（reasoning_delta 来自 StreamProcessor）
                reasoning_delta = evt.get("reasoning_delta", "")
                if reasoning_delta:
                    stream_callback({
                        "type": "reasoning",
                        "delta": reasoning_delta,
                    })
                # 处理普通内容（content_delta 来自 StreamProcessor）
                content_delta = evt.get("content_delta", "")
                if content_delta:
                    stream_callback({
                        "type": "content",
                        "delta": content_delta,
                    })
        
        try:
            # 运行IntentAgent
            result_content = await agent.run(
                intent_input=overview,
                stream=True,
                observer=llm_observer,
            )
            
            # 关闭LLM客户端
            await client.aclose()
            
        except Exception as e:
            error_msg = f"分析执行失败: {str(e)}"
            if stream_callback:
                stream_callback({
                    "type": "error",
                    "message": error_msg,
                })
            # 尝试关闭客户端
            try:
                await client.aclose()
            except Exception:
                pass
            return {
                "success": False,
                "project_name": project_name,
                "content": None,
                "error": error_msg,
                "cached": False,
            }
        
        # 验证结果
        if not result_content or not result_content.strip():
            error_msg = "分析结果为空"
            if stream_callback:
                stream_callback({
                    "type": "error",
                    "message": error_msg,
                })
            return {
                "success": False,
                "project_name": project_name,
                "content": None,
                "error": error_msg,
                "cached": False,
            }
        
        # 保存到缓存
        if stream_callback:
            stream_callback({
                "type": "progress",
                "stage": "saving",
                "message": "\n正在保存分析结果...",
            })
        
        save_result = IntentAPI.save_intent_cache(
            project_root=str(project_path),
            content=result_content,
            source="agent",
        )
        
        if not save_result.get("success"):
            # 保存失败但分析成功，仍然返回结果
            if stream_callback:
                stream_callback({
                    "type": "warning",
                    "message": f"保存缓存失败: {save_result.get('error')}",
                })
        
        # 发送完成事件
        if stream_callback:
            stream_callback({
                "type": "progress",
                "stage": "complete",
                "message": "\n分析完成",
            })
        
        return {
            "success": True,
            "project_name": project_name,
            "content": result_content,
            "cached": False,
        }

    @staticmethod
    async def run_intent_analysis_sse(
        project_root: str,
        force_refresh: bool = False,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """运行意图分析并以SSE事件流形式返回结果。
        
        Args:
            project_root: 项目根路径
            force_refresh: 是否强制刷新
            
        Yields:
            Dict: SSE事件，包含type字段标识事件类型
                - progress: 进度事件
                - content: 内容增量
                - error: 错误事件
                - final: 最终结果
                - done: 完成标记
        """
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        
        def stream_callback(evt: Dict[str, Any]) -> None:
            """将事件放入队列。"""
            try:
                queue.put_nowait(evt)
            except Exception:
                pass
        
        async def run_analysis() -> None:
            """执行分析任务。"""
            try:
                result = await IntentAPI.run_intent_analysis(
                    project_root=project_root,
                    stream_callback=stream_callback,
                    force_refresh=force_refresh,
                    model=model,
                )
                await queue.put({"type": "final", "result": result})
            except Exception as e:
                await queue.put({"type": "error", "message": str(e)})
            finally:
                await queue.put({"type": "done"})
        
        # 启动分析任务
        task = asyncio.create_task(run_analysis())
        
        try:
            while True:
                evt = await queue.get()
                yield evt
                if evt.get("type") in {"done", "error"} and evt.get("type") != "error":
                    # error类型继续等待done
                    pass
                if evt.get("type") == "done":
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


__all__ = [
    "IntentAPI",
    "IntentCacheData",
    "IntentStatusResponse",
    "IntentUpdateRequest",
    "IntentAnalyzeRequest",
]
