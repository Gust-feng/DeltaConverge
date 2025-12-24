import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from pathlib import Path
import os
import subprocess
import time

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Agent.core.api import available_llm_options, available_tools, run_review_async_entry
from Agent.core.api import ConfigAPI, CacheAPI, HealthAPI, IntentAPI
from Agent.core.api import DiffAPI, ToolAPI, LogAPI, ProjectAPI, SessionAPI, ModelAPI
from Agent.core.api import RuleGrowthAPI
from Agent.DIFF.rule.scanner_registry import ScannerRegistry
from Agent.DIFF.rule.scanner_performance import AvailabilityCache
from Agent.core.api.intent import IntentAnalyzeRequest, IntentUpdateRequest
from Agent.core.api.factory import LLMFactory
from Agent.core.api.session import get_session_manager
from Agent.core.context.diff_provider import collect_diff_context
from Agent.tool.registry import default_tool_names, get_tool_schemas
from Agent.core.state.session import ReviewSession
from UI.dialogs import pick_folder as pick_folder_dialog

app = FastAPI()
# 使用统一的会话管理器单例
session_manager = get_session_manager()

_SCANNER_STATUS_CACHE_TTL_SECONDS = 60.0
_scanner_status_cache: Dict[str, Dict[str, Any]] = {}

# 允许跨域（方便前端调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 禁用静态文件缓存（开发模式）
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.endswith(('.js', '.css', '.html')):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)


def _bootstrap_env() -> None:
    env = {}
    try:
        env = _load_env()
    except Exception:
        env = {}
    for k, v in env.items():
        if not os.environ.get(k):
            os.environ[k] = v

_bootstrap_env()


def _is_running_in_docker() -> bool:
    try:
        flags = (
            os.environ.get("RUNNING_IN_DOCKER"),
            os.environ.get("DOCKER"),
            os.environ.get("IS_DOCKER"),
        )
        if any(f for f in flags if str(f).lower() in ("1", "true", "yes", "on")):
            return True
    except Exception:
        pass
    try:
        return os.path.exists("/.dockerenv")
    except Exception:
        return False


def _parse_git_status_porcelain_z(out: str) -> List[Dict[str, Any]]:
    if not out:
        return []
    items = out.split("\x00")
    result: List[Dict[str, Any]] = []
    i = 0
    while i < len(items):
        rec = items[i]
        i += 1
        if not rec:
            continue
        if len(rec) < 4:
            continue
        x = rec[0]
        y = rec[1]
        path = rec[3:]

        old_path = None
        new_path = None
        display_path = path
        if x in ("R", "C") and i < len(items):
            old_path = path
            new_path = items[i]
            i += 1
            if new_path:
                display_path = f"{old_path} -> {new_path}"
                path = new_path

        st_code = x if x and x != " " else y
        ch = {
            "A": "add",
            "M": "modify",
            "D": "delete",
            "R": "rename",
            "C": "copy",
        }.get(st_code, "modify")

        result.append({
            "x": x,
            "y": y,
            "path": path,
            "old_path": old_path,
            "new_path": new_path,
            "display_path": display_path,
            "change_type": ch,
        })
    return result


class ReviewRequest(BaseModel):
    prompt: Optional[str] = None
    model: str = "auto"
    tools: Optional[List[str]] = None
    autoApprove: bool = False
    project_root: Optional[str] = None
    session_id: Optional[str] = None
    agents: Optional[List[str]] = None  # 新增：指定运行的 Agents
    enableStaticScan: bool = False  # 是否启用静态分析旁路扫描

class IntentAnalyzeStreamRequest(BaseModel):
    project_root: str
    force_refresh: bool = False
    model: Optional[str] = None  # 保留字段，兼容旧调用


class ModelUpdate(BaseModel):
    provider: str
    model: Optional[str] = None
    model_name: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: str = "auto"
    tools: Optional[List[str]] = None
    autoApprove: bool = False
    project_root: Optional[str] = None

class SessionCreate(BaseModel):
    session_id: str
    project_root: Optional[str] = None


class SessionRename(BaseModel):
    session_id: str
    new_name: str


class SessionDelete(BaseModel):
    session_id: str


class ReviewReportParseRequest(BaseModel):
    text: Optional[str] = None
    session_id: Optional[str] = None
    diff_units: Optional[List[Dict[str, Any]]] = None
    include_items: bool = True
    include_blocks: bool = True
    map_to_units: bool = False


def _safe_event(evt: Dict[str, Any]) -> Dict[str, Any]:
    """避免把巨型 raw 字段塞进 SSE。"""
    cleaned = dict(evt)
    cleaned.pop("raw", None)
    return cleaned


def _prewarm_scanner_availability_for_languages(langs: List[str]) -> None:
    try:
        if not isinstance(langs, list) or not langs:
            return
        lang_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "react": "javascript",
            "react/typescript": "typescript",
            "java": "java",
            "go": "go",
            "ruby": "ruby",
            "c++": "cpp",
            "c": "c",
            "php": "php",
            "rust": "rust",
        }
        target_langs: List[str] = []
        for l in langs:
            key = str(l).lower().replace(" ", "")
            mapped = lang_map.get(key)
            if mapped:
                target_langs.append(mapped)
        for language in set(target_langs):
            try:
                classes = ScannerRegistry.get_scanner_classes(language)
                for cls in classes:
                    command = getattr(cls, "command", "")
                    if command:
                        AvailabilityCache.check(command, refresh=True)
            except Exception:
                continue
    except Exception:
        pass


def _prewarm_scanner_availability_from_project(project_root: Optional[str]) -> None:
    try:
        info = ProjectAPI.get_project_info(project_root)
        _prewarm_scanner_availability_for_languages(info.get("detected_languages", []))
    except Exception:
        pass


@app.post("/api/system/pick-folder")
async def pick_folder():
    """打开系统文件夹选择对话框并返回路径。"""
    try:
        # 在线程池中运行阻塞的 GUI 操作，避免阻塞 asyncio 事件循环
        path = await asyncio.to_thread(pick_folder_dialog)
        
        if not path:
            return {"path": None}
            
        return {"path": path}
    except Exception as e:
        return {"error": str(e)}


def is_docker() -> bool:
    try:
        flags = (
            os.environ.get("RUNNING_IN_DOCKER"),
            os.environ.get("DOCKER"),
            os.environ.get("IS_DOCKER"),
        )
        if any(f for f in flags if str(f).lower() in ("1", "true", "yes")):
            return True
        if os.path.exists("/.dockerenv"):
            return True
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
                c = f.read().lower()
                if "docker" in c or "kubepods" in c or "containerd" in c:
                    return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _docker_path_restrictions_enabled() -> bool:
    raw = os.getenv("DOCKER_PATH_RESTRICTIONS")
    if raw is None:
        return False
    return str(raw).lower() in ("1", "true", "yes", "on")


def _get_allowed_project_roots() -> List[Path]:
    roots: List[str] = []
    raw = os.getenv("ALLOWED_PROJECT_ROOTS")
    if raw:
        roots.extend([p.strip() for p in raw.split(",") if p.strip()])
    default_root = os.getenv("DEFAULT_PROJECT_ROOT")
    if default_root:
        roots.append(default_root)
    if not roots:
        roots.append("/workspace")
    out: List[Path] = []
    for r in roots:
        try:
            out.append(Path(r).expanduser().resolve())
        except Exception:
            continue
    return out


def _is_path_allowed_in_docker(target: Path, allowed_roots: List[Path]) -> bool:
    for base_path in allowed_roots:
        try:
            target.relative_to(base_path)
            return True
        except Exception:
            continue
    return False

class ListDirRequest(BaseModel):
    path: Optional[str] = None

@app.get("/api/system/env")
async def system_env():
    drives: List[str] = []
    try:
        if sys.platform == "win32":
            import string
            for d in string.ascii_uppercase:
                p = Path(f"{d}:/")
                if p.exists():
                    drives.append(f"{d}:\\")
    except Exception:
        pass
    docker_mode = is_docker()
    restrictions_enabled = docker_mode and _docker_path_restrictions_enabled()
    allowed_roots = _get_allowed_project_roots() if restrictions_enabled else []
    default_project_root = os.getenv("DEFAULT_PROJECT_ROOT") or (str(allowed_roots[0]) if allowed_roots else None)
    if docker_mode and not default_project_root:
        default_project_root = "/"
    return {
        "is_docker": docker_mode,
        "platform": sys.platform,
        "default_project_root": default_project_root,
        "allowed_project_roots": [str(p) for p in allowed_roots],
        "docker_path_restrictions": restrictions_enabled,
        "drives": drives,
        "base": os.getcwd(),
    }

@app.post("/api/system/list-directory")
def list_directory(req: ListDirRequest):
    try:
        docker_mode = is_docker()
        restrictions_enabled = docker_mode and _docker_path_restrictions_enabled()
        allowed_roots = _get_allowed_project_roots() if restrictions_enabled else []
        default_root = os.getenv("DEFAULT_PROJECT_ROOT")
        if default_root:
            base = default_root
        elif allowed_roots:
            base = str(allowed_roots[0])
        elif docker_mode:
            base = "/"
        else:
            base = os.getcwd()
        target_str = req.path or base
        target = Path(target_str).expanduser().resolve()
        if restrictions_enabled:
            if not _is_path_allowed_in_docker(target, allowed_roots):
                allowed_text = ", ".join(str(p) for p in allowed_roots) if allowed_roots else "(none)"
                return {
                    "error": (
                        "路径不在允许的范围内（Docker）。"
                        f" 允许的根目录: {allowed_text}. "
                        "请将需要审查的项目通过 volume 挂载到上述目录之一，并在 docker-compose 设置 DEFAULT_PROJECT_ROOT 或 ALLOWED_PROJECT_ROOTS。"
                    ),
                    "path": str(target),
                    "children": [],
                }
        if not target.exists() or not target.is_dir():
            return {"error": "目录不存在", "path": str(target), "children": []}
        children: List[Dict[str, str]] = []
        skipped = {".git", "node_modules", "__pycache__", "venv", ".venv"}
        try:
            for entry in target.iterdir():
                try:
                    name = entry.name
                    if name in skipped:
                        continue
                    if entry.is_dir():
                        children.append({"name": name, "type": "dir"})
                        if len(children) >= 200:
                            break
                except Exception:
                    continue
        except Exception:
            pass
        children.sort(key=lambda x: x.get("name", "").lower())
        return {"path": str(target), "children": children}
    except Exception as e:
        return {"error": str(e), "path": str(req.path or ""), "children": []}

# --- 环境变量管理 API ---

class EnvVarUpdate(BaseModel):
    key: str
    value: Optional[str] = None

ENV_FILE = ROOT / ".env"

def _parse_env_line(line: str) -> Optional[tuple]:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.lower().startswith("export "):
        s = s[7:].strip()
    if "=" not in s:
        return None
    k, v = s.split("=", 1)
    k = k.strip()
    v = v.strip()
    if (v.startswith("\"") and v.endswith("\"")) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    return (k, v)

def _load_env() -> Dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out: Dict[str, str] = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_env_line(line)
                if parsed:
                    k, v = parsed
                    out[k] = v
    except Exception:
        pass
    return out

def _quote_if_needed(value: str) -> str:
    if value is None:
        return ""
    if any(ch in value for ch in [' ', '#', '=', '"', "'", '\\']):
        return "'" + value.replace("'", "'\"'\"'") + "'"
    return value

def _save_env(env: Dict[str, str]) -> None:
    lines: List[str] = []
    for k, v in env.items():
        lines.append(f"{k}={_quote_if_needed(v)}\n")
    tmp = ENV_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    try:
        os.replace(tmp, ENV_FILE)
    except Exception:
        # Fallback for Windows if replace fails
        try:
            if ENV_FILE.exists():
                os.remove(ENV_FILE)
        except Exception:
            pass
        os.rename(tmp, ENV_FILE)

def _valid_key(key: str) -> bool:
    if not key:
        return False
    if key[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_":
        return False
    for ch in key[1:]:
        if ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789":
            return False
    return True

@app.get("/api/env/vars")
async def list_env_vars():
    return _load_env()

@app.post("/api/env/vars")
async def set_env_var(req: EnvVarUpdate):
    if not _valid_key(req.key):
        raise HTTPException(status_code=400, detail="Invalid key")
    value = req.value or ""
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=400, detail="Invalid value")
    env = _load_env()
    env[req.key] = value
    _save_env(env)
    # 更新进程环境，便于后续调用即时生效（重启更保险）
    os.environ[req.key] = value
    return {"success": True}

@app.delete("/api/env/vars/{key}")
async def delete_env_var(key: str):
    if not _valid_key(key):
        raise HTTPException(status_code=400, detail="Invalid key")
    env = _load_env()
    if key in env:
        env.pop(key)
        _save_env(env)
    try:
        os.environ.pop(key, None)
    except Exception:
        pass
    return {"success": True}


class ProviderKeyUpdate(BaseModel):
    provider: str
    value: Optional[str] = None


def _mask_secret(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) <= 6:
        return "••••••"
    return "••••••••" + s[-4:]


@app.get("/api/providers/keys")
async def list_provider_keys():
    env = _load_env()
    providers = []
    for name, cfg in LLMFactory.PROVIDERS.items():
        env_key = cfg.api_key_env
        raw = env.get(env_key)
        if not raw:
            raw = os.environ.get(env_key) or ""
        raw = raw.strip() if isinstance(raw, str) else ""
        providers.append({
            "provider": name,
            "label": cfg.label,
            "configured": bool(raw),
            "masked": _mask_secret(raw),
        })
    return {"providers": providers}


@app.post("/api/providers/keys")
async def set_provider_key(req: ProviderKeyUpdate):
    provider = str(req.provider or "").strip()
    cfg = LLMFactory.PROVIDERS.get(provider)
    if not cfg:
        raise HTTPException(status_code=400, detail="Unknown provider")

    value = (req.value or "").strip()
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=400, detail="Invalid value")

    env_key = cfg.api_key_env
    env = _load_env()
    if value:
        env[env_key] = value
        os.environ[env_key] = value
    else:
        env.pop(env_key, None)
        try:
            os.environ.pop(env_key, None)
        except Exception:
            pass
    _save_env(env)
    return {"success": True, "provider": provider, "configured": bool(value)}


@app.post("/api/diff/check")
def check_diff(req: ReviewRequest):
    """检查当前项目的 Diff 状态，返回变更文件列表。"""
    try:
        # Resolve target path if provided
        cwd = None
        if req.project_root:
            target_path = Path(req.project_root).expanduser().resolve()
            if not target_path.is_dir():
                raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_root}")
            cwd = str(target_path)
        
        diff_ctx = collect_diff_context(cwd=cwd)
        return {
            "summary": diff_ctx.summary,
            "files": diff_ctx.files,
            "stats": {
                "total_files": len(diff_ctx.files),
                "mode": diff_ctx.mode.value,
                "base_branch": diff_ctx.base_branch
            }
        }
    except Exception as e:
        return {"error": str(e), "files": []}


@app.get("/api/options")
async def get_options():
    """模型与工具选项（含默认工具 schema），缺省时提供兜底值。"""
    models = available_llm_options()
    if not models:
        models = [
            {"name": "auto", "available": True, "reason": None},
            {"name": "mock", "available": True, "reason": "fallback"},
        ]

    tools = available_tools()
    if not tools:
        defaults = set(default_tool_names())
        tools = [
            {"name": name, "default": name in defaults, "description": None}
            for name in defaults
        ]

    schemas = get_tool_schemas(default_tool_names())
    return {"models": models, "tools": tools, "schemas": schemas}


@app.post("/api/models/add")
async def api_add_model(req: ModelUpdate):
    """添加新模型。"""
    try:
        target = req.model or req.model_name
        if not target:
            raise HTTPException(status_code=400, detail="model required")
        LLMFactory.add_model(req.provider, target)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/static-scan/issues")
async def get_static_scan_issues(
    session_id: str,
    severity: str = "error",
    offset: int = 0,
    limit: int = 50,
):
    try:
        from Agent.DIFF.static_scan_service import get_static_scan_issues_page
        return get_static_scan_issues_page(
            session_id=session_id,
            severity=severity,
            offset=offset,
            limit=limit,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="static_scan_issues_not_found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/static-scan/linked")
async def get_static_scan_linked(session_id: str):
    session = session_manager.get_session(session_id)

    linked: Optional[Dict[str, Any]] = None
    if session:
        try:
            existing = getattr(session, "static_scan_linked", None)
            if isinstance(existing, dict) and existing:
                linked = dict(existing)
        except Exception:
            linked = None

    if linked is None:
        try:
            from Agent.DIFF.static_scan_service import get_static_scan_linked as _get_static_scan_linked
            linked = dict(_get_static_scan_linked(session_id=session_id))
        except KeyError:
            linked = None
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if linked is None:
        if not session:
            raise HTTPException(status_code=404, detail="static_scan_linked_not_found")
        linked = {
            "session_id": session_id,
            "generated_at": None,
            "diff_units": session.diff_units or [],
        }

    if session:
        try:
            from Agent.DIFF.static_scan_service import parse_review_report_issues, build_linked_unit_llm_suggestions

            content = ""
            messages = session.conversation.messages if session.conversation else []
            for m in reversed(messages or []):
                if m.get("role") != "assistant":
                    continue
                c = (m.get("content") or "").strip()
                if c:
                    content = m.get("content") or ""
                    break

            suggestions = parse_review_report_issues(content)
            units = linked.get("diff_units")
            if not isinstance(units, list) or not units:
                units = session.diff_units or []
                linked["diff_units"] = units

            llm_linked = build_linked_unit_llm_suggestions(units=units, suggestions=suggestions)
            linked.update(llm_linked)

            session.static_scan_linked = linked
            session_manager.save_session(session)
        except Exception:
            pass

    return linked


@app.post("/api/review-report/parse")
async def parse_review_report(req: ReviewReportParseRequest):
    try:
        text = str(req.text or "")

        if (not text or not text.strip()) and req.session_id:
            session = session_manager.get_session(req.session_id)
            if session:
                messages = session.conversation.messages if session.conversation else []
                for m in reversed(messages or []):
                    if m.get("role") != "assistant":
                        continue
                    c = (m.get("content") or "").strip()
                    if c:
                        text = m.get("content") or ""
                        break

        if not text or not str(text).strip():
            raise HTTPException(status_code=400, detail="text_required")

        from Agent.DIFF.static_scan_service import (
            parse_review_report_issues,
            parse_review_report_blocks,
            build_linked_unit_llm_suggestions,
        )

        items = parse_review_report_issues(text) if req.include_items else []
        blocks = parse_review_report_blocks(text) if req.include_blocks else []

        mapping: Optional[Dict[str, Any]] = None
        if req.map_to_units:
            units = req.diff_units
            if not units and req.session_id:
                session = session_manager.get_session(req.session_id)
                if session:
                    units = session.diff_units or []
            mapping = build_linked_unit_llm_suggestions(units=units or [], suggestions=items)

        return {
            "items": items,
            "blocks": blocks,
            "mapping": mapping,
            "meta": {
                "text_len": len(str(text)),
                "items_total": len(items),
                "blocks_total": len(blocks),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/models/delete")
async def api_remove_model(req: ModelUpdate):
    """移除模型。"""
    try:
        target = req.model or req.model_name
        if not target:
            raise HTTPException(status_code=400, detail="model required")
        LLMFactory.remove_model(req.provider, target)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/create")
def create_session(req: SessionCreate, background_tasks: BackgroundTasks):
    """创建一个新的会话。"""
    try:
        session = session_manager.create_session(req.session_id, req.project_root)
        background_tasks.add_task(_prewarm_scanner_availability_from_project, req.project_root)
        return {"status": "ok", "session": session.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/list")
async def list_sessions(
    status: Optional[str] = None,
    project_root: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """列出所有会话（支持过滤）。"""
    try:
        return SessionAPI.list_sessions(
            status=status,
            project_root=project_root,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/stats")
async def get_session_stats():
    """获取会话统计信息。"""
    try:
        return SessionAPI.get_session_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/rename")
async def rename_session(req: SessionRename):
    """重命名会话。"""
    try:
        result = SessionAPI.update_session(req.session_id, name=req.new_name)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["error"])
        return {"status": "ok", "session": result["session"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sessions/delete")
async def delete_session(req: SessionDelete):
    """删除会话。"""
    try:
        result = SessionAPI.delete_session(req.session_id)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result.get("error", "Delete failed"))
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话详情。"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@app.get("/api/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """获取指定会话的完成状态（用于前端轮询）。"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    meta_status = getattr(session.metadata, "status", None)
    if meta_status == "completed":
        return {"completed": True, "status": meta_status}

    messages = session.conversation.messages if session.conversation else []
    has_final_report = any(m.get("role") == "assistant" and (m.get("content") or "").strip() for m in messages)
    return {"completed": bool(has_final_report), "status": meta_status or "active"}


@app.post("/api/chat/send")
async def chat_send(req: ChatRequest):
    """发送消息进行多轮对话（SSE 流式）。"""
    
    session = session_manager.get_session(req.session_id)
    if not session:
        session = session_manager.create_session(req.session_id, req.project_root)
    
    session.add_message("user", req.message)
    session_manager.save_session(session)

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    def stream_callback(evt: Dict[str, Any]) -> None:
        try:
            evt_type = evt.get("type", "")

            if evt_type == "diff_units_snapshot":
                try:
                    df = evt.get("diff_files")
                    du = evt.get("diff_units")
                    if isinstance(df, list) and df:
                        session.diff_files = df
                    if isinstance(du, list) and du:
                        session.diff_units = du
                    session_manager.save_session(session)
                except Exception:
                    pass
                return

            stage = None
            if evt_type == "planner_delta":
                stage = "planner"
            elif evt_type == "intent_delta":
                stage = "intent"
            elif evt_type == "delta":
                stage = "review"
            
            # 处理所有包含 content_delta/reasoning_delta 的事件类型
            # 包括: delta, planner_delta, intent_delta 等
            if evt_type in ("delta", "planner_delta", "intent_delta") or "delta" in evt_type:
                # 1. 思考过程
                reasoning = evt.get("reasoning_delta")
                if reasoning:
                    queue.put_nowait({"type": "thought", "content": reasoning, "stage": stage})
                
                # 2. 正文内容
                content = evt.get("content_delta")
                if content:
                    queue.put_nowait({"type": "chunk", "content": content, "stage": stage})
                
                # 3. 工具调用 (StreamProcessor 的 tool_calls_delta 是列表)
                tool_calls = evt.get("tool_calls_delta")
                if tool_calls:
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function")
                            if isinstance(fn, dict) and fn.get("name"):
                                queue.put_nowait({"type": "tool_start", "tool": fn.get("name")})

            # 兼容旧格式或直接 event 格式 (如 tool_start, tool_result, step 等)
            else:
                safe_evt = _safe_event(evt)
                queue.put_nowait(safe_evt)
                # 保存扫描器事件以便历史回放（聊天模式可能也触发规则扫描）
                evt_type2 = evt.get("type", "")
                if evt_type2 in ("scanner_progress", "scanner_issues_summary", "scanner_init"):
                    session.add_workflow_event(safe_evt)
                    session_manager.save_session(session)
        except Exception:
            pass

    async def run_agent() -> None:
        try:
            # 这里我们区分“全量审查”和“普通对话”
            # 简单起见，如果 Session 历史消息较少（<=2，即 user+system），或者是显式的“start”，则视为新审查
            # 否则视为后续对话，传入 message_history
            # 注意：run_review_async_entry 每次都会创建新的 Kernel，但它现在支持 message_history
            # 这意味着 Planner 会看到以前的对话，从而做出更明智的决策（例如跳过 Diff 分析，直接回答）
            # 理想情况下，应该复用 Kernel 实例，但为了稳定性，先采用“无状态 Kernel + 有状态 Session”的模式

            # 导出历史消息用于注入
            history = session.conversation.messages[:-1]

            result = await run_review_async_entry(
                prompt=req.message,
                llm_preference=req.model,
                tool_names=req.tools or default_tool_names(),
                auto_approve=True,
                project_root=req.project_root,
                stream_callback=stream_callback,
                session_id=req.session_id,
                message_history=history,
            )

            session.add_message("assistant", str(result))
            session_manager.save_session(session)
            await queue.put({"type": "final", "content": str(result)})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put({"type": "done"})

    task = asyncio.create_task(run_agent())

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                evt = await queue.get()
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt.get("type") in {"done"}:
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class IntentUpdatePayload(BaseModel):
    project_root: str
    content: str


@app.post("/api/intent/update")
async def update_intent(payload: IntentUpdatePayload):
    """更新意图缓存内容。
    
    Args:
        payload: 包含 project_root 和 content
        
    Returns:
        Dict: 更新结果
    """
    try:
        return IntentAPI.update_intent_cache(
            project_root=payload.project_root,
            content=payload.content
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/review/start")
async def start_review(req: ReviewRequest):
    """启动一次代码审查，使用 SSE 流式返回事件。"""

    # 1. 确保会话存在
    session_id = req.session_id
    if not session_id:
        import time
        import secrets
        session_id = f"sess_{int(time.time())}_{secrets.token_hex(4)}"
    
    session = session_manager.get_session(session_id)
    if not session:
        session = session_manager.create_session(session_id, req.project_root)
    
    # 更新项目路径（如果变化）
    if req.project_root and session.metadata.project_root != req.project_root:
        session.metadata.project_root = req.project_root
        session_manager.save_session(session)

    # 保存变更文件快照（用于历史会话回放）
    if req.project_root and (not session.diff_files or not getattr(session, "diff_units", None)):
        try:
            diff_ctx = collect_diff_context(cwd=req.project_root)
            # 从review_index获取更详细的文件信息
            review_files = diff_ctx.review_index.get("files", []) if diff_ctx.review_index else []

            if not session.diff_files:
                if review_files:
                    session.diff_files = [
                        {
                            "path": f.get("path", ""),
                            "display_path": f.get("path", ""),
                            "change_type": f.get("change_type", "modify"),
                        }
                        for f in review_files
                    ]
                else:
                    # 回退到简单文件列表
                    session.diff_files = [
                        {"path": str(f), "display_path": str(f), "change_type": "modify"}
                        for f in (diff_ctx.files or [])
                    ]

            if not getattr(session, "diff_units", None):
                def _prune_unit(u: Dict[str, Any]) -> Dict[str, Any]:
                    return {
                        "unit_id": u.get("unit_id") or u.get("id"),
                        "file_path": u.get("file_path"),
                        "change_type": u.get("change_type") or u.get("patch_type"),
                        "hunk_range": u.get("hunk_range") or {},
                        "unified_diff": u.get("unified_diff") or "",
                        "unified_diff_with_lines": u.get("unified_diff_with_lines"),
                        "tags": u.get("tags") or [],
                        "rule_context_level": u.get("rule_context_level"),
                        "rule_confidence": u.get("rule_confidence"),
                    }

                session.diff_units = [_prune_unit(u) for u in (diff_ctx.units or [])]
            session_manager.save_session(session)
        except Exception as e:
            print(f"[WARN] Failed to save diff_files snapshot: {e}")

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    static_scan_start_evt: asyncio.Event = asyncio.Event()
    static_scan_done_evt: asyncio.Event = asyncio.Event()

    accept_stream_events: bool = True

    def stream_callback(evt: Dict[str, Any]) -> None:
        try:
            evt_type = evt.get("type", "")

            if evt_type == "diff_units_snapshot":
                try:
                    df = evt.get("diff_files")
                    du = evt.get("diff_units")
                    if isinstance(df, list) and df:
                        session.diff_files = df
                    if isinstance(du, list) and du:
                        session.diff_units = du
                    session_manager.save_session(session)
                except Exception:
                    pass
                return

            if evt_type == "static_scan_start":
                static_scan_start_evt.set()
                try:
                    if int(evt.get("files_total") or 0) <= 0:
                        static_scan_done_evt.set()
                except Exception:
                    pass
            elif evt_type == "static_scan_complete":
                static_scan_start_evt.set()
                static_scan_done_evt.set()
                try:
                    from Agent.DIFF.static_scan_service import get_static_scan_linked
                    session.static_scan_linked = get_static_scan_linked(session_id=session_id)
                except Exception:
                    pass

            stage = None
            if evt_type == "planner_delta":
                stage = "planner"
            elif evt_type == "intent_delta":
                stage = "intent"
            elif evt_type == "delta":
                stage = "review"
            
            # 处理所有包含 content_delta/reasoning_delta 的事件类型
            # 包括: delta, planner_delta, intent_delta 等
            if evt_type in ("delta", "planner_delta", "intent_delta") or "delta" in evt_type:
                # 1. 思考过程 - 只累积，不立即保存
                reasoning = evt.get("reasoning_delta")
                if reasoning:
                    workflow_evt = {"type": "thought", "content": reasoning, "stage": stage}
                    queue.put_nowait(workflow_evt)
                    session.add_workflow_event(workflow_evt)
                    # 不保存：高频低优先级事件
                
                # 2. 正文内容 - 只累积，不立即保存
                content = evt.get("content_delta")
                if content:
                    workflow_evt = {"type": "chunk", "content": content, "stage": stage}
                    queue.put_nowait(workflow_evt)
                    session.add_workflow_event(workflow_evt)
                    # 不保存：高频低优先级事件

                # 3. 工具调用 - 立即保存（重要操作）
                tool_calls = evt.get("tool_calls_delta")
                if tool_calls:
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function")
                            if isinstance(fn, dict) and fn.get("name"):
                                detail = None
                                args = fn.get("arguments")
                                try:
                                    if isinstance(args, str):
                                        j = json.loads(args)
                                        if isinstance(j, dict):
                                            keys = list(j.keys())[:3]
                                            kv = [f"{k}={j.get(k)}" for k in keys]
                                            detail = ", ".join(kv)
                                        else:
                                            detail = str(j)[:200]
                                    elif args is not None:
                                        detail = str(args)[:200]
                                except Exception:
                                    detail = None
                                workflow_evt = {"type": "tool_start", "tool": fn.get("name"), "detail": detail, "stage": stage or "planner"}
                                queue.put_nowait(workflow_evt)
                                session.add_workflow_event(workflow_evt)
                                session_manager.save_session(session)  # 工具调用立即保存
            else:
                safe_evt = _safe_event(evt)
                queue.put_nowait(safe_evt)
                # pipeline 阶段事件 - 立即保存（关键节点）
                if evt_type in ("pipeline_stage_start", "pipeline_stage_end"):
                    session.add_workflow_event(safe_evt)
                    session_manager.save_session(session)
                # 工具调用事件 - 保存用于历史回放（包含完整的工具返回内容）
                elif evt_type in ("tool_call_start", "tool_result", "tool_call_end"):
                    session.add_workflow_event(safe_evt)
                    session_manager.save_session(session)  # 立即保存工具事件
                # 监控日志事件 - 保存用于历史回放
                elif evt_type in ("warning", "usage_summary"):
                    session.add_workflow_event(safe_evt)
                    # 不立即保存，等审查完成时一起保存
                # 扫描器事件 - 保存用于历史回放（使历史会话可回放扫描信息）
                elif evt_type in ("scanner_progress", "scanner_issues_summary", "scanner_init", "scanner_performance"):
                    session.add_workflow_event(safe_evt)
                    session_manager.save_session(session)
                # 静态扫描旁路事件 - 保存用于历史回放
                elif evt_type in ("static_scan_start", "static_scan_file_start", "static_scan_file_done", "static_scan_complete"):
                    session.add_workflow_event(safe_evt)
                    # 只在关键节点保存
                    if evt_type in ("static_scan_start", "static_scan_complete"):
                        session_manager.save_session(session)
        except Exception as e:
            print(f"[WARN] Stream callback error: {e}")

    async def run_agent() -> None:
        review_ok = False
        try:
            result = await run_review_async_entry(
                prompt=req.prompt or "",# 此处为前端传递提示词，考虑到任务仅为代码审查，使用固定提示词效果更优
                llm_preference=req.model,
                tool_names=req.tools or default_tool_names(),
                auto_approve=True,
                project_root=req.project_root,
                stream_callback=stream_callback,
                session_id=session_id,  # 传入 session_id 以便 Agent 内部也能感知
                agents=req.agents,
                enable_static_scan=req.enableStaticScan,  # 传递静态扫描开关
            )
            
            # 审查完成后，将结果保存到会话
            session.add_message("assistant", str(result))
            session.metadata.status = "completed"
            session_manager.save_session(session)

            final_content: str
            if isinstance(result, str):
                final_content = result
            else:
                try:
                    final_content = json.dumps(result, ensure_ascii=False, indent=2)
                except Exception:
                    final_content = str(result)

            await queue.put({"type": "final", "content": final_content})
            review_ok = True
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            # 静态扫描属于旁路任务：不阻塞审查完成。
            # 扫描结果可通过 /api/static-scan/issues 或 /api/static-scan/linked 查询。
            accept_stream_events = False
            await queue.put({"type": "done"})

    task = asyncio.create_task(run_agent())

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            while True:
                evt = await queue.get()
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt.get("type") in {"done"}:
                    break
        except asyncio.CancelledError:
            # 客户端断开连接或其他取消信号
            raise
        finally:
            # 确保后台任务被取消
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    print("[WARN] Review task cleanup timeout")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # 避免代理/服务器端缓冲，保证逐片推送
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 运维API端点 ====================

# --- 健康检查与指标 ---

@app.get("/api/health")
async def health_check():
    """服务健康检查。"""
    return HealthAPI.health_check()


@app.get("/api/health/simple")
async def health_simple():
    """简单健康检查（仅返回状态）。"""
    is_healthy = HealthAPI.is_healthy()
    return {"healthy": is_healthy}


@app.get("/api/metrics")
async def get_metrics():
    """获取系统运行指标。"""
    return HealthAPI.get_metrics()


@app.get("/api/providers/status")
async def get_provider_status():
    """获取所有LLM提供商状态。"""
    return HealthAPI.get_provider_status()


@app.get("/api/scanners/status")
def get_scanner_status(language: Optional[str] = None):
    try:
        cache_key = str(language or "__all__")
        now = time.time()
        cached = _scanner_status_cache.get(cache_key)
        if (
            isinstance(cached, dict)
            and (now - float(cached.get("ts", 0.0))) < _SCANNER_STATUS_CACHE_TTL_SECONDS
            and cached.get("data") is not None
        ):
            return cached["data"]

        langs = [language] if language else ScannerRegistry.get_registered_languages()
        languages_info: List[Dict[str, Any]] = []
        for lang in langs:
            infos = ScannerRegistry.get_scanner_info(lang)
            available_count = sum(1 for i in infos if i.get("available"))
            languages_info.append({
                "language": lang,
                "scanners": infos,
                "available_count": available_count,
                "total_count": len(infos),
            })
        data = {"languages": languages_info, "total_languages": len(langs)}
        _scanner_status_cache[cache_key] = {"ts": now, "data": data}
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 配置管理 ---

@app.get("/api/config")
async def get_config():
    """获取当前内核配置。"""
    return ConfigAPI.get_config()


class ConfigUpdate(BaseModel):
    updates: Dict[str, Any]
    persist: bool = True


@app.patch("/api/config")
async def update_config(req: ConfigUpdate):
    """更新配置（支持部分更新）。"""
    try:
        return ConfigAPI.update_config(req.updates, req.persist)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/config/reset")
async def reset_config():
    """重置为默认配置。"""
    return ConfigAPI.reset_config()


@app.get("/api/config/llm")
async def get_llm_config():
    """获取LLM相关配置。"""
    return ConfigAPI.get_llm_config()


@app.get("/api/config/context")
async def get_context_config():
    """获取上下文相关配置。"""
    return ConfigAPI.get_context_config()


@app.get("/api/config/review")
async def get_review_config():
    """获取审查流程配置。"""
    return ConfigAPI.get_review_config()


@app.get("/api/config/fusion")
async def get_fusion_config():
    """获取融合层阈值配置。"""
    return ConfigAPI.get_fusion_thresholds()


# --- 缓存管理 ---

@app.get("/api/cache/stats")
async def get_cache_stats():
    """获取缓存统计信息。"""
    return CacheAPI.get_cache_stats()


@app.get("/api/cache/intent")
async def list_intent_caches():
    """列出所有意图缓存条目。"""
    return CacheAPI.list_intent_caches()


@app.get("/api/cache/intent/{project_name}")
async def api_get_intent_cache(project_name: str):
    """获取指定项目的意图缓存内容。"""
    content = CacheAPI.get_intent_cache(project_name)
    if content is None:
        raise HTTPException(status_code=404, detail="Cache not found")
    return content


class CacheClearRequest(BaseModel):
    project_name: Optional[str] = None


@app.delete("/api/cache/intent")
async def api_clear_intent_cache(req: CacheClearRequest = CacheClearRequest()):
    """清除意图分析缓存。"""
    return CacheAPI.clear_intent_cache(req.project_name)


@app.post("/api/cache/intent/{project_name}/refresh")
async def api_refresh_intent_cache(project_name: str):
    """刷新指定项目的意图缓存。"""
    return CacheAPI.refresh_intent_cache(project_name)


@app.post("/api/intent/analyze_stream")
async def analyze_intent_stream(req: IntentAnalyzeStreamRequest):
    """使用核心 IntentAPI 进行流式意图分析。"""

    async def event_stream() -> AsyncGenerator[str, None]:
        done_sent = False
        try:
            async for evt in IntentAPI.run_intent_analysis_sse(
                req.project_root,
                force_refresh=req.force_refresh,
                model=req.model,
            ):
                etype = evt.get("type")
                payload: Optional[Dict[str, Any]] = None

                if etype == "content":
                    delta = evt.get("delta") or evt.get("content_delta") or ""
                    if not delta:
                        continue
                    payload = {"type": "chunk", "content": delta}
                elif etype == "reasoning":
                    # 处理思考模型的推理内容
                    delta = evt.get("delta") or ""
                    if not delta:
                        continue
                    payload = {"type": "thought", "content": delta}
                elif etype == "progress":
                    msg = evt.get("message") or evt.get("stage")
                    if not msg:
                        continue
                    payload = {"type": "thought", "content": msg}
                elif etype == "final":
                    result = evt.get("result") or {}
                    # 确保 content 是字符串
                    content = result.get("content") if isinstance(result, dict) else result
                    if not isinstance(content, str):
                        content = str(content) if content else ""
                    payload = {"type": "final", "content": content}
                elif etype == "error":
                    payload = {"type": "error", "message": evt.get("message", "unknown error")}
                elif etype == "done":
                    payload = {"type": "done"}
                else:
                    continue

                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if etype == "done":
                    done_sent = True
                    break
        except Exception as e:
            error_payload = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
        finally:
            if not done_sent:
                yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # 避免代理/服务器端缓冲，保证逐片推送
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ExpiredCacheClearRequest(BaseModel):
    max_age_days: int = 30


@app.delete("/api/cache/expired")
async def clear_expired_caches(req: ExpiredCacheClearRequest = ExpiredCacheClearRequest()):
    """清除过期的缓存文件。"""
    return CacheAPI.clear_expired_caches(req.max_age_days)


# ==================== 功能性API端点 ====================

# --- Diff分析 API ---

class DiffRequest(BaseModel):
    project_root: Optional[str] = None
    mode: Optional[str] = None  # working, staged, pr, auto
    base_branch: Optional[str] = None


@app.get("/api/diff/status")
def get_diff_status(project_root: Optional[str] = None):
    """获取当前Diff状态概览。"""
    try:
        return DiffAPI.get_diff_status(project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diff/summary")
def get_diff_summary(project_root: Optional[str] = None, mode: str = "auto"):
    """获取Diff摘要信息。"""
    try:
        return DiffAPI.get_diff_summary(project_root, mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diff/files")
def get_diff_files(project_root: Optional[str] = None, mode: str = "auto"):
    """获取所有变更文件列表。"""
    try:
        return DiffAPI.get_diff_files(project_root, mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diff/units")
def get_review_units(project_root: Optional[str] = None, mode: str = "auto", file_filter: Optional[str] = None):
    """获取审查单元列表（基于规则解析）。"""
    try:
        return DiffAPI.get_review_units(project_root, mode, file_filter)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diff/file/{file_path:path}")
def get_file_diff(file_path: str, project_root: Optional[str] = None, mode: str = "auto"):
    """获取指定文件的Diff详情。"""
    try:
        result = DiffAPI.get_file_diff(file_path, project_root, mode)
        # Don't raise 404, let frontend handle the error message to show debug info
        if "error" in result and result["error"]:
             # Log error for server-side debugging
             print(f"[DiffAPI] Error fetching diff for {file_path} (mode={mode}): {result['error']}")
        return result
    except Exception as e:
        print(f"[DiffAPI] Exception fetching diff for {file_path}: {e}")
        return {"file_path": file_path, "error": str(e)}


@app.post("/api/diff/analyze")
def analyze_diff(req: DiffRequest):
    """分析Diff并返回完整分析结果（组合调用）。"""
    start = time.perf_counter()
    try:
        status = DiffAPI.get_diff_status(req.project_root)
        from Agent.DIFF.git_operations import DiffMode, run_git
        md = DiffMode(req.mode) if req.mode and req.mode != "auto" else DiffMode.AUTO
        files_info = []
        if md == DiffMode.WORKING:
            if _is_running_in_docker():
                out = run_git("status", "--porcelain=v1", "-z", "--untracked-files=no", cwd=req.project_root)
                entries = _parse_git_status_porcelain_z(out)
                for it in entries:
                    if not it.get("y") or it.get("y") == " ":
                        continue
                    files_info.append({
                        "path": it.get("path"),
                        "old_path": it.get("old_path"),
                        "new_path": it.get("new_path"),
                        "display_path": it.get("display_path") or it.get("path"),
                        "language": "unknown",
                        "change_type": it.get("change_type") or "modify",
                        "lines_added": 0,
                        "lines_removed": 0,
                        "tags": [],
                    })
                return {
                    "status": status,
                    "summary": {
                        "summary": "",
                        "mode": md.value,
                        "base_branch": None,
                        "files": [f.get("path") for f in files_info],
                        "file_count": len(files_info),
                        "unit_count": 0,
                        "lines_added": 0,
                        "lines_removed": 0,
                        "error": None,
                    },
                    "files": files_info,
                    "units": [],
                    "detected_mode": md.value,
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                }
            out = run_git("diff", "--name-status", "--diff-filter=ACMRD", cwd=req.project_root)
        elif md == DiffMode.STAGED:
            if _is_running_in_docker():
                out = run_git("status", "--porcelain=v1", "-z", "--untracked-files=no", cwd=req.project_root)
                entries = _parse_git_status_porcelain_z(out)
                for it in entries:
                    if not it.get("x") or it.get("x") == " ":
                        continue
                    files_info.append({
                        "path": it.get("path"),
                        "old_path": it.get("old_path"),
                        "new_path": it.get("new_path"),
                        "display_path": it.get("display_path") or it.get("path"),
                        "language": "unknown",
                        "change_type": it.get("change_type") or "modify",
                        "lines_added": 0,
                        "lines_removed": 0,
                        "tags": [],
                    })
                return {
                    "status": status,
                    "summary": {
                        "summary": "",
                        "mode": md.value,
                        "base_branch": None,
                        "files": [f.get("path") for f in files_info],
                        "file_count": len(files_info),
                        "unit_count": 0,
                        "lines_added": 0,
                        "lines_removed": 0,
                        "error": None,
                    },
                    "files": files_info,
                    "units": [],
                    "detected_mode": md.value,
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                }
            out = run_git("diff", "--cached", "--name-status", "--diff-filter=ACMRD", cwd=req.project_root)
        else:
            ctx = collect_diff_context(mode=md, cwd=req.project_root)
            rev = ctx.review_index or {}
            for fe in rev.get("files", []):
                m = fe.get("metrics", {})
                p = fe.get("path")
                if p:
                    if p.startswith("a/"): p = p[2:]
                    elif p.startswith("b/"): p = p[2:]
                files_info.append({
                    "path": p,
                    "language": fe.get("language", "unknown"),
                    "change_type": fe.get("change_type", "modify"),
                    "lines_added": m.get("added_lines", 0),
                    "lines_removed": m.get("removed_lines", 0),
                    "tags": fe.get("tags", []),
                })
            return {
                "status": status,
                "summary": {
                    "summary": ctx.summary,
                    "mode": ctx.mode.value,
                    "base_branch": ctx.base_branch,
                    "files": ctx.files,
                    "file_count": len(ctx.files),
                    "unit_count": len(ctx.units),
                    "lines_added": 0,
                    "lines_removed": 0,
                    "error": None,
                },
                "files": files_info,
                "units": [],
                "detected_mode": ctx.mode.value,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }
        if md in (DiffMode.WORKING, DiffMode.STAGED):
            lines = out.splitlines()
            for line in lines:
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                st = parts[0]
                st_code = st[:1]
                ch = {
                    "A": "add",
                    "M": "modify",
                    "R": "rename",
                    "C": "copy",
                    "D": "delete",
                }.get(st_code, "modify")

                # rename/copy: `R100\told\tnew` / `C100\told\tnew`
                old_path = None
                new_path = None
                if st_code in ("R", "C") and len(parts) >= 3:
                    old_path = parts[1]
                    new_path = parts[2]
                    p = new_path
                    display_path = f"{old_path} -> {new_path}"
                else:
                    p = parts[1]
                    display_path = p

                files_info.append({
                    "path": p,
                    "old_path": old_path,
                    "new_path": new_path,
                    "display_path": display_path,
                    "language": "unknown",
                    "change_type": ch,
                    "lines_added": 0,
                    "lines_removed": 0,
                    "tags": [],
                })
            return {
                "status": status,
                "summary": {
                    "summary": "",
                    "mode": md.value,
                    "base_branch": None,
                    "files": [f.get("path") for f in files_info],
                    "file_count": len(files_info),
                    "unit_count": 0,
                    "lines_added": 0,
                    "lines_removed": 0,
                    "error": None,
                },
                "files": files_info,
                "units": [],
                "detected_mode": md.value,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ModelAddRequest(BaseModel):
    provider: str
    model_name: str

class ModelDeleteRequest(BaseModel):
    provider: str
    model_name: str

@app.get("/api/models/providers")
async def get_model_providers():
    """获取支持的模型厂商列表。"""
    return {"providers": ModelAPI.get_providers()}


# --- 工具管理 API ---

@app.get("/api/tools/list")
async def list_tools(include_builtin: bool = True, include_custom: bool = True):
    """获取所有可用工具列表。"""
    try:
        return ToolAPI.list_tools(include_builtin, include_custom)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tools/{tool_name}")
async def get_tool_info(tool_name: str):
    """获取指定工具的详细信息。"""
    try:
        result = ToolAPI.get_tool_detail(tool_name)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tools/stats/summary")
async def get_tool_stats():
    """获取工具使用统计。"""
    try:
        return ToolAPI.get_tool_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tools/stats/recent")
async def get_recent_tool_calls(limit: int = 20):
    """获取最近的工具调用记录。"""
    try:
        return {"executions": ToolAPI.get_recent_executions(limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ToolRecord(BaseModel):
    tool_name: str
    success: bool
    duration_ms: float
    error: Optional[str] = None


@app.post("/api/tools/stats/record")
async def record_tool_call(req: ToolRecord):
    """记录工具调用（供内部使用）。"""
    try:
        from Agent.core.api.tools import get_stats_collector
        get_stats_collector().record_execution(
            tool_name=req.tool_name,
            arguments={},
            result=None,
            success=req.success,
            error=req.error,
            duration_ms=req.duration_ms,
        )
        return {"status": "recorded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CustomToolRequest(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    handler_code: Optional[str] = None


@app.post("/api/tools/register")
async def register_custom_tool(req: CustomToolRequest):
    """注册自定义工具（高级功能）。"""
    try:
        # 注意：handler_code 需要在服务端安全执行，这里只做基本校验
        if not req.handler_code:
            raise HTTPException(status_code=400, detail="handler_code is required")
        
        # 创建一个简单的占位处理器（实际应用中需要安全的代码执行机制）
        def placeholder_handler(args: Dict[str, Any]) -> Any:
            return {"message": "Custom tool executed", "args": args}
        
        return ToolAPI.register_custom_tool(
            req.name, req.description, req.parameters, placeholder_handler
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 日志访问 API ---

@app.get("/api/logs/sessions")
async def list_log_sessions(limit: int = 50, offset: int = 0):
    """列出所有日志会话。"""
    try:
        return LogAPI.list_sessions(limit, offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/session/{trace_id}")
async def get_session_log(trace_id: str):
    """获取指定会话的完整日志。"""
    try:
        result = LogAPI.get_session_log(trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Session log not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/session/{trace_id}/human")
async def get_human_readable_log(trace_id: str):
    """获取人类可读格式的日志（Markdown）。"""
    try:
        result = LogAPI.get_session_log(trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Session log not found")
        # 返回 human_log_preview 部分
        return {
            "trace_id": trace_id,
            "content": result.get("human_log_preview", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/session/{trace_id}/api-calls")
async def get_api_calls(trace_id: str):
    """获取指定会话的API调用记录。"""
    try:
        return LogAPI.get_api_calls(trace_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/session/{trace_id}/pipeline")
async def get_pipeline_log(trace_id: str):
    """获取指定会话的流水线日志。"""
    try:
        result = LogAPI.get_session_log(trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Pipeline log not found")
        return {
            "trace_id": trace_id,
            "pipeline_log_path": result.get("pipeline_log_path"),
            "events": result.get("events", []),
            "event_count": result.get("event_count", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/stats")
async def get_log_stats():
    """获取日志统计信息。"""
    try:
        return LogAPI.get_log_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LogCleanupRequest(BaseModel):
    max_age_days: int = 30


@app.delete("/api/logs/old")
async def delete_old_logs(req: LogCleanupRequest = LogCleanupRequest()):
    """删除旧日志文件。"""
    try:
        return LogAPI.delete_old_logs(req.max_age_days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/export/{trace_id}")
async def export_session_log(trace_id: str, format: str = "json"):
    """导出会话日志（支持json/markdown格式）。"""
    try:
        result = LogAPI.get_session_log(trace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Session log not found")
        
        if format == "markdown":
            return {
                "trace_id": trace_id,
                "format": "markdown",
                "content": result.get("human_log_preview", ""),
            }
        else:
            return {
                "trace_id": trace_id,
                "format": "json",
                "content": result,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 项目信息 API ---

@app.get("/api/project/info")
def get_project_info(project_root: Optional[str] = None):
    """获取项目基本信息。"""
    try:
        return ProjectAPI.get_project_info(project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/tree")
def get_file_tree(
    project_root: Optional[str] = None,
    max_depth: int = 3,
    include_hidden: bool = False
):
    """获取项目文件树结构。"""
    try:
        return ProjectAPI.get_file_tree(project_root, max_depth, include_hidden)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/readme")
def get_readme_content(project_root: Optional[str] = None):
    """获取项目README内容。"""
    try:
        result = ProjectAPI.get_readme_content(project_root)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/dependencies")
def get_dependencies(project_root: Optional[str] = None):
    """获取项目依赖信息。"""
    try:
        return ProjectAPI.get_dependencies(project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/git")
def get_git_info(project_root: Optional[str] = None):
    """获取项目Git信息。"""
    try:
        return ProjectAPI.get_git_info(project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class FileSearchRequest(BaseModel):
    pattern: str
    project_root: Optional[str] = None
    max_results: int = 100


@app.post("/api/project/search")
def search_files(req: FileSearchRequest):
    """在项目中搜索文件。"""
    try:
        return ProjectAPI.search_files(
            query=req.pattern,
            project_root=req.project_root,
            max_results=req.max_results
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/project/languages")
def get_project_languages(background_tasks: BackgroundTasks, project_root: Optional[str] = None):
    """获取项目使用的编程语言统计。"""
    try:
        # 使用 get_project_info 获取语言信息
        info = ProjectAPI.get_project_info(project_root)
        background_tasks.add_task(
            _prewarm_scanner_availability_for_languages,
            info.get("detected_languages", []),
        )
        return {
            "languages": info.get("detected_languages", []),
            "project_name": info.get("project_name"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 增强会话管理 API ---

@app.get("/api/sessions/stats")
async def get_all_sessions_stats():
    """获取所有会话的统计信息。"""
    try:
        return SessionAPI.get_session_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, limit: Optional[int] = None, role: Optional[str] = None):
    """获取会话消息历史。"""
    try:
        result = SessionAPI.get_session_messages(session_id, limit, role)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, format: str = "json"):
    """导出会话数据。"""
    try:
        result = SessionAPI.export_session(session_id, format)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SessionUpdateRequest(BaseModel):
    metadata: Optional[Dict[str, Any]] = None
    project_root: Optional[str] = None


@app.patch("/api/sessions/{session_id}")
async def update_session_metadata(session_id: str, req: SessionUpdateRequest):
    """更新会话元数据。"""
    try:
        # 提取更新参数
        name = req.metadata.get("name") if req.metadata else None
        status = req.metadata.get("status") if req.metadata else None
        tags = req.metadata.get("tags") if req.metadata else None
        
        result = SessionAPI.update_session(
            session_id=session_id,
            name=name,
            status=status,
            tags=tags
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ArchiveRequest(BaseModel):
    max_age_days: int = 30


@app.post("/api/sessions/archive")
async def archive_old_sessions(req: ArchiveRequest = ArchiveRequest()):
    """归档旧会话。"""
    try:
        return SessionAPI.archive_old_sessions(req.max_age_days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/search")
async def search_sessions(
    query: Optional[str] = None,
    project_root: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
):
    """搜索会话。"""
    try:
        # 使用 list_sessions 并进行过滤
        result = SessionAPI.list_sessions(
            status=status,
            project_root=project_root,
            limit=limit
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 意图分析API端点 ====================


@app.get("/api/intent/status")
def get_intent_status(project_root: str):
    """检查指定项目的意图缓存状态。
    
    Args:
        project_root: 项目根路径
        
    Returns:
        IntentStatusResponse: 缓存状态信息
    """
    try:
        return IntentAPI.check_intent_status(project_root)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/intent/{project_name}")
def get_intent_cache(project_name: str, project_root: Optional[str] = None):
    """获取项目的意图分析内容。
    
    Args:
        project_name: 项目名称
        project_root: 可选的项目根路径（如果提供则使用此路径）
        
    Returns:
        Dict: 缓存内容
    """
    try:
        # 如果提供了project_root，使用它；否则尝试从project_name构建
        if project_root:
            result = IntentAPI.get_intent_cache(project_root)
        else:
            # 尝试从缓存目录直接读取
            cache_path = IntentAPI._get_cache_path(project_name)
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result = {
                    "found": True,
                    "project_name": project_name,
                    "content": data.get("content", ""),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "source": data.get("source"),
                }
            else:
                result = {
                    "found": False,
                    "project_name": project_name,
                    "content": None,
                }
        
        if not result.get("found"):
            raise HTTPException(status_code=404, detail="Intent cache not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/intent/analyze")
async def analyze_intent(req: IntentAnalyzeRequest):
    """触发意图分析（SSE流式返回）。
    
    Args:
        req: IntentAnalyzeRequest包含project_root和force_refresh
        
    Returns:
        StreamingResponse: SSE事件流
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for evt in IntentAPI.run_intent_analysis_sse(
                project_root=req.project_root,
                force_refresh=req.force_refresh,
            ):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt.get("type") == "done":
                    break
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # 避免代理/服务器端缓冲，保证逐片推送
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.put("/api/intent/{project_name}")
async def update_intent_content(project_name: str, req: IntentUpdateRequest, project_root: Optional[str] = None):
    """更新意图分析内容。
    
    Args:
        project_name: 项目名称
        req: IntentUpdateRequest包含新的content
        project_root: 可选的项目根路径
        
    Returns:
        Dict: 更新结果
    """
    try:
        # 如果提供了project_root，使用它
        if project_root:
            result = IntentAPI.update_intent_cache(project_root, req.content)
        else:
            # 尝试从缓存中获取原始project_root
            cache_path = IntentAPI._get_cache_path(project_name)
            if cache_path.exists():
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                original_root = data.get("project_root", "")
                if original_root:
                    result = IntentAPI.update_intent_cache(original_root, req.content)
                else:
                    raise HTTPException(status_code=400, detail="Cannot determine project root")
            else:
                raise HTTPException(status_code=404, detail="Intent cache not found")
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 规则自成长API端点 ====================

class RuleGrowthCleanupRequest(BaseModel):
    max_age_days: int = 30
    max_count: Optional[int] = None


@app.get("/api/rule-growth/summary")
async def get_rule_growth_summary():
    """获取规则冲突汇总统计。"""
    try:
        return RuleGrowthAPI.get_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rule-growth/suggestions")
async def get_rule_growth_suggestions():
    """获取规则优化建议。"""
    try:
        return RuleGrowthAPI.get_rule_suggestions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rule-growth/cleanup")
async def cleanup_rule_growth_conflicts(req: RuleGrowthCleanupRequest = RuleGrowthCleanupRequest()):
    """清理旧的冲突记录。"""
    try:
        return RuleGrowthAPI.cleanup_old_conflicts(
            max_age_days=req.max_age_days,
            max_count=req.max_count
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rule-growth/enhanced-suggestions")
async def get_enhanced_suggestions():
    """获取增强的规则建议（可应用规则和参考提示）。"""
    try:
        return RuleGrowthAPI.get_enhanced_suggestions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RuleApplyRequest(BaseModel):
    rule_id: str


@app.post("/api/rule-growth/apply")
async def apply_rule(req: RuleApplyRequest):
    """应用规则到配置。"""
    try:
        result = RuleGrowthAPI.apply_rule(req.rule_id)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rule-growth/learned-rules")
async def get_learned_rules():
    """获取所有学习到的规则。"""
    try:
        return RuleGrowthAPI.get_learned_rules()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RuleRemoveRequest(BaseModel):
    rule_id: str


@app.post("/api/rule-growth/remove")
async def remove_learned_rule(req: RuleRemoveRequest):
    """移除学习到的规则。"""
    try:
        result = RuleGrowthAPI.remove_learned_rule(req.rule_id)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PromoteHintRequest(BaseModel):
    """提升参考提示为规则的请求。
    
    **Feature: rule-growth-layout-optimization**
    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    language: str
    tags: list[str]
    suggested_context_level: str
    sample_count: int = 0
    consistency: float = 0.0
    conflict_type: str = ""


@app.post("/api/rule-growth/promote-hint")
async def promote_hint_to_rule(req: PromoteHintRequest):
    """将参考提示手动提升为规则。
    
    **Feature: rule-growth-layout-optimization**
    **Validates: Requirements 5.3, 5.4**
    
    即使提示不满足自动应用条件，开发者也可以手动提升为规则。
    """
    try:
        result = RuleGrowthAPI.promote_hint(
            language=req.language,
            tags=req.tags,
            suggested_context_level=req.suggested_context_level,
            sample_count=req.sample_count,
            consistency=req.consistency,
            conflict_type=req.conflict_type
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Git History API ---

from Agent.DIFF.git_history import get_commit_history, get_current_branch, get_branch_graph

class GitCommitsRequest(BaseModel):
    project_root: str
    limit: int = 20
    skip: int = 0  # 跳过的提交数量，用于分页
    branch: Optional[str] = None

@app.post("/api/git/commits")
def get_git_commits_api(req: GitCommitsRequest):
    """获取 Git 提交历史"""
    start = time.perf_counter()
    try:
        project_root = (req.project_root or "").strip()
        if not project_root:
            return {
                "success": False,
                "error": "project_root is required",
                "commits": [],
                "project_root": project_root,
                "limit": None,
                "skip": None,
                "elapsed_ms": int((time.perf_counter() - start) * 1000),
            }

        limit = int(req.limit or 20)
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50

        skip = int(req.skip or 0)
        if skip < 0:
            skip = 0
        if skip > 20000:
            skip = 20000

        commits = get_commit_history(
            cwd=project_root,
            limit=limit,
            skip=skip,
            branch=req.branch
        )
        return {
            "success": True,
            "commits": commits,
            "project_root": project_root,
            "limit": limit,
            "skip": skip,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "commits": [],
            "project_root": (req.project_root or "").strip(),
            "limit": int(req.limit or 20) if req is not None else None,
            "skip": int(req.skip or 0) if req is not None else None,
            "elapsed_ms": int((time.perf_counter() - start) * 1000),
        }


@app.get("/api/git/branch")
def get_current_git_branch_api(project_root: str):
    """获取当前分支"""
    try:
        branch = get_current_branch(cwd=project_root)
        return {"success": True, "branch": branch}
    except Exception as e:
        return {"success": False, "error": str(e), "branch": "unknown"}

@app.post("/api/git/graph")
def get_git_graph_api(req: GitCommitsRequest):
    """获取分支图数据"""
    try:
        project_root = (req.project_root or "").strip()
        if not project_root:
            return {"success": False, "error": "project_root is required"}

        limit = int(req.limit or 20)
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50

        graph_data = get_branch_graph(
            cwd=project_root,
            limit=limit
        )
        return {"success": True, **graph_data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_wellknown():
    return JSONResponse(content={}, media_type="application/json")


# 挂载静态文件（必须放在最后，否则会覆盖 API 路由）
app.mount("/", StaticFiles(directory="UI/static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=54321)
