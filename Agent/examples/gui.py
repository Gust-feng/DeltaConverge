"""Quick-and-dirty GUI for manually testing the agent."""

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
from tkinter import filedialog, messagebox, scrolledtext

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
    # Delegate to unified service layer to avoid multiple event loops
    return run_review(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
    )


def main() -> None:
    root = tk.Tk()
    root.title("Agent GUI (temporary)")
    root.geometry("700x500")

    header_frame = tk.Frame(root)
    header_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

    tk.Label(header_frame, text="LLM Provider").pack(side=tk.LEFT)
    model_var = tk.StringVar(value="auto")
    options = ["auto"]
    if GLM_KEY_PRESENT:
        options.append("glm")
    if BAILIAN_KEY_PRESENT:
        options.append("bailian")
    if MOONSHOT_KEY_PRESENT:
        options.append("moonshot")
    options.append("mock")
    tk.OptionMenu(header_frame, model_var, *options).pack(side=tk.LEFT, padx=(4, 12))

    tk.Label(header_frame, text="Project root:").pack(side=tk.LEFT)
    project_var = tk.StringVar(value="")
    tk.Entry(header_frame, textvariable=project_var, width=26).pack(
        side=tk.LEFT, padx=(4, 4)
    )

    def choose_project_root() -> None:
        path = filedialog.askdirectory(title="选择待审查项目根目录")
        if path:
            project_var.set(path)

    tk.Button(header_frame, text="Browse", command=choose_project_root).pack(
        side=tk.LEFT, padx=(0, 12)
    )

    run_button = tk.Button(header_frame, text="Run Agent")
    run_button.pack(side=tk.RIGHT)

    tk.Label(root, text="Prompt").pack(anchor="w", padx=8, pady=(0, 0))
    prompt_box = scrolledtext.ScrolledText(root, height=6)
    prompt_box.insert(
        tk.END,
        DEFAULT_USER_PROMPT,
    )
    prompt_box.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 4))

    tools_frame = tk.LabelFrame(root, text="Tools")
    tools_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
    auto_approve_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        tools_frame,
        text="Auto approve selected tools",
        variable=auto_approve_var,
    ).pack(anchor="w", padx=8, pady=(0, 2))
    tool_vars: Dict[str, tk.BooleanVar] = {}
    for name in list_tool_names():
        var = tk.BooleanVar(value=name in default_tool_names())
        tool_vars[name] = var
        tk.Checkbutton(
            tools_frame,
            text=name,
            variable=var,
        ).pack(anchor="w", padx=16, pady=(0, 2))

    token_label = tk.Label(root, text="Tokens: -")
    token_label.pack(anchor="w", padx=8, pady=(4, 0))
    tk.Label(root, text="Result").pack(anchor="w", padx=8, pady=(0, 0))
    result_box = scrolledtext.ScrolledText(root, height=12)
    result_box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    usage_agg = UsageAggregator()

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
        """Produce a compact preview of tool arguments for GUI prompts."""

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
                    result_box.insert(tk.END, text)
                    result_box.see(tk.END)
                if payload_type == "tool_result":
                    tool_name = payload.get("tool_name")
                    err = payload.get("error")
                    snippet = payload.get("content")
                    result_box.insert(
                        tk.END,
                        f"\n\n[tool_result] {tool_name} "
                        f"{'ERROR: '+err if err else '(ok)'}"
                        f"{' '+str(snippet)[:200] if snippet else ''}\n",
                    )
                    result_box.see(tk.END)
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
                result_box.insert(tk.END, "\n\n[Final Reply]\n")
                result_box.insert(tk.END, event.get("content", ""))
                run_button.config(state=tk.NORMAL)
            elif etype == "error":
                run_button.config(state=tk.NORMAL)
                messagebox.showerror("Error", event.get("message", "Unknown error"))
        if run_button["state"] == tk.DISABLED or updated:
            root.after(100, poll_queue)

    def on_run() -> None:
        prompt = prompt_box.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showwarning("Warning", "Prompt cannot be empty.")
            return
        usage_agg.reset()
        token_label.config(text="Tokens: -")
        run_button.config(state=tk.DISABLED)
        result_box.delete("1.0", tk.END)
        result_box.insert(tk.END, "Running...\n")
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

    root.mainloop()


if __name__ == "__main__":
    main()
