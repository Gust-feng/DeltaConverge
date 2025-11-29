#!/usr/bin/env python3
"""IntentAgent测试GUI：用于测试和调试IntentAgent的轻量级GUI工具。"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import threading
import asyncio
import subprocess
import re
from typing import Dict, Any, Optional, List

# 添加项目根目录到Python路径
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Agent.agents.intent_agent import IntentAgent
from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.state.conversation import ConversationState


class IntentAgentGUI:
    """IntentAgent测试GUI类。"""

    def __init__(self, root: tk.Tk):
        """初始化GUI。"""
        self.root = root
        self.root.title("IntentAgent测试工具")
        self.root.geometry("1000x700")
        self.root.minsize(800, 600)

        # 初始化IntentAgent相关组件
        self.llm_adapter = None
        self.intent_agent = None
        self.is_running = False

        # 创建主布局
        self.create_main_layout()
        
        # 初始化IntentAgent
        self.init_intent_agent()

    def create_main_layout(self):
        """创建主布局。"""
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 创建标题
        title_label = ttk.Label(main_frame, text="IntentAgent测试工具", font=('Arial', 16, 'bold'))
        title_label.pack(pady=10)

        # 创建输入输出容器
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # 创建左侧输入区域
        input_frame = ttk.LabelFrame(content_frame, text="项目概览输入", padding="10")
        input_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # 创建输入文本框
        input_scroll = ttk.Scrollbar(input_frame)
        self.input_text = tk.Text(input_frame, wrap=tk.WORD, yscrollcommand=input_scroll.set, height=15)
        input_scroll.config(command=self.input_text.yview)
        input_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.input_text.pack(fill=tk.BOTH, expand=True)

        # 创建输入控制按钮
        input_buttons_frame = ttk.Frame(input_frame)
        input_buttons_frame.pack(fill=tk.X, pady=10)

        load_button = ttk.Button(input_buttons_frame, text="加载文件", command=self.load_from_file)
        load_button.pack(side=tk.LEFT, padx=(0, 10))

        clear_button = ttk.Button(input_buttons_frame, text="清空", command=self.clear_all)
        clear_button.pack(side=tk.LEFT)

        # 创建右侧输出区域
        output_frame = ttk.LabelFrame(content_frame, text="IntentAgent输出", padding="10")
        output_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # 创建输出文本框
        output_scroll = ttk.Scrollbar(output_frame)
        self.output_text = tk.Text(output_frame, wrap=tk.WORD, yscrollcommand=output_scroll.set, height=30)
        output_scroll.config(command=self.output_text.yview)
        output_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.config(state=tk.DISABLED)

        # 创建运行按钮
        run_frame = ttk.Frame(main_frame)
        run_frame.pack(fill=tk.X, pady=10)

        self.run_button = ttk.Button(run_frame, text="运行IntentAgent", command=self.run_intent_agent, style="Accent.TButton")
        self.run_button.pack(side=tk.RIGHT)

        # 创建样式
        style = ttk.Style()
        style.configure("Accent.TButton", foreground="white", background="#0078d7")

    def init_intent_agent(self):
        """初始化IntentAgent。"""
        try:
            # 初始化LLMAdapter（使用正确的方式）
            from Agent.core.api.factory import LLMFactory
            from Agent.core.stream.stream_processor import StreamProcessor
            from Agent.core.adapter.llm_adapter import OpenAIAdapter
            
            # 创建LLM客户端
            client, provider_name = LLMFactory.create(preference="auto", trace_id="intent-agent-gui")
            
            # 创建StreamProcessor
            stream_processor = StreamProcessor()
            
            # 初始化LLMAdapter（使用具体实现类）
            self.llm_adapter = OpenAIAdapter(client, stream_processor, provider_name)
            
            # 初始化IntentAgent
            self.intent_agent = IntentAgent(self.llm_adapter)
            self.append_output("IntentAgent初始化成功！\n")
            
            # 自动收集项目数据
            self.auto_collect_project_data()
        except Exception as e:
            self.append_output(f"IntentAgent初始化失败：{str(e)}\n")
            messagebox.showerror("初始化失败", f"无法初始化IntentAgent：{str(e)}")
    
    def run_command(self, cmd: List[str], cwd: str = None) -> str:
        """运行命令并返回输出。"""
        try:
            # 使用UTF-8编码确保中文路径正确处理
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"命令执行失败：{e.stderr.strip()}"
        except Exception as e:
            return f"运行命令时发生错误：{str(e)}"
    
    def get_git_root(self, cwd: str = None) -> Optional[str]:
        """获取Git仓库根目录。"""
        result = self.run_command(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
        if not result.startswith("命令执行失败"):
            return result
        return None
    
    def get_file_list(self, root_dir: str) -> List[str]:
        """获取项目文件列表。"""
        file_list = []
        # 确保root_dir使用正确的编码
        root_dir = os.path.abspath(root_dir)
        
        for root, dirs, files in os.walk(root_dir):
            # 过滤掉一些常见的非代码目录
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'venv', '.idea', '.vscode', 'node_modules']]
            
            for file in files:
                # 过滤掉一些常见的非代码文件
                if file.endswith(('.pyc', '.pyo', '.o', '.a', '.so', '.dll', '.exe', '.zip', '.tar.gz', '.tar.bz2', '.7z')):
                    continue
                
                # 获取相对路径，确保中文路径正确处理
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, root_dir)
                # 确保路径使用正斜杠，便于JSON处理
                rel_path = rel_path.replace('\\', '/')
                file_list.append(rel_path)
        
        return file_list
    
    def get_file_hierarchy(self, root_dir: str) -> Dict[str, Any]:
        """获取项目文件层级结构。"""
        hierarchy = {}
        # 确保root_dir使用正确的编码
        root_dir = os.path.abspath(root_dir)
        
        def build_hierarchy(current_dir: str, parent_dict: Dict[str, Any]):
            try:
                # 使用os.scandir替代os.listdir，更好地处理编码问题
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        item = entry.name
                        item_path = entry.path
                        
                        # 过滤掉一些常见的非代码目录
                        if entry.is_dir():
                            if item in ['.git', '__pycache__', '.venv', 'venv', '.idea', '.vscode', 'node_modules']:
                                continue
                            parent_dict[item] = {}
                            build_hierarchy(item_path, parent_dict[item])
                        else:
                            # 只记录重要的文件类型
                            if item.endswith(('.py', '.md', '.txt', '.json', '.yaml', '.yml', '.ini', '.cfg')):
                                parent_dict[item] = "file"
            except PermissionError:
                pass
            except UnicodeDecodeError:
                # 处理文件名编码错误
                pass
        
        build_hierarchy(root_dir, hierarchy)
        return hierarchy
    
    def get_root_md_files(self, root_dir: str) -> List[str]:
        """获取根目录下的所有md文件名。"""
        md_files = []
        try:
            # 确保root_dir使用正确的编码
            root_dir = os.path.abspath(root_dir)
            
            # 使用os.scandir替代os.listdir，更好地处理编码问题
            with os.scandir(root_dir) as entries:
                for entry in entries:
                    if entry.is_file() and entry.name.endswith('.md'):
                        md_files.append(entry.name)
        except PermissionError:
            pass
        except UnicodeDecodeError:
            # 处理文件名编码错误
            pass
        return md_files
    
    def get_readme_summary(self, root_dir: str) -> str:
        """获取README文件摘要。"""
        readme_files = ['README.md', 'README.rst', 'README.txt', 'readme.md', 'readme.rst', 'readme.txt']
        
        for readme_file in readme_files:
            readme_path = os.path.join(root_dir, readme_file)
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # 提取前500个字符作为摘要
                        return content[:500] + '...' if len(content) > 500 else content
                except Exception as e:
                    return f"无法读取README文件：{str(e)}"
        
        return "未找到README文件"
    
    def get_recent_commits(self, root_dir: str, count: int = 5) -> List[Dict[str, str]]:
        """获取最近的commit信息。"""
        cmd = ["git", "log", f"--pretty=format:%H|%an|%ad|%s", f"-{count}", "--date=iso"]
        result = self.run_command(cmd, cwd=root_dir)
        
        if result.startswith("命令执行失败"):
            return []
        
        commits = []
        for line in result.split('\n'):
            if line:
                parts = line.split('|')
                if len(parts) == 4:
                    commits.append({
                        "hash": parts[0],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3]
                    })
        
        return commits
    
    def auto_collect_project_data(self):
        """自动收集项目数据。"""
        self.append_output("\n正在自动收集项目数据...\n")
        
        # 在新线程中执行数据收集，避免阻塞GUI
        threading.Thread(target=self._collect_project_data_thread, daemon=True).start()
    
    def _collect_project_data_thread(self):
        """在后台线程中收集项目数据。"""
        # 尝试检测最近的Git仓库
        git_root = self.detect_recent_git_repo()
        if git_root:
            self.root.after(0, self.append_output, f"检测到Git仓库：{git_root}\n")
            
            # 获取文件列表（限制深度为3，避免大型项目卡顿）
            file_list = self.get_file_list(git_root)
            self.root.after(0, self.append_output, f"找到 {len(file_list)} 个文件\n")
            
            # 获取README摘要
            readme_summary = self.get_readme_summary(git_root)
            self.root.after(0, self.append_output, f"README摘要：{readme_summary[:100]}...\n")
            
            # 获取最近的commit信息
            recent_commits = self.get_recent_commits(git_root)
            self.root.after(0, self.append_output, f"最近 {len(recent_commits)} 个commit\n")
            
            # 获取文件层级结构（限制深度为3）
            file_hierarchy = self.get_file_hierarchy(git_root)
            self.root.after(0, self.append_output, f"文件层级结构已生成\n")
            
            # 获取根目录下的md文件
            root_md_files = self.get_root_md_files(git_root)
            self.root.after(0, self.append_output, f"根目录下找到 {len(root_md_files)} 个md文件：{', '.join(root_md_files)}\n")
            
            # 构建项目概览数据，限制输出大小
            project_overview = {
                "git_root": git_root,
                "file_list": file_list[:15],  # 只取前15个文件
                "file_count": len(file_list),
                "file_hierarchy": file_hierarchy,
                "root_md_files": root_md_files,
                "readme_summary": readme_summary[:300],  # 限制README摘要长度
                "recent_commits": recent_commits
            }
            
            # 序列化JSON，避免阻塞GUI
            try:
                json_data = json.dumps(project_overview, ensure_ascii=False, indent=2)
                self.root.after(0, self.input_text.delete, 1.0, tk.END)
                self.root.after(0, self.input_text.insert, tk.END, json_data)
                self.root.after(0, self.append_output, "项目数据收集完成！\n")
            except Exception as e:
                self.root.after(0, self.append_output, f"JSON序列化失败：{str(e)}\n")
        else:
            self.root.after(0, self.append_output, "未检测到Git仓库\n")
            # 提供选择Git仓库的选项
            self.root.after(0, self._ask_select_repo)
    
    def _ask_select_repo(self):
        """询问用户是否选择Git仓库。"""
        if messagebox.askyesno("提示", "未检测到Git仓库，是否手动选择？"):
            git_root = filedialog.askdirectory(title="选择Git仓库目录")
            if git_root and self.get_git_root(git_root):
                # 重新收集数据
                self.auto_collect_project_data()
    
    def detect_recent_git_repo(self) -> Optional[str]:
        """检测最近的Git仓库。"""
        # 限制检测目录数量，避免卡顿
        check_dirs = []
        
        # 1. 首先检查当前运行目录
        current_dir = os.getcwd()
        check_dirs.append(current_dir)
        
        # 2. 检查当前目录的父目录
        parent_dir = os.path.dirname(current_dir)
        check_dirs.append(parent_dir)
        
        # 3. 检查程序所在目录
        app_dir = os.path.dirname(os.path.abspath(__file__))
        check_dirs.append(app_dir)
        
        # 4. 检查程序目录的父目录
        app_parent_dir = os.path.dirname(app_dir)
        check_dirs.append(app_parent_dir)
        
        # 遍历检查目录
        for check_dir in check_dirs:
            self.root.after(0, self.append_output, f"检查目录：{check_dir}\n")
            git_root = self.get_git_root(check_dir)
            if git_root:
                return git_root
        
        return None
    
    def get_file_list(self, root_dir: str) -> List[str]:
        """获取项目文件列表，限制深度为3。"""
        file_list = []
        # 确保root_dir使用正确的编码
        root_dir = os.path.abspath(root_dir)
        
        for root, dirs, files in os.walk(root_dir):
            # 计算当前深度
            depth = root[len(root_dir):].count(os.sep)
            if depth > 2:  # 限制深度为3（0-based）
                continue
                
            # 过滤掉一些常见的非代码目录
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', '.venv', 'venv', '.idea', '.vscode', 'node_modules']]
            
            for file in files:
                # 过滤掉一些常见的非代码文件
                if file.endswith(('.pyc', '.pyo', '.o', '.a', '.so', '.dll', '.exe', '.zip', '.tar.gz', '.tar.bz2', '.7z')):
                    continue
                
                # 获取相对路径，确保中文路径正确处理
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, root_dir)
                # 确保路径使用正斜杠，便于JSON处理
                rel_path = rel_path.replace('\\', '/')
                file_list.append(rel_path)
        
        return file_list
    
    def get_file_hierarchy(self, root_dir: str) -> Dict[str, Any]:
        """获取项目文件层级结构，限制深度为3。"""
        hierarchy = {}
        # 确保root_dir使用正确的编码
        root_dir = os.path.abspath(root_dir)
        
        def build_hierarchy(current_dir: str, parent_dict: Dict[str, Any], depth: int = 0):
            if depth > 2:  # 限制深度为3（0-based）
                return
                
            try:
                # 使用os.scandir替代os.listdir，更好地处理编码问题
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        item = entry.name
                        item_path = entry.path
                        
                        # 过滤掉一些常见的非代码目录
                        if entry.is_dir():
                            if item in ['.git', '__pycache__', '.venv', 'venv', '.idea', '.vscode', 'node_modules']:
                                continue
                            parent_dict[item] = {}
                            build_hierarchy(item_path, parent_dict[item], depth + 1)
                        else:
                            # 只记录重要的文件类型
                            if item.endswith(('.py', '.md', '.txt', '.json', '.yaml', '.yml', '.ini', '.cfg')):
                                parent_dict[item] = "file"
            except PermissionError:
                pass
            except UnicodeDecodeError:
                # 处理文件名编码错误
                pass
        
        build_hierarchy(root_dir, hierarchy)
        return hierarchy

    def load_from_file(self):
        """从文件加载项目概览数据。"""
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="选择项目概览JSON文件"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 验证JSON格式
                    json.loads(content)
                    self.input_text.delete(1.0, tk.END)
                    self.input_text.insert(tk.END, content)
                    self.append_output(f"已加载文件：{file_path}\n")
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON格式错误", f"文件不是有效的JSON格式：{str(e)}")
            except Exception as e:
                messagebox.showerror("加载失败", f"无法加载文件：{str(e)}")

    def clear_all(self):
        """清空输入和输出。"""
        self.input_text.delete(1.0, tk.END)
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete(1.0, tk.END)
        self.output_text.config(state=tk.DISABLED)

    def append_output(self, text: str):
        """向输出文本框添加内容。"""
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def run_intent_agent(self):
        """运行IntentAgent。"""
        if self.is_running:
            messagebox.showinfo("提示", "IntentAgent正在运行中，请稍候...")
            return

        # 获取输入内容
        input_content = self.input_text.get(1.0, tk.END).strip()
        if not input_content:
            messagebox.showwarning("警告", "请先输入项目概览数据！")
            return

        try:
            # 验证JSON格式
            intent_input = json.loads(input_content)
            self.append_output("\n" + "="*50 + "\n")
            self.append_output("正在运行IntentAgent...\n")
            self.append_output(f"输入数据：\n{json.dumps(intent_input, ensure_ascii=False, indent=2)}\n\n")
            
            # 禁用运行按钮
            self.run_button.config(state=tk.DISABLED)
            self.is_running = True
            
            # 在新线程中运行IntentAgent
            thread = threading.Thread(target=self._run_intent_agent_thread, args=(intent_input,))
            thread.daemon = True
            thread.start()
            
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON格式错误", f"输入不是有效的JSON格式：{str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"运行IntentAgent时发生错误：{str(e)}")
            self.run_button.config(state=tk.NORMAL)
            self.is_running = False

    def _run_intent_agent_thread(self, intent_input: Dict[str, Any]):
        """在线程中运行IntentAgent。"""
        try:
            # 流式输出缓冲区，避免频繁更新GUI
            content_buffer = []  # 正式内容缓冲区
            reasoning_buffer = []  # 思考内容缓冲区
            buffer_lock = threading.Lock()
            
            # 创建流式输出观察者
            def stream_observer(delta_dict):
                if isinstance(delta_dict, dict):
                    # 分别提取正式内容和思考内容
                    content_delta = delta_dict.get("content_delta", "")
                    reasoning_delta = delta_dict.get("reasoning_delta", "")
                    
                    # 处理思考内容
                    if reasoning_delta:
                        with buffer_lock:
                            reasoning_buffer.append(reasoning_delta)
                            # 只在思考内容开始时添加一次"[思考]"标签
                            if len(reasoning_buffer) == 1:
                                self.root.after(0, self.append_output, f"[思考] {reasoning_delta}")
                            else:
                                self.root.after(0, self.append_output, reasoning_delta)
                    
                    # 处理正式内容
                    if content_delta:
                        with buffer_lock:
                            content_buffer.append(content_delta)
                            # 当缓冲区达到一定大小或包含换行符时，更新GUI
                            if len(''.join(content_buffer)) > 50 or '\n' in content_delta:
                                self.root.after(0, self._flush_content_buffer, content_buffer.copy())
                                content_buffer.clear()
            
            # 运行IntentAgent
            result = asyncio.run(self.intent_agent.run(intent_input, stream=True, observer=stream_observer))
            
            # 确保缓冲区中的内容全部输出
            with buffer_lock:
                if content_buffer:
                    self.root.after(0, self._flush_content_buffer, content_buffer.copy())
                    content_buffer.clear()
            
            self.root.after(0, self.append_output, f"\n\nIntentAgent运行完成！\n")
            
            # 显示最终结果，明确区分思考内容和正式内容
            self.root.after(0, self.append_output, f"\n{'='*50}\n")
            self.root.after(0, self.append_output, f"【最终结果】\n")
            self.root.after(0, self.append_output, f"\n正式回复内容（将添加到系统提示词）：\n")
            self.root.after(0, self.append_output, f"{result}\n")
            self.root.after(0, self.append_output, f"{'='*50}\n")
        except Exception as e:
            self.root.after(0, messagebox.showerror, "运行错误", f"运行IntentAgent时发生错误：{str(e)}")
            self.root.after(0, self.append_output, f"\n\n运行错误：{str(e)}\n")
        finally:
            self.root.after(0, self.run_button.config, {'state': tk.NORMAL})
            self.root.after(0, setattr, self, 'is_running', False)
    
    def _flush_content_buffer(self, buffer: List[str]):
        """刷新正式内容缓冲区到GUI。"""
        if buffer:
            try:
                content = ''.join(buffer)
                self.append_output(content)
            except Exception as e:
                # 处理连接错误，逐个输出
                for item in buffer:
                    self.append_output(str(item))


def main():
    """主函数。"""
    root = tk.Tk()
    app = IntentAgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
