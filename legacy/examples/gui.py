"""用于手动测试 Agent 的简易 GUI。"""

# 此模块仅为前期内核快速开发使用，后续迁移到前端中测试

from __future__ import annotations

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
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y, HORIZONTAL, VERTICAL, W, E, BOTTOM, N, S
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
from Agent.core.api import (
    available_llm_options,
    available_tools,
    run_review_sync,
)


def run_agent(
    prompt: str,
    llm_preference: str,
    planner_llm_preference: str | None,
    tool_names: List[str],
    auto_approve: bool,
    project_root: str | None = None,
    stream_callback=None,
    tool_approver=None,
) -> str:
    """统一走内核接口，避免 GUI 触碰底层实现。"""

    return run_review_sync(
        prompt=prompt,
        llm_preference=llm_preference,
        planner_llm_preference=planner_llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
    )


class CollapsibleSection:
    """可折叠容器：标题常显，内容区可展开/收起。"""

    def __init__(self, parent: tk.Widget, title: str, *, collapsed: bool = True) -> None:
        self.frame = ttk.Frame(parent, style="Content.TFrame")
        self.header = ttk.Frame(self.frame, style="Content.TFrame")
        self.header.pack(fill=X, pady=(0, 6))
        self._collapsed = collapsed
        self._title = title
        self.toggle_btn = ttk.Button(
            self.header,
            text=self._title + (" (展开)" if collapsed else " (收起)"),
            command=self.toggle,
            bootstyle="secondary-outline",
            width=30,
        )
        self.toggle_btn.pack(side=LEFT)
        self.body = ttk.Frame(self.frame, style="Content.TFrame")
        if not collapsed:
            self.body.pack(fill=BOTH, expand=True)

    def toggle(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.body.pack_forget()
            self.toggle_btn.configure(text=self._title + " (展开)")
        else:
            self.body.pack(fill=BOTH, expand=True)
            self.toggle_btn.configure(text=self._title + " (收起)")
    
    def expand_if_collapsed(self) -> None:
        """如果当前是折叠状态，则展开。"""
        if self._collapsed:
            self.toggle()
    
    def collapse_if_expanded(self) -> None:
        """如果当前是展开状态，则折叠。"""
        if not self._collapsed:
            self.toggle()


class MarkdownViewer:
    """Lightweight markdown-aware text viewer for Tk。流式时插入，完成时全量重渲染。"""

    def __init__(
        self,
        parent: tk.Widget,
        *,
        body_bg: str = "#ffffff",
        body_fg: str = "#333333",
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

    def append_stream(self, text: str) -> None:
        """流式追加：不重新解析 markdown，直接插入正文。"""

        if not text:
            return
        self._buffer += text
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, text, ("body",))
        self.text.configure(state=tk.DISABLED)
        self.text.see(tk.END)

    def _configure_tags(self) -> None:
        self.text.tag_config("body", font=("Microsoft YaHei UI", 11), foreground="#333333", spacing3=8)
        self.text.tag_config("h1", font=("Microsoft YaHei UI", 22, "bold"), foreground="#1a1a1a", spacing1=24, spacing3=12)
        self.text.tag_config("h2", font=("Microsoft YaHei UI", 18, "bold"), foreground="#2c2c2c", spacing1=20, spacing3=10)
        self.text.tag_config("h3", font=("Microsoft YaHei UI", 14, "bold"), foreground="#444444", spacing1=16, spacing3=8)
        self.text.tag_config("bullet", font=("Microsoft YaHei UI", 11), foreground="#333333", lmargin1=20, lmargin2=36, spacing3=6)
        self.text.tag_config("codeblock", font=("Consolas", 10), background="#f8f9fa", foreground="#24292e", lmargin1=15, lmargin2=15, spacing1=10, spacing3=10)
        self.text.tag_config("inline_code", font=("Consolas", 10, "bold"), background="#f1f3f5", foreground="#e03131", relief=tk.FLAT, borderwidth=0)

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
    sidebar = ttk.Frame(main_container, style="Sidebar.TFrame", width=320, padding=20)
    sidebar.pack(side=LEFT, fill=Y)
    sidebar.pack_propagate(False) # 固定宽度

    # 1. 品牌标题
    branding_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
    branding_frame.pack(fill=X, pady=(0, 20))
    ttk.Label(branding_frame, text="代码审查助手", style="SidebarTitle.TLabel").pack(anchor=W)
    
    ttk.Separator(sidebar, orient=HORIZONTAL).pack(fill=X, pady=(0, 20))

    # 2. 项目配置 - 可折叠
    project_section = CollapsibleSection(sidebar, "项目配置", collapsed=False)
    project_section.frame.pack(fill=X, pady=(0, 15))
    
    # 项目路径
    project_var = tk.StringVar(value="")
    ttk.Label(project_section.body, text="选择审查文件夹", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 10))
    p_frame = ttk.Frame(project_section.body, style="Sidebar.TFrame")
    p_frame.pack(fill=X, pady=(0, 15))
    
    p_entry = ttk.Entry(p_frame, textvariable=project_var, bootstyle="secondary")
    p_entry.pack(side=LEFT, fill=X, expand=True)
    
    def choose_root():
        p = filedialog.askdirectory()
        if p: project_var.set(p)
    ttk.Button(p_frame, text="...", command=choose_root, bootstyle="secondary-outline", width=3).pack(side=RIGHT, padx=(8, 0))

    # 模型选择
    model_var = tk.StringVar(value="auto")
    planner_model_var = tk.StringVar(value="auto")
    llm_options_data = available_llm_options()
    llm_options = [opt["name"] for opt in llm_options_data]
    if "auto" not in llm_options:
        llm_options.insert(0, "auto")
    
    ttk.Label(project_section.body, text="审查模型", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 6))
    ttk.Combobox(project_section.body, textvariable=model_var, values=llm_options, state="readonly", bootstyle="secondary").pack(fill=X, pady=(0, 12))
    ttk.Label(project_section.body, text="规划模型（可选）", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 6))
    ttk.Combobox(project_section.body, textvariable=planner_model_var, values=llm_options, state="readonly", bootstyle="secondary").pack(fill=X, pady=(0, 15))

    # 3. 工具与指令 - 可折叠
    tools_section = CollapsibleSection(sidebar, "工具与指令", collapsed=True)
    tools_section.frame.pack(fill=X, pady=(0, 15))
    
    # 工具列表 (紧凑网格布局)
    ttk.Label(tools_section.body, text="工具", style="SidebarHeader.TLabel").pack(anchor=W, pady=(0, 10))
    
    tool_vars: Dict[str, tk.BooleanVar] = {}
    tools_grid = ttk.Frame(tools_section.body, style="Sidebar.TFrame")
    tools_grid.pack(fill=X, pady=(0, 15))
    
    # 按列排列工具，每列显示2个
    tool_list = available_tools()
    for i, tool in enumerate(tool_list):
        name = tool["name"]
        var = tk.BooleanVar(value=tool.get("default", False))
        tool_vars[name] = var
        # 使用grid布局，每行2列
        ttk.Checkbutton(tools_grid, text=name, variable=var, bootstyle="secondary").grid(
            row=i//2, column=i%2, sticky=W, padx=(0, 20), pady=3
        )

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

    ttk.Button(tools_section.body, text="自定义审查指令...", command=open_prompt_editor, bootstyle="secondary-outline").pack(fill=X, pady=(0, 15))

    # 自动批准
    auto_approve_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(tools_section.body, text="自动执行工具", variable=auto_approve_var, bootstyle="round-toggle").pack(anchor=W, pady=(0, 15))

    # 4. 回退监控 - 可折叠
    monitor_section = CollapsibleSection(sidebar, "监控", collapsed=True)
    monitor_section.frame.pack(fill=X, pady=(0, 15))
    
    fallback_frame = ttk.Frame(monitor_section.body, style="Sidebar.TFrame", padding=10)
    fallback_frame.pack(fill=X)
    
    fb_status_lbl = ttk.Label(fallback_frame, text="等待运行...", bootstyle="secondary", font=("Microsoft YaHei UI", 9))
    fb_status_lbl.pack(anchor=W)
    
    fb_detail_lbl = ttk.Label(fallback_frame, text="暂无异常告警", bootstyle="secondary", font=("Microsoft YaHei UI", 8), wraplength=280, justify=tk.LEFT)
    fb_detail_lbl.pack(anchor=W, pady=(5, 0))

    # 底部：启动按钮
    # 使用 pack(side=BOTTOM) 将其推到底部
    sidebar_bottom = ttk.Frame(sidebar, style="Sidebar.TFrame")
    sidebar_bottom.pack(side=BOTTOM, fill=X)
    
    ttk.Separator(sidebar, orient=HORIZONTAL).pack(side=BOTTOM, fill=X, pady=(20, 0)) # 分割线在按钮上方
    
    # 4. 启动按钮 (Big Black Button)
    run_btn = ttk.Button(sidebar_bottom, text="开始审查", bootstyle="dark", padding=(0, 15))
    run_btn.pack(fill=X, pady=(20, 0))

    # 导出事件按钮
    def export_events():
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(history_events, fp, ensure_ascii=False, indent=2)
            Messagebox.show_info(f"已导出事件到 {path}")
        except Exception as e:
            Messagebox.show_error(f"导出失败: {e}")
    ttk.Button(sidebar_bottom, text="导出链路事件", command=export_events, bootstyle="secondary-outline").pack(fill=X, pady=(10, 0))

    # --- 右侧：内容工作台 (Content) ---
    content_area = ttk.Frame(main_container, style="Content.TFrame", padding=30)
    content_area.pack(side=RIGHT, fill=BOTH, expand=True)

    # 顶部状态栏
    status_bar = ttk.Frame(content_area, style="Content.TFrame")
    status_bar.pack(fill=X, pady=(0, 20))
    
    # 右侧：状态指示器 (Clean Design)
    status_indicator_frame = ttk.Frame(status_bar, style="Content.TFrame")
    status_indicator_frame.pack(side=RIGHT)
    
    # 状态点绘制
    status_canvas = tk.Canvas(status_indicator_frame, width=10, height=10, bg=COLORS["content_bg"], highlightthickness=0)
    status_dot = status_canvas.create_oval(1, 1, 9, 9, fill=COLORS["success"], outline="")
    status_canvas.pack(side=LEFT, padx=(0, 8))
    
    status_text = ttk.Label(status_indicator_frame, text="系统就绪", font=("Microsoft YaHei UI", 10), background=COLORS["content_bg"], foreground=COLORS["text_secondary"])
    status_text.pack(side=LEFT)
    
    # tokens 计数
    tokens_lbl = ttk.Label(status_indicator_frame, text="", font=("Microsoft YaHei UI", 10), background=COLORS["content_bg"], foreground=COLORS["text_muted"])
    tokens_lbl.pack(side=LEFT, padx=(15, 0))

    # 状态/流程视图 - 紧凑折叠式
    stages = [
        "diff_parse","review_units","rule_layer","review_index","intent_analysis","planner",
        "fusion","final_context_plan","context_provider","context_bundle","reviewer","issues","final_output"
    ]
    stage_vars: Dict[str, tk.StringVar] = {s: tk.StringVar(value="等待") for s in stages}
    
    # 流程状态 - 可折叠
    stages_section = CollapsibleSection(content_area, "流程状态", collapsed=True)
    stages_section.frame.pack(fill=X, pady=(0, 20))
    
    # 使用紧凑的网格布局显示流程状态
    stages_grid = ttk.Frame(stages_section.body, style="Content.TFrame")
    stages_grid.pack(fill=X)
    
    # 每行显示3个状态
    for i, s in enumerate(stages):
        stage_frame = ttk.Frame(stages_grid, style="Content.TFrame", padding=(10, 5))
        stage_frame.grid(row=i//3, column=i%3, sticky=W+E, padx=5, pady=5)
        stage_frame.columnconfigure(1, weight=1)
        
        ttk.Label(stage_frame, text=s, font=("Microsoft YaHei UI", 10, "bold"), width=18).grid(row=0, column=0, sticky=W)
        ttk.Label(stage_frame, textvariable=stage_vars[s], foreground=COLORS["text_secondary"], width=10).grid(row=0, column=1, sticky=E)

    # 调整网格列宽
    for i in range(3):
        stages_grid.columnconfigure(i, weight=1)

    # 单页展示区域 - 空白信息载体
    sections_container = ttk.Frame(content_area, style="Content.TFrame")
    sections_container.pack(fill=BOTH, expand=True)

    # 主要输出区域（空白信息载体）
    result_viewer = MarkdownViewer(sections_container, body_bg=COLORS["content_bg"], body_fg=COLORS["text_primary"])
    result_viewer.text.pack(fill=BOTH, expand=True)
    result_viewer.set_content("")

    # 动态加载的辅助信息区域
    auxiliary_container = ttk.Frame(sections_container, style="Content.TFrame")
    auxiliary_container.pack(fill=X, expand=False)

    # 初始化辅助信息组件，但默认不显示
    planner_stream = None
    thoughts_stream = None
    tools_list = None
    bundle_list = None
    intent_stream = None

    # 创建辅助信息组件的函数
    def create_auxiliary_components():
        nonlocal planner_stream, thoughts_stream, tools_list, bundle_list, intent_stream
        
        # 只创建一次
        if planner_stream is not None:
            return
        
        # 辅助信息区域标题
        ttk.Label(auxiliary_container, text="辅助信息", font=(
            "Microsoft YaHei UI", 12, "bold")).pack(anchor=W, pady=(15, 10))
        
        # 辅助信息框架
        aux_frame = ttk.Frame(auxiliary_container, style="Content.TFrame")
        aux_frame.pack(fill=X, expand=False)
        aux_frame.columnconfigure(0, weight=1)
        aux_frame.columnconfigure(1, weight=1)
        
        # 意图分析
        ttk.Label(aux_frame, text="意图分析", font=(
            "Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky=W, padx=(0, 10), pady=(0, 5))
        intent_stream = scrolledtext.ScrolledText(
            aux_frame, height=4, wrap=tk.WORD, font=("Microsoft YaHei UI", 10),
            bg=COLORS["content_bg"], relief=tk.FLAT, borderwidth=0
        )
        intent_stream.grid(row=1, column=0, sticky=W+E+N+S, padx=(0, 10), pady=(0, 10))
        
        # 规划思考
        ttk.Label(aux_frame, text="规划思考", font=(
            "Microsoft YaHei UI", 10, "bold")).grid(row=0, column=1, sticky=W, padx=(10, 0), pady=(0, 5))
        planner_stream = scrolledtext.ScrolledText(
            aux_frame, height=4, wrap=tk.WORD, font=("Microsoft YaHei UI", 10),
            bg=COLORS["content_bg"], relief=tk.FLAT, borderwidth=0
        )
        planner_stream.grid(row=1, column=1, sticky=W+E+N+S, padx=(10, 0), pady=(0, 10))
        
        # 审查思考
        ttk.Label(aux_frame, text="审查思考", font=(
            "Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky=W, padx=(0, 10), pady=(0, 5))
        thoughts_stream = scrolledtext.ScrolledText(
            aux_frame, height=4, wrap=tk.WORD, font=("Microsoft YaHei UI", 10),
            bg=COLORS["content_bg"], relief=tk.FLAT, borderwidth=0
        )
        thoughts_stream.grid(row=3, column=0, sticky=W+E+N+S, padx=(0, 10), pady=(0, 10))
        
        # 工具调用
        ttk.Label(aux_frame, text="工具调用", font=(
            "Microsoft YaHei UI", 10, "bold")).grid(row=2, column=1, sticky=W, padx=(10, 0), pady=(0, 5))
        tools_list = scrolledtext.ScrolledText(
            aux_frame, height=4, wrap=tk.WORD, font=("Consolas", 9),
            bg=COLORS["content_bg"], relief=tk.FLAT, borderwidth=0
        )
        tools_list.grid(row=3, column=1, sticky=W+E+N+S, padx=(10, 0), pady=(0, 10))
        
        # 上下文包
        ttk.Label(aux_frame, text="上下文包", font=(
            "Microsoft YaHei UI", 10, "bold")).grid(row=4, column=0, sticky=W, padx=(0, 10), pady=(0, 5))
        bundle_list = scrolledtext.ScrolledText(
            aux_frame, height=4, wrap=tk.WORD, font=("Consolas", 9),
            bg=COLORS["content_bg"], relief=tk.FLAT, borderwidth=0
        )
        bundle_list.grid(row=5, column=0, sticky=W+E+N+S, padx=(0, 10), pady=(0, 10))
        
        # 调整网格布局，增加一行
        aux_frame.rowconfigure(4, weight=1)
        aux_frame.rowconfigure(5, weight=1)

    # === 4. 业务逻辑集成 ===
    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    is_running = False
    fallback_seen = False
    history_events: List[Dict[str, Any]] = []
    last_content_call_idx: int | None = None
    last_thought_call_idx: int | None = None

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
        result_viewer.append_stream("# 正在初始化审查任务...\n\n")
        for s in stages:
            stage_vars[s].set("等待")
        
        # 重置辅助信息组件（如果存在）
        if intent_stream:
            intent_stream.delete("1.0", tk.END)
        if planner_stream:
            planner_stream.delete("1.0", tk.END)
        if thoughts_stream:
            thoughts_stream.delete("1.0", tk.END)
        if tools_list:
            tools_list.delete("1.0", tk.END)
        if bundle_list:
            bundle_list.delete("1.0", tk.END)
        
        history_events.clear()
        run_btn.configure(state=tk.DISABLED, text="任务执行中...")
        update_status("busy", "正在运行...")
        tokens_lbl.configure(text="")
        fallback_seen = False
        fb_status_lbl.configure(text="运行中...", bootstyle="secondary")
        fb_detail_lbl.configure(text="正在监控系统回退事件")
        last_content_call_idx = None
        last_thought_call_idx = None
        
        is_running = True

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

            # Stream Callback
            def stream_handler(evt):
                etype = evt.get("type")
                if etype == "delta":
                    reasoning = evt.get("reasoning_delta", "")
                    content = evt.get("content_delta", "")
                    if reasoning:
                        event_queue.put(
                            {
                                "type": "thought",
                                "content": reasoning,
                                "call_index": evt.get("call_index"),
                            }
                        )
                    if content:
                        event_queue.put(
                            {
                                "type": "stream",
                                "content": content,
                                "call_index": evt.get("call_index"),
                            }
                        )
                    return
                if etype == "usage_summary":
                    event_queue.put({"type": "usage", "data": evt})
                    return
                if etype == "warning":
                    event_queue.put({"type": "fallback", "data": evt})
                    return
                # 透传其他事件类型（planner/tool/bundle/pipeline）
                event_queue.put(evt)

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
                llm_preference=llm_pref,
                planner_llm_preference=planner_model_var.get() or llm_pref,
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
        nonlocal is_running, fallback_seen, last_content_call_idx, last_thought_call_idx
        try:
            while True:
                ev = event_queue.get_nowait()
                etype = ev["type"]
                
                if etype == "stream":
                    idx = ev.get("call_index")
                    if idx is not None and idx != last_content_call_idx:
                        # 分段标记不同的 LLM 调用
                        result_viewer.append_stream(f"\n\n---\n## 模型调用 #{idx}\n\n")
                        last_content_call_idx = idx
                    result_viewer.append_stream(ev["content"])
                    history_events.append(ev)
                
                elif etype == "thought":
                    content = ev.get("content", "")
                    idx = ev.get("call_index")
                    create_auxiliary_components()
                    if thoughts_stream:
                        if idx is not None and idx != last_thought_call_idx:
                            thoughts_stream.insert(tk.END, f"\n\n--- 思考 #{idx} ---\n\n")
                            last_thought_call_idx = idx
                        if content:
                            thoughts_stream.insert(tk.END, content)
                            thoughts_stream.see(tk.END)
                    history_events.append(ev)
                
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
                    tokens_lbl.configure(text=f"tokens: {total}")

                elif etype == "approval":
                    call = ev["call"]
                    q = ev["q"]
                    name = call.get("name", "unknown")
                    args = call.get("arguments", "{}")
                    msg = f"允许执行工具调用吗？\n\n工具: {name}\n参数: {args}"
                    ans = Messagebox.yesno(msg, "工具执行确认", parent=root)
                    q.put(ans == "Yes")
                
                elif etype == "intent_delta":
                    # 处理意图分析的流式输出
                    content = ev.get("content_delta", "")
                    reasoning = ev.get("reasoning_delta", "")
                    create_auxiliary_components()
                    if intent_stream:
                        # 确保intent_stream处于可编辑状态
                        intent_stream.configure(state=tk.NORMAL)
                        
                        if reasoning:
                            # 检查当前光标位置前的内容，避免重复添加标签
                            intent_stream.mark_set(tk.INSERT, tk.END)
                            # 获取当前行的内容
                            current_line = intent_stream.get(tk.INSERT + "-1c linestart", tk.INSERT)
                            if "思考：" not in current_line:
                                # 添加思考内容标签
                                intent_stream.insert(tk.END, "\n思考：")
                            intent_stream.insert(tk.END, reasoning)
                        
                        if content:
                            # 检查当前光标位置前的内容，避免重复添加标签
                            intent_stream.mark_set(tk.INSERT, tk.END)
                            # 获取当前行的内容
                            current_line = intent_stream.get(tk.INSERT + "-1c linestart", tk.INSERT)
                            if "正式输出：" not in current_line:
                                # 添加正式输出标签
                                intent_stream.insert(tk.END, "\n正式输出：")
                            intent_stream.insert(tk.END, content)
                        
                        # 恢复只读状态
                        intent_stream.configure(state=tk.DISABLED)
                        intent_stream.see(tk.END)
                    history_events.append(ev)
                
                elif etype == "done":
                    result_viewer.append_stream("\n\n---\n**审查任务完成**")
                    # 最终渲染一次 markdown，保证格式恢复
                    result_viewer.set_content(result_viewer._buffer)
                    is_running = False
                    run_btn.configure(state=tk.NORMAL, text="开始审查")
                    update_status("idle", "任务完成")
                    if not fallback_seen:
                        fb_status_lbl.configure(text="一切正常", bootstyle="success")
                        fb_detail_lbl.configure(text="本次运行未检测到回退路径")
                    stage_vars["final_output"].set("成功")
                    # 基于最终输出提取问题索引
                    try:
                        text = result_viewer._buffer
                        lines = text.splitlines()
                        extracted = []
                        import re
                        pat = re.compile(r"([\w./\\-]+):(L?\d+(?:-\d+)?)")
                        for ln in lines:
                            m = pat.findall(ln)
                            if m:
                                for fp, loc in m:
                                    extracted.append({"file": fp, "loc": loc, "line": ln.strip()[:500]})
                        # issues_list.delete("1.0", tk.END)
                        # if not extracted:
                        #     issues_list.insert(tk.END, "未能从最终输出中抽取结构化问题位置，可在报告中手动查看。")
                        # else:
                        #     for it in extracted:
                        #         issues_list.insert(tk.END, f"- {it['file']}:{it['loc']} — {it['line']}\n")
                        stage_vars["issues"].set("成功")
                        history_events.append({"type":"issues_index","items":extracted})
                    except Exception:
                        pass
                    history_events.append(ev)
                
                elif etype == "error":
                    result_viewer.append_stream(f"\n\n**错误**: {ev['error']}")
                    result_viewer.set_content(result_viewer._buffer)
                    stage = ev.get("stage")
                    if stage and stage in stage_vars:
                        stage_vars[stage].set("失败")
                    is_running = False
                    run_btn.configure(state=tk.NORMAL, text="重试任务")
                    update_status("error", "发生错误")
                    history_events.append(ev)
                elif etype == "pipeline_stage_start":
                    stage = ev.get("stage")
                    if stage in stage_vars:
                        stage_vars[stage].set("进行中")
                    history_events.append(ev)
                elif etype == "pipeline_stage_end":
                    stage = ev.get("stage")
                    if stage in stage_vars:
                        stage_vars[stage].set("成功")
                    history_events.append(ev)
                elif etype == "planner_delta":
                    delta = ev.get("reasoning_delta") or ev.get("content_delta") or ev.get("delta") or ""
                    if delta:
                        create_auxiliary_components()
                        if planner_stream:
                            planner_stream.insert(tk.END, delta)
                            planner_stream.see(tk.END)
                    history_events.append(ev)
                elif etype == "tool_call_start":
                    nm = ev.get("tool_name")
                    args = ev.get("arguments")
                    create_auxiliary_components()
                    if tools_list:
                        tools_list.insert(tk.END, f"→ {nm} {json.dumps(args, ensure_ascii=False)}\n")
                        tools_list.see(tk.END)
                    history_events.append(ev)
                elif etype == "tool_call_end":
                    nm = ev.get("tool_name")
                    dur = ev.get("duration_ms")
                    cpu = ev.get("cpu_time")
                    mem = ev.get("mem_delta")
                    create_auxiliary_components()
                    if tools_list:
                        tools_list.insert(tk.END, f"← {nm} done {dur}ms cpu={cpu} memΔ={mem}\n")
                        tools_list.see(tk.END)
                    history_events.append(ev)
                elif etype == "tool_result":
                    nm = ev.get("tool_name")
                    err = ev.get("error")
                    create_auxiliary_components()
                    if tools_list:
                        if err:
                            tools_list.insert(tk.END, f"! {nm} error: {err}\n")
                        else:
                            tools_list.insert(tk.END, f"= {nm} result: (已返回，详见日志)\n")
                        tools_list.see(tk.END)
                    history_events.append(ev)
                elif etype == "bundle_item":
                    uid = ev.get("unit_id")
                    lvl = ev.get("final_context_level")
                    loc = ev.get("location")
                    create_auxiliary_components()
                    if bundle_list:
                        bundle_list.insert(tk.END, f"[{uid}] {lvl} {loc}\n")
                        bundle_list.see(tk.END)
                    history_events.append(ev)
                    
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
