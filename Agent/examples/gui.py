"""用于手动测试 Agent 的简易 GUI。"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import queue
from pathlib import Path
from typing import Any, Dict, List, cast
import json

import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.scrolledtext as scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.widgets.scrolled import ScrolledFrame
from ttkbootstrap.dialogs import Messagebox

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _inject_venv_sitepackages() -> None:
    candidates = [
        ROOT / "venv" / "Lib" / "site-packages",
    ]
    candidates.extend((ROOT / "venv" / "lib").glob("python*/site-packages"))
    for path in candidates:
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))

_inject_venv_sitepackages()

load_dotenv()

from Agent.agents import DEFAULT_USER_PROMPT
from Agent.ui.service import run_review
from Agent.core.adapter.llm_adapter import KimiAdapter, ToolDefinition
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import (
    collect_diff_context,
)
from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
)
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.tool.registry import (
    default_tool_names,
    get_tool_functions,
    get_tool_schemas,
    list_tool_names,
)
from Agent.ui.service import UsageAggregator


GLM_KEY_PRESENT = bool(os.getenv("GLM_API_KEY"))
MOONSHOT_KEY_PRESENT = bool(os.getenv("MOONSHOT_API_KEY"))
BAILIAN_KEY_PRESENT = bool(os.getenv("BAILIAN_API_KEY"))


def create_llm_client(preference: str = "auto") -> tuple[BaseLLMClient, str]:
    glm_key = os.getenv("GLM_API_KEY")
    if preference in {"glm", "auto"} and glm_key:
        try:
            return (
                GLMLLMClient(
                    model=os.getenv("GLM_MODEL", "GLM-4.6"),
                    api_key=glm_key,
                ),
                "glm",
            )
        except Exception as exc:
            print(f"[警告] GLM 客户端初始化失败：{exc}")

    bailian_key = os.getenv("BAILIAN_API_KEY")
    if preference in {"bailian", "auto"} and bailian_key:
        try:
            return (
                BailianLLMClient(
                    model=os.getenv("BAILIAN_MODEL", "qwen-max"),
                    api_key=bailian_key,
                    base_url=os.getenv("BAILIAN_BASE_URL"),
                ),
                "bailian",
            )
        except Exception as exc:
            print(f"[警告] Bailian 客户端初始化失败：{exc}")

    if preference in {"moonshot", "auto"}:
        try:
            return (
                MoonshotLLMClient(
                    model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                ),
                "moonshot",
            )
        except (ValueError, RuntimeError) as exc:
            print(f"[警告] Moonshot 客户端初始化失败：{exc}")

    if preference == "glm":
        raise RuntimeError("GLM 模式被选择，但 GLM 客户端不可用。")
    if preference == "bailian":
        raise RuntimeError("Bailian 模式被选择，但 Bailian 客户端不可用。")
    if preference == "moonshot":
        raise RuntimeError("Moonshot 模式被选择，但 Moonshot 客户端不可用。")
    return MockMoonshotClient(), "mock"


def run_agent(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: str | None = None,
    stream_callback=None,
    tool_approver=None,
) -> str:
    # 统一走服务层以避免出现多个事件循环
    return run_review(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
    )


class MarkdownViewer:
    """Lightweight markdown-aware text viewer for Tk."""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        body_bg: str = "#ffffff",  # Clean White
        body_fg: str = "#333333",  # Dark Gray
    ) -> None:
        self._buffer: str = ""
        self.text = scrolledtext.ScrolledText(
            parent,
            height=16,
            wrap=tk.WORD,
            font=("Microsoft YaHei UI", 11),
            background=body_bg,
            foreground=body_fg,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            insertbackground=body_fg,
            padx=30,
            pady=30,
        )
        self._configure_tags()
        self.text.configure(state=tk.DISABLED)

    def clear(self) -> None:
        self._buffer = ""
        self._render()

    def set_content(self, content: str) -> None:
        self._buffer = content or ""
        self._render()

    def append(self, text: str) -> None:
        if not text:
            return
        self._buffer += text
        self._render()

    def _configure_tags(self) -> None:
        # Modern Document Style (Not Code Editor Style)
        # 针对中文优化字体
        self.text.tag_config(
            "body",
            font=("Microsoft YaHei UI", 11),
            foreground="#333333",
            spacing3=8,
        )
        self.text.tag_config(
            "h1",
            font=("Microsoft YaHei UI", 22, "bold"),
            foreground="#1a1a1a",  # Near Black
            spacing1=24,
            spacing3=12,
        )
        self.text.tag_config(
            "h2",
            font=("Microsoft YaHei UI", 18, "bold"),
            foreground="#2c2c2c",  # Dark Gray
            spacing1=20,
            spacing3=10,
        )
        self.text.tag_config(
            "h3",
            font=("Microsoft YaHei UI", 14, "bold"),
            foreground="#444444",
            spacing1=16,
            spacing3=8,
        )
        self.text.tag_config(
            "bullet",
            font=("Microsoft YaHei UI", 11),
            foreground="#333333",
            lmargin1=20,
            lmargin2=36,
            spacing3=6,
        )
        self.text.tag_config(
            "codeblock",
            font=("Consolas", 10),
            background="#f8f9fa",  # Very Light Gray
            foreground="#24292e",  # GitHub Dark Text
            lmargin1=15,
            lmargin2=15,
            spacing1=10,
            spacing3=10,
        )
        self.text.tag_config(
            "inline_code",
            font=("Consolas", 10, "bold"),
            background="#f1f3f5",
            foreground="#e03131",  # Reddish accent for code
            relief=tk.FLAT,
            borderwidth=0,
        )

    def _render(self) -> None:
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self._insert_markdown(self._buffer)
        self.text.configure(state=tk.DISABLED)
        self.text.see(tk.END)

    def _insert_markdown(self, content: str) -> None:
        in_code_block = False
        for raw_line in content.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                self.text.insert(tk.END, line + "\n", ("codeblock",))
                continue

            if not stripped:
                self.text.insert(tk.END, "\n")
                continue

            heading_level = self._heading_level(stripped)
            if heading_level:
                tag = f"h{heading_level}"
                heading_text = stripped.lstrip("#").strip()
                self.text.insert(tk.END, heading_text + "\n", (tag,))
                continue

            if self._is_list_item(stripped):
                bullet_text = stripped.lstrip("-*•0123456789. ").strip()
                self.text.insert(tk.END, f"• {bullet_text}\n", ("bullet",))
                continue

            self._insert_inline(line + "\n")

    def _insert_inline(self, line: str) -> None:
        parts = line.split("`")
        for idx, part in enumerate(parts):
            if not part and idx == len(parts) - 1:
                continue
            tag = "inline_code" if idx % 2 else "body"
            self.text.insert(tk.END, part, (tag,))

    @staticmethod
    def _heading_level(text: str) -> int:
        if text.startswith("###"):
            return 3
        if text.startswith("##"):
            return 2
        if text.startswith("#"):
            return 1
        return 0

    @staticmethod
    def _is_list_item(text: str) -> bool:
        if text.startswith(("-", "*", "•")):
            return True
        if text and text[0].isdigit():
            if len(text) > 1 and text[1] == ".":
                return True
            if len(text) > 2 and text[1].isdigit() and text[2] == ".":
                return True
        return False


def main() -> None:
    # === 1. 初始化 (Clean & Premium) ===
    # 使用 litera 主题，提供清爽的白色底板
    root = ttk.Window(themename="litera")
    root.title("智能代码审查助手")
    root.geometry("1300x850")

    # === 2. 视觉样式定义 (Premium SaaS 风格) ===
    style = ttk.Style()
    
    # 调色板 - 高级灰与纯白
    COLORS = {
        "sidebar_bg": "#f9fafb",   # 极浅的灰，接近白，但有层次
        "content_bg": "#ffffff",   # 纯白内容区
        "text_primary": "#111827", # 深色主标题 (Tailwind Gray 900)
        "text_secondary": "#4b5563", # 次要文字 (Tailwind Gray 600)
        "text_muted": "#9ca3af",   # 弱化文字
        "accent": "#000000",       # 纯黑强调色，高级感
        "border": "#e5e7eb",       # 极细边框
        "success": "#10b981",      # 绿色状态
        "warning": "#f59e0b",      # 黄色状态
        "error": "#ef4444",        # 红色状态
    }

    # 字体配置 (优先使用微软雅黑)
    base_font = ("Microsoft YaHei UI", 10)
    heading_font = ("Microsoft YaHei UI", 16, "bold")
    subheading_font = ("Microsoft YaHei UI", 9, "bold")

    style.configure(".", font=base_font)
    style.configure("TLabel", foreground=COLORS["text_primary"])
    style.configure("TButton", font=("Microsoft YaHei UI", 10, "bold"))
    
    # 侧边栏样式
    style.configure("Sidebar.TFrame", background=COLORS["sidebar_bg"])
    style.configure("Sidebar.TLabel", background=COLORS["sidebar_bg"], foreground=COLORS["text_secondary"])
    style.configure("SidebarTitle.TLabel", background=COLORS["sidebar_bg"], foreground=COLORS["text_primary"], font=("Microsoft YaHei UI", 14, "bold"))
    style.configure("SidebarHeader.TLabel", background=COLORS["sidebar_bg"], foreground=COLORS["text_muted"], font=("Microsoft YaHei UI", 9, "bold"))
    
    # 分割线
    style.configure("Horizontal.TSeparator", background=COLORS["border"])

    # 内容区样式
    style.configure("Content.TFrame", background=COLORS["content_bg"])
    
    # 无边框分组容器
    style.configure("Group.TLabelframe", background=COLORS["sidebar_bg"], bordercolor=COLORS["sidebar_bg"], relief=tk.FLAT)
    style.configure("Group.TLabelframe.Label", background=COLORS["sidebar_bg"], foreground=COLORS["text_primary"], font=("Microsoft YaHei UI", 10, "bold"))

    # === 3. 界面布局 (Fixed Sidebar + Spacious Content) ===
    
    # 主容器
    main_container = ttk.Frame(root)
    main_container.pack(fill=BOTH, expand=True)

    # --- 左侧：控制面板 (Sidebar) ---
    sidebar = ttk.Frame(main_container, style="Sidebar.TFrame", width=340, padding=30)
    sidebar.pack(side=LEFT, fill=Y)
    sidebar.pack_propagate(False) # 固定宽度

    # 1. 品牌标题
    branding_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
    branding_frame.pack(fill=X, pady=(0, 25))
    ttk.Label(branding_frame, text="代码审查助手", style="SidebarTitle.TLabel").pack(anchor=W)
    
    ttk.Separator(sidebar, orient=HORIZONTAL).pack(fill=X, pady=(0, 25))

    # 2. 项目配置
    ttk.Label(sidebar, text="配置", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 10))
    
    # 项目路径
    project_var = tk.StringVar(value="")
    p_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
    p_frame.pack(fill=X, pady=(0, 15))
    
    p_entry = ttk.Entry(p_frame, textvariable=project_var, bootstyle="secondary")
    p_entry.pack(side=LEFT, fill=X, expand=True)
    
    def choose_root():
        p = filedialog.askdirectory()
        if p: project_var.set(p)
    ttk.Button(p_frame, text="...", command=choose_root, bootstyle="secondary-outline", width=3).pack(side=RIGHT, padx=(8, 0))

    # 模型选择
    model_var = tk.StringVar(value="auto")
    llm_options = ["auto"]
    if GLM_KEY_PRESENT: llm_options.append("glm")
    if BAILIAN_KEY_PRESENT: llm_options.append("bailian")
    if MOONSHOT_KEY_PRESENT: llm_options.append("moonshot")
    llm_options.append("mock")
    
    # 使用 Labelframe 包装 Combobox 以增加标签感
    ttk.Combobox(sidebar, textvariable=model_var, values=llm_options, state="readonly", bootstyle="secondary").pack(fill=X, pady=(0, 25))

    ttk.Separator(sidebar, orient=HORIZONTAL).pack(fill=X, pady=(0, 25))

    # 3. 工具与指令
    ttk.Label(sidebar, text="策略", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 10))

    # 工具列表 (嵌入式滚动区域)
    tools_frame = ttk.Frame(sidebar, style="Sidebar.TFrame", height=150)
    tools_frame.pack(fill=X, pady=(0, 15))
    tools_frame.pack_propagate(False) # 限制高度
    
    tools_scroll = ScrolledFrame(tools_frame, autohide=True, width=300) 
    tools_scroll.pack(fill=BOTH, expand=True)
    
    tool_vars: Dict[str, tk.BooleanVar] = {}
    for name in list_tool_names():
        var = tk.BooleanVar(value=name in default_tool_names())
        tool_vars[name] = var
        ttk.Checkbutton(tools_scroll, text=name, variable=var, bootstyle="secondary").pack(anchor=W, pady=4)

    # 4. 回退监控 (Fallback Monitor)
    fallback_frame = ttk.Labelframe(sidebar, text="监控", style="Group.TLabelframe", padding=10)
    fallback_frame.pack(fill=X, pady=(0, 15))
    
    fb_status_lbl = ttk.Label(fallback_frame, text="等待运行...", bootstyle="secondary", font=("Microsoft YaHei UI", 9))
    fb_status_lbl.pack(anchor=W)
    
    fb_detail_lbl = ttk.Label(fallback_frame, text="暂无异常告警", bootstyle="secondary", font=("Microsoft YaHei UI", 8), wraplength=280, justify=tk.LEFT)
    fb_detail_lbl.pack(anchor=W, pady=(5, 0))

    # 审查指令编辑器
    prompt_content = [DEFAULT_USER_PROMPT]
    def open_prompt_editor():
        top = ttk.Toplevel(title="编辑审查指令")
        top.geometry("800x600")
        
        # 弹窗样式
        bg_color = "#ffffff"
        top.configure(background=bg_color)
        
        frame = ttk.Frame(top, padding=30)
        frame.pack(fill=BOTH, expand=True)
        
        ttk.Label(frame, text="自定义审查指令 (Prompt)", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor=W, pady=(0, 15))
        
        txt = scrolledtext.ScrolledText(
            frame, font=("Microsoft YaHei UI", 11), 
            padx=15, pady=15, 
            relief=tk.FLAT, borderwidth=1,
            bg="#f9fafb" # 浅灰背景编辑器
        )
        txt.insert("1.0", prompt_content[0])
        txt.pack(fill=BOTH, expand=True, pady=(0, 20))
        
        def save():
            prompt_content[0] = txt.get("1.0", tk.END)
            top.destroy()
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=X)
        ttk.Button(btn_frame, text="保存修改", command=save, bootstyle="dark", width=15).pack(side=RIGHT)
        ttk.Button(btn_frame, text="取消", command=top.destroy, bootstyle="secondary-outline", width=10).pack(side=RIGHT, padx=10)

    ttk.Button(sidebar, text="自定义审查指令...", command=open_prompt_editor, bootstyle="secondary-outline").pack(fill=X, pady=(0, 15))

    # 自动批准
    auto_approve_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(sidebar, text="自动执行工具 (免确认)", variable=auto_approve_var, bootstyle="round-toggle").pack(anchor=W)

    # 底部：启动按钮
    # 使用 pack(side=BOTTOM) 将其推到底部
    sidebar_bottom = ttk.Frame(sidebar, style="Sidebar.TFrame")
    sidebar_bottom.pack(side=BOTTOM, fill=X)
    
    ttk.Separator(sidebar, orient=HORIZONTAL).pack(side=BOTTOM, fill=X, pady=(20, 0)) # 分割线在按钮上方
    
    # 4. 启动按钮 (Big Black Button)
    run_btn = ttk.Button(sidebar_bottom, text="开始审查", bootstyle="dark", padding=(0, 15))
    run_btn.pack(fill=X, pady=(20, 0))


    # --- 右侧：内容工作台 (Content) ---
    content_area = ttk.Frame(main_container, style="Content.TFrame", padding=40)
    content_area.pack(side=RIGHT, fill=BOTH, expand=True)

    # 顶部状态栏
    status_bar = ttk.Frame(content_area, style="Content.TFrame")
    status_bar.pack(fill=X, pady=(0, 30))
    
    # 左侧：当前视图标题 - 移除静态标题，让内容更纯粹
    # ttk.Label(status_bar, text="审查报告", font=("Microsoft YaHei UI", 18, "bold"), background=COLORS["content_bg"]).pack(side=LEFT)
    
    # 右侧：状态指示器 (Canvas Dot + Text)
    status_indicator_frame = ttk.Frame(status_bar, style="Content.TFrame")
    status_indicator_frame.pack(side=RIGHT)
    
    # 状态点绘制
    status_canvas = tk.Canvas(status_indicator_frame, width=12, height=12, bg=COLORS["content_bg"], highlightthickness=0)
    status_dot = status_canvas.create_oval(2, 2, 10, 10, fill=COLORS["success"], outline="")
    status_canvas.pack(side=LEFT, padx=(0, 8))
    
    status_text = ttk.Label(status_indicator_frame, text="系统就绪", font=("Microsoft YaHei UI", 10), background=COLORS["content_bg"], foreground=COLORS["text_secondary"])
    status_text.pack(side=LEFT)
    
    # Token 计数
    token_lbl = ttk.Label(status_indicator_frame, text="", font=("Microsoft YaHei UI", 10), background=COLORS["content_bg"], foreground=COLORS["text_muted"])
    token_lbl.pack(side=LEFT, padx=(15, 0))

    # 结果展示区
    result_viewer = MarkdownViewer(content_area, body_bg=COLORS["content_bg"], body_fg=COLORS["text_primary"])
    result_viewer.text.pack(fill=BOTH, expand=True)
    
    # 欢迎语
    result_viewer.set_content("")


    # === 4. 业务逻辑集成 ===
    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    is_running = False
    fallback_seen = False
    usage_agg = UsageAggregator()

    def update_status(state: str, msg: str):
        # state: idle, busy, error
        color_map = {
            "idle": COLORS["success"],   # Green
            "busy": COLORS["warning"],   # Yellow/Orange
            "error": COLORS["error"]     # Red
        }
        status_canvas.itemconfig(status_dot, fill=color_map.get(state, COLORS["text_muted"]))
        status_text.configure(text=msg)

    def on_run_click(event: tk.Event | None = None) -> None:
        nonlocal is_running, fallback_seen
        if is_running: return

        selected_tools = [name for name, var in tool_vars.items() if var.get()]
        if not selected_tools:
            Messagebox.show_warning("请至少选择一个工具。", parent=root)
            return
        
        prompt = prompt_content[0].strip()
        if not prompt:
            Messagebox.show_warning("审查指令不能为空。", parent=root)
            return

        # UI Reset
        result_viewer.clear()
        result_viewer.append("# 正在初始化审查任务...\n\n")
        run_btn.configure(state=tk.DISABLED, text="任务执行中...")
        update_status("busy", "正在运行...")
        token_lbl.configure(text="")
        fallback_seen = False
        fb_status_lbl.configure(text="运行中...", bootstyle="secondary")
        fb_detail_lbl.configure(text="正在监控系统回退事件")
        
        is_running = True
        usage_agg.reset()

        threading.Thread(
            target=_run_agent_thread,
            args=(prompt, model_var.get(), selected_tools, auto_approve_var.get(), project_var.get() or None),
            daemon=True
        ).start()

    def _run_agent_thread(prompt, llm_pref, tools, auto, proj):
        try:
            # 确保 Project Root 存在
            if proj and not os.path.isdir(proj):
                 event_queue.put({"type": "error", "error": f"无效的项目路径: {proj}"})
                 return

            # LLM Init
            try:
                llm_client, model_name = create_llm_client(llm_pref)
            except Exception as e:
                event_queue.put({"type": "error", "error": f"模型初始化失败: {str(e)}"})
                return

            # Stream Callback
            def stream_handler(evt):
                # evt is a dict from service.py
                etype = evt.get("type")
                
                if etype == "delta":
                    # Content stream
                    content = evt.get("content_delta", "")
                    if content:
                        event_queue.put({"type": "stream", "content": content})
                
                elif etype == "warning":
                    # Fallback event
                    event_queue.put({"type": "fallback", "data": evt})
                
                elif etype == "usage_summary":
                    # Usage update
                    event_queue.put({"type": "usage", "data": evt})

            # Approval Callback
            def approval_handler(calls):
                approved = []
                for call in calls:
                    q = queue.Queue()
                    event_queue.put({"type": "approval", "call": call, "q": q})
                    if q.get():
                        approved.append(call)
                return approved

            # Run
            final_res = run_agent(
                prompt=prompt,
                llm_preference=model_name,
                tool_names=tools,
                auto_approve=auto,
                project_root=proj,
                stream_callback=stream_handler,
                tool_approver=approval_handler
            )
            event_queue.put({"type": "done", "result": final_res})

        except Exception as e:
            event_queue.put({"type": "error", "error": str(e)})

    def process_queue():
        nonlocal is_running, fallback_seen
        try:
            while True:
                ev = event_queue.get_nowait()
                etype = ev["type"]
                
                if etype == "stream":
                    result_viewer.append(ev["content"])
                
                elif etype == "fallback":
                    data = ev["data"]
                    summary = data.get("fallback_summary") or {}
                    total = summary.get("total")
                    by_key = summary.get("by_key") or summary.get("byKey") or {}
                    msg = data.get("message", "发现回退")
                    fallback_seen = True
                    fb_status_lbl.configure(text=(f"回退 {total} 次" if total else "发现回退"), bootstyle="warning")
                    if by_key:
                        lines = [f"{k}: {v}" for k, v in by_key.items()]
                        fb_detail_lbl.configure(text="\n".join(lines))
                    else:
                        fb_detail_lbl.configure(text=msg)
                
                elif etype == "usage":
                    data = ev["data"]
                    session_usage = data.get("session_usage", {})
                    total = session_usage.get("total", 0)
                    token_lbl.configure(text=f"Tokens: {total}")

                elif etype == "approval":
                    call = ev["call"]
                    q = ev["q"]
                    name = call.get("name", "unknown")
                    args = call.get("arguments", "{}")
                    msg = f"允许执行工具调用吗？\n\n工具: {name}\n参数: {args}"
                    ans = Messagebox.yesno(msg, "工具执行确认", parent=root)
                    q.put(ans == "Yes")
                
                elif etype == "done":
                    result_viewer.append("\n\n---\n**审查任务完成**")
                    is_running = False
                    run_btn.configure(state=tk.NORMAL, text="开始审查任务")
                    update_status("idle", "任务完成")
                    if not fallback_seen:
                        fb_status_lbl.configure(text="未触发回退", bootstyle="success")
                        fb_detail_lbl.configure(text="本次运行未检测到回退路径")
                
                elif etype == "error":
                    result_viewer.append(f"\n\n**错误**: {ev['error']}")
                    is_running = False
                    run_btn.configure(state=tk.NORMAL, text="重试任务")
                    update_status("error", "发生错误")
                    
        except queue.Empty:
            pass
        root.after(50, process_queue)

    run_btn.configure(command=on_run_click)
    root.bind("<Control-Return>", on_run_click)
    root.after(100, process_queue)
    root.place_window_center()
    root.mainloop()

if __name__ == "__main__":
    main()
