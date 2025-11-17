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
from tkinter import messagebox, scrolledtext

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

from Agent.agents.review.code_reviewer import CodeReviewAgent
from Agent.core.adapter.llm_adapter import KimiAdapter, ToolDefinition
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import collect_diff_context
from Agent.core.llm.client import (
    BaseLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
)
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime
from Agent.tool.registry import (
    DEFAULT_TOOL_NAMES,
    get_tool_functions,
    get_tool_schemas,
    list_tool_names,
)


GLM_KEY_PRESENT = bool(os.getenv("GLM_API_KEY"))
MOONSHOT_KEY_PRESENT = bool(os.getenv("MOONSHOT_API_KEY"))


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
    if preference == "moonshot":
        raise RuntimeError("Moonshot 模式被选择，但 Moonshot 客户端不可用。")
    return MockMoonshotClient(), "mock"


def build_agent(llm_preference: str, tool_names: List[str]) -> CodeReviewAgent:
    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)

    client, provider = create_llm_client(llm_preference)

    adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider)
    context_provider = ContextProvider()
    state = ConversationState()
    return CodeReviewAgent(adapter, runtime, context_provider, state)


def run_agent(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    stream_callback=None,
    tool_approver=None,
) -> str:
    diff_ctx = collect_diff_context()
    agent = build_agent(llm_preference, tool_names)
    augmented_prompt = f"{prompt}\n\n[Diff Summary]\n{diff_ctx.summary}"
    tools = cast(List[ToolDefinition], get_tool_schemas(tool_names))
    return asyncio.run(
        agent.run(
            augmented_prompt,
            files=diff_ctx.files,
            stream_observer=stream_callback,
            tools=tools,
            auto_approve_tools=tool_names if auto_approve else [],
            tool_approver=tool_approver,
        )
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
    if MOONSHOT_KEY_PRESENT:
        options.append("moonshot")
    options.append("mock")
    tk.OptionMenu(header_frame, model_var, *options).pack(side=tk.LEFT, padx=(4, 12))

    run_button = tk.Button(header_frame, text="Run Agent")
    run_button.pack(side=tk.RIGHT)

    tk.Label(root, text="Prompt").pack(anchor="w", padx=8, pady=(0, 0))
    prompt_box = scrolledtext.ScrolledText(root, height=6)
    prompt_box.insert(
        tk.END,
        "请审查下面的代码。在需要时调用 echo_tool (提示: tool:).\n",
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
        var = tk.BooleanVar(value=name in DEFAULT_TOOL_NAMES)
        tool_vars[name] = var
        tk.Checkbutton(
            tools_frame,
            text=name,
            variable=var,
        ).pack(anchor="w", padx=16, pady=(0, 2))

    tk.Label(root, text="Result").pack(anchor="w", padx=8, pady=(4, 0))
    result_box = scrolledtext.ScrolledText(root, height=12)
    result_box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()

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
        prompt_text: str, preference: str, names: List[str], auto_approve: bool
    ) -> None:
        def observer(event: Dict[str, Any]) -> None:
            event_queue.put({"type": "delta", "payload": event})

        try:
            result = run_agent(
                prompt_text,
                preference,
                names,
                auto_approve,
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
                text = payload.get("content_delta") or ""
                if text:
                    result_box.insert(tk.END, text)
                    result_box.see(tk.END)
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
            ),
            daemon=True,
        )
        thread.start()
        poll_queue()

    run_button.config(command=on_run)

    root.mainloop()


if __name__ == "__main__":
    main()
