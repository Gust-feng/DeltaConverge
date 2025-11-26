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
from tkinter import filedialog, messagebox, scrolledtext, ttk

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
        body_bg: str = "#0b1221",
        body_fg: str = "#e2e8f0",
    ) -> None:
        self._buffer: str = ""
        self.text = scrolledtext.ScrolledText(
            parent,
            height=16,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            background=body_bg,
            foreground=body_fg,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            insertbackground=body_fg,
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
        self.text.tag_config(
            "body",
            font=("Segoe UI", 11),
            foreground="#e2e8f0",
            spacing3=4,
        )
        self.text.tag_config(
            "h1",
            font=("Segoe UI", 16, "bold"),
            foreground="#f8fafc",
            spacing1=8,
            spacing3=6,
        )
        self.text.tag_config(
            "h2",
            font=("Segoe UI", 14, "bold"),
            foreground="#f8fafc",
            spacing1=6,
            spacing3=4,
        )
        self.text.tag_config(
            "h3",
            font=("Segoe UI", 12, "bold"),
            foreground="#e2e8f0",
            spacing1=4,
            spacing3=2,
        )
        self.text.tag_config(
            "bullet",
            font=("Segoe UI", 11),
            foreground="#e2e8f0",
            lmargin1=16,
            lmargin2=32,
            spacing3=3,
        )
        self.text.tag_config(
            "codeblock",
            font=("JetBrains Mono", 10),
            background="#0f172a",
            foreground="#cbd5e1",
            lmargin1=10,
            lmargin2=18,
            spacing1=4,
            spacing3=6,
        )
        self.text.tag_config(
            "inline_code",
            font=("JetBrains Mono", 10, "bold"),
            background="#1e293b",
            foreground="#e2e8f0",
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
    root = tk.Tk()
    root.title("Agent 管理面板")
    root.geometry("1280x800")

    bg = "#f7f8fb"
    accent = "#2563eb"
    muted = "#475569"

    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=bg)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground="#0f172a", font=("Segoe UI", 11))
    style.configure("Header.TLabel", background=bg, foreground="#0f172a", font=("Segoe UI", 16, "bold"))
    style.configure("Muted.TLabel", background=bg, foreground=muted, font=("Segoe UI", 10))
    style.configure(
        "Badge.TLabel",
        background="#e2e8f0",
        foreground="#0f172a",
        padding=(10, 4),
        font=("Segoe UI", 10, "bold"),
    )
    style.configure(
        "Status.TLabel",
        background="#e2e8f0",
        foreground=muted,
        padding=(10, 4),
        font=("Segoe UI", 10),
    )
    style.configure(
        "Accent.TButton",
        padding=8,
        font=("Segoe UI", 11, "bold"),
        background=accent,
        foreground="white",
        borderwidth=0,
    )
    style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#cbd5e1")], foreground=[("disabled", "#f8fafc")])
    style.configure("Card.TLabelframe", background=bg, foreground="#0f172a", padding=12)
    style.configure("Card.TLabelframe.Label", background=bg, foreground="#0f172a", font=("Segoe UI", 11, "bold"))

    outer = ttk.Frame(root, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    header = ttk.Frame(outer)
    header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    ttk.Label(header, text="Agent 管理面板", style="Header.TLabel").pack(side=tk.LEFT)
    token_label = ttk.Label(header, text="Tokens: -", style="Badge.TLabel")
    token_label.pack(side=tk.RIGHT, padx=(8, 0))
    status_var = tk.StringVar(value="Idle")
    ttk.Label(header, textvariable=status_var, style="Status.TLabel").pack(
        side=tk.RIGHT, padx=(0, 4)
    )

    left = ttk.LabelFrame(outer, text="设置", style="Card.TLabelframe", padding=12)
    left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
    outer.grid_columnconfigure(0, weight=1, minsize=320)
    outer.grid_columnconfigure(1, weight=6, minsize=720)
    outer.grid_rowconfigure(1, weight=1)
    left.grid_columnconfigure(1, weight=1)

    ttk.Label(left, text="LLM Provider").grid(row=0, column=0, sticky="w")
    model_var = tk.StringVar(value="auto")
    options = ["auto"]
    if GLM_KEY_PRESENT:
        options.append("glm")
    if BAILIAN_KEY_PRESENT:
        options.append("bailian")
    if MOONSHOT_KEY_PRESENT:
        options.append("moonshot")
    options.append("mock")
    ttk.OptionMenu(left, model_var, model_var.get(), *options).grid(
        row=0, column=1, sticky="ew", padx=(8, 0)
    )

    ttk.Label(left, text="Project root").grid(row=1, column=0, sticky="w", pady=(10, 0))
    project_var = tk.StringVar(value="")
    project_entry = ttk.Entry(left, textvariable=project_var)
    project_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))

    def choose_project_root() -> None:
        path = filedialog.askdirectory(title="选择待审查项目根目录")
        if path:
            project_var.set(path)

    ttk.Button(left, text="Browse", command=choose_project_root).grid(
        row=1, column=2, padx=(8, 0), pady=(10, 0)
    )

    auto_approve_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(
        left,
        text="Auto approve selected tools",
        variable=auto_approve_var,
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 6))

    tools_frame = ttk.LabelFrame(left, text="Tools", style="Card.TLabelframe", padding=10)
    tools_frame.grid(row=3, column=0, columnspan=3, sticky="nsew")
    left.grid_rowconfigure(3, weight=1)

    tool_vars: Dict[str, tk.BooleanVar] = {}
    tools_canvas = tk.Canvas(tools_frame, highlightthickness=0, background=bg, borderwidth=0, relief=tk.FLAT)
    tools_scrollbar = ttk.Scrollbar(tools_frame, orient="vertical", command=tools_canvas.yview)
    tools_inner = ttk.Frame(tools_canvas)
    tools_inner.bind(
        "<Configure>",
        lambda e: tools_canvas.configure(scrollregion=tools_canvas.bbox("all")),
    )
    tools_canvas.create_window((0, 0), window=tools_inner, anchor="nw")
    tools_canvas.configure(yscrollcommand=tools_scrollbar.set, height=200)
    tools_canvas.grid(row=0, column=0, sticky="nsew")
    tools_scrollbar.grid(row=0, column=1, sticky="ns")
    tools_frame.grid_rowconfigure(0, weight=1)
    tools_frame.grid_columnconfigure(0, weight=1)

    for idx, name in enumerate(list_tool_names()):
        var = tk.BooleanVar(value=name in default_tool_names())
        tool_vars[name] = var
        ttk.Checkbutton(
            tools_inner,
            text=name,
            variable=var,
        ).grid(row=idx, column=0, sticky="w", pady=(0, 2))

    # Prompt 编辑放在左侧，减少与结果区的干扰；提供弹出式大屏编辑。
    prompt_card = ttk.LabelFrame(left, text="Prompt", style="Card.TLabelframe", padding=10)
    prompt_card.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
    prompt_card.grid_columnconfigure(0, weight=1)

    prompt_box = scrolledtext.ScrolledText(
        prompt_card,
        height=5,
        wrap=tk.WORD,
        font=("JetBrains Mono", 11),
        background="#f1f5f9",
        foreground="#0f172a",
        relief=tk.FLAT,
        borderwidth=0,
        highlightthickness=0,
        insertbackground="#0f172a",
    )
    prompt_box.insert(
        tk.END,
        DEFAULT_USER_PROMPT,
    )
    prompt_box.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
    prompt_box.edit_modified(False)

    prompt_preview_var = tk.StringVar(value="Prompt: (默认)")
    prompt_popup: tk.Toplevel | None = None

    def _update_prompt_preview() -> None:
        content = prompt_box.get("1.0", tk.END).strip().splitlines()
        first_line = content[0] if content else "(空)"
        preview = first_line if len(first_line) <= 80 else first_line[:77] + "..."
        prompt_preview_var.set(f"Prompt: {preview}")

    def _on_prompt_modified(event: tk.Event | None = None) -> None:
        prompt_box.edit_modified(False)
        _update_prompt_preview()

    def open_prompt_modal() -> None:
        nonlocal prompt_popup
        if prompt_popup and prompt_popup.winfo_exists():
            prompt_popup.lift()
            return
        prompt_popup = tk.Toplevel(root)
        prompt_popup.title("编辑 Prompt")
        prompt_popup.geometry("820x540")
        prompt_popup.configure(bg=bg)
        modal_frame = ttk.Frame(prompt_popup, padding=12)
        modal_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(modal_frame, text="Prompt（大屏编辑）").pack(anchor="w")
        modal_text = scrolledtext.ScrolledText(
            modal_frame,
            wrap=tk.WORD,
            font=("JetBrains Mono", 11),
            background="#f1f5f9",
            foreground="#0f172a",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            insertbackground="#0f172a",
        )
        modal_text.insert(tk.END, prompt_box.get("1.0", tk.END))
        modal_text.pack(fill=tk.BOTH, expand=True, pady=(6, 10))

        def save_prompt() -> None:
            prompt_box.delete("1.0", tk.END)
            prompt_box.insert(tk.END, modal_text.get("1.0", tk.END))
            prompt_box.edit_modified(False)
            _update_prompt_preview()
            prompt_popup.destroy()

        footer = ttk.Frame(modal_frame)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="取消", command=lambda: prompt_popup.destroy()).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(footer, text="保存并关闭", style="Accent.TButton", command=save_prompt).pack(side=tk.RIGHT)

        def on_close() -> None:
            if prompt_popup:
                prompt_popup.destroy()

        prompt_popup.protocol("WM_DELETE_WINDOW", on_close)

    prompt_header = ttk.Frame(prompt_card)
    prompt_header.grid(row=0, column=0, sticky="ew")
    ttk.Label(prompt_header, text="Prompt（可选，默认不必修改）").pack(side=tk.LEFT)
    ttk.Button(prompt_header, text="弹出编辑", command=open_prompt_modal).pack(side=tk.RIGHT)
    prompt_box.bind("<<Modified>>", _on_prompt_modified)
    _update_prompt_preview()

    right = ttk.Frame(outer)
    right.grid(row=1, column=1, sticky="nsew")
    outer.grid_columnconfigure(1, weight=6)
    right.grid_rowconfigure(0, weight=1)
    right.grid_columnconfigure(0, weight=1)

    result_card = ttk.LabelFrame(right, text="Result (Markdown)", style="Card.TLabelframe", padding=10)
    result_card.grid(row=0, column=0, sticky="nsew")
    result_card.grid_rowconfigure(1, weight=1)
    result_card.grid_columnconfigure(0, weight=1)

    result_header = ttk.Frame(result_card)
    result_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    result_header.grid_columnconfigure(0, weight=1)
    ttk.Label(result_header, text="Result").grid(row=0, column=0, sticky="w")
    ttk.Label(result_header, textvariable=prompt_preview_var, style="Muted.TLabel").grid(
        row=1, column=0, sticky="w", pady=(2, 0)
    )

    header_actions = ttk.Frame(result_header)
    header_actions.grid(row=0, column=1, rowspan=2, sticky="e")
    shortcut_hint = ttk.Label(header_actions, text="Ctrl+Enter 运行", style="Muted.TLabel")
    shortcut_hint.pack(side=tk.LEFT, padx=(0, 8))
    edit_prompt_btn = ttk.Button(header_actions, text="编辑 Prompt", command=open_prompt_modal)
    edit_prompt_btn.pack(side=tk.LEFT, padx=(0, 8))
    clear_button = ttk.Button(header_actions, text="Clear Result", command=lambda: result_viewer.clear())
    clear_button.pack(side=tk.LEFT, padx=(0, 8))
    run_button = ttk.Button(header_actions, text="Run Agent", style="Accent.TButton")
    run_button.pack(side=tk.LEFT)

    result_viewer = MarkdownViewer(
        result_card,
        body_bg="#0b1221",
        body_fg="#e2e8f0",
    )
    result_viewer.text.grid(row=1, column=0, sticky="nsew")

    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    is_running = False
    usage_agg = UsageAggregator()

    def _bind_mousewheel(widget: tk.Widget, command) -> None:
        def _on_mousewheel(event: tk.Event) -> None:
            delta = int(-1 * (event.delta / 120)) if event.delta else 0
            if delta:
                command(delta)

        def _on_scroll_up(_: tk.Event) -> None:
            command(-1)

        def _on_scroll_down(_: tk.Event) -> None:
            command(1)

        widget.bind("<Enter>", lambda _: widget.bind_all("<MouseWheel>", _on_mousewheel))
        widget.bind("<Leave>", lambda _: widget.unbind_all("<MouseWheel>"))
        widget.bind("<Enter>", lambda _: widget.bind_all("<Button-4>", _on_scroll_up))
        widget.bind("<Leave>", lambda _: widget.unbind_all("<Button-4>"))
        widget.bind("<Enter>", lambda _: widget.bind_all("<Button-5>", _on_scroll_down))
        widget.bind("<Leave>", lambda _: widget.unbind_all("<Button-5>"))

    _bind_mousewheel(
        tools_canvas, lambda delta: tools_canvas.yview_scroll(delta, "units")
    )

    def _render_usage(
        call_usage: Dict[str, Any],
        session_usage: Dict[str, Any],
        call_index: Any,
        stage: str | None,
    ) -> None:
        label = "planner" if stage == "planner" or call_index == 0 else f"call#{call_index or 1}"
        token_label.config(
            text=(
                f"Tokens: {label} total={call_usage.get('total', '-')}"
                f" (in={call_usage.get('in', '-')}, out={call_usage.get('out', '-')}) | "
                f"session_total={session_usage.get('total', '-')}"
                f" (in={session_usage.get('in', '-')}, out={session_usage.get('out', '-')})"
            )
        )

    def selected_tool_names() -> List[str]:
        return [name for name, var in tool_vars.items() if var.get()]

    def _format_tool_args(args: Any, max_len: int = 300) -> str:
        """为 GUI 提示生成简短的工具参数预览。"""

        if isinstance(args, str):
            preview = args.strip()
        else:
            preview = json.dumps(args, ensure_ascii=False, indent=2)

        preview = preview.replace("\r", "")
        lines = preview.splitlines()
        if len(lines) > 8:
            preview = "\n".join(lines[:8]) + "\n...(内容较长，仅显示前 8 行)"

        if len(preview) > max_len:
            preview = preview[: max_len - 20] + "\n...(内容较长，已截断)"
        return preview

    def gui_tool_approver(calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        response_queue = queue.Queue()
        event_queue.put(
            {"type": "tool_request", "calls": calls, "response_queue": response_queue}
        )
        return response_queue.get()

    def worker(
        prompt_text: str,
        preference: str,
        names: List[str],
        auto_approve: bool,
        project_root: str | None,
    ) -> None:
        def observer(event: Dict[str, Any]) -> None:
            event_queue.put({"type": "delta", "payload": event})

        try:
            result = run_agent(
                prompt_text,
                preference,
                names,
                auto_approve,
                project_root or None,
                observer,
                gui_tool_approver if not auto_approve else None,
            )
            event_queue.put({"type": "final", "content": result})
        except Exception as exc:  # pragma: no cover
            event_queue.put({"type": "error", "message": str(exc)})

    def poll_queue() -> None:
        nonlocal is_running
        updated = False
        while not event_queue.empty():
            updated = True
            event = event_queue.get()
            etype = event.get("type")
            if etype == "delta":
                payload = event.get("payload", {})
                payload_type = payload.get("type")
                text = payload.get("content_delta") or ""
                if text:
                    result_viewer.append(text)
                if payload_type == "tool_result":
                    tool_name = payload.get("tool_name")
                    err = payload.get("error")
                    snippet = payload.get("content")
                    result_viewer.append(
                        f"\n\n[tool_result] {tool_name} "
                        f"{'ERROR: ' + err if err else '(ok)'}"
                        f"{' ' + str(snippet)[:200] if snippet else ''}\n"
                    )
                usage = payload.get("usage")
                call_usage = payload.get("call_usage")
                session_usage = payload.get("session_usage")
                usage_stage = payload.get("usage_stage")
                call_index = payload.get("call_index")
                if isinstance(call_usage, dict) and isinstance(session_usage, dict):
                    _render_usage(call_usage, session_usage, call_index, usage_stage)
                elif isinstance(usage, dict):
                    call_u, session_u = usage_agg.update(usage, call_index)
                    _render_usage(call_u, session_u, call_index, usage_stage)
            elif etype == "tool_request":
                calls = event.get("calls", [])
                response_queue = event.get("response_queue")
                approved: List[Dict[str, Any]] = []
                for call in calls:
                    name = call.get("name")
                    args = call.get("arguments")
                    display_args = _format_tool_args(args)
                    message = f"工具: {name}\n\n参数预览:\n{display_args}\n\n允许执行该工具吗?"
                    if messagebox.askyesno("工具审批", message):
                        approved.append(call)
                if response_queue:
                    response_queue.put(approved)
            elif etype == "final":
                result_viewer.append("\n\n## Final Reply\n")
                result_viewer.append(event.get("content", ""))
                run_button.config(state=tk.NORMAL, text="Run Agent")
                status_var.set("Done")
                is_running = False
            elif etype == "error":
                run_button.config(state=tk.NORMAL, text="Run Agent")
                status_var.set("Error")
                messagebox.showerror("Error", event.get("message", "Unknown error"))
                is_running = False
        if updated or is_running:
            root.after(100, poll_queue)

    def on_run(event: Any | None = None) -> None:
        prompt = prompt_box.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showwarning("Warning", "Prompt cannot be empty.")
            return
        usage_agg.reset()
        token_label.config(text="Tokens: -")
        run_button.config(state=tk.DISABLED, text="Running…")
        status_var.set("Running…")
        nonlocal is_running
        is_running = True
        result_viewer.set_content("Running...\n")
        root.update_idletasks()
        thread = threading.Thread(
            target=worker,
            args=(
                prompt,
                model_var.get(),
                selected_tool_names(),
                auto_approve_var.get(),
                project_var.get() or None,
            ),
            daemon=True,
        )
        thread.start()
        poll_queue()

    run_button.config(command=on_run)
    root.bind_all("<Control-Return>", on_run)
    root.bind_all("<Command-Return>", on_run)

    root.mainloop()


if __name__ == "__main__":
    main()
