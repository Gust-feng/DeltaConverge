"""规则解析测试工具GUI界面

使用tkinter创建的简单GUI界面，用于测试规则解析功能。

功能：
1. 默认测试数据
2. 检测工作区diff
3. JSON输入
4. 从文件读取输入
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from tkinter import Tk, Label, Button, Text, Entry, Frame, Radiobutton, IntVar, filedialog, messagebox, Scrollbar, Checkbutton
from tkinter.ttk import Progressbar

# 添加项目根目录到Python路径
sys.path.insert(0, "z:\\Agent代码审查")

from Agent.DIFF.rule.context_decision import build_rule_suggestion
from Agent.DIFF.rule.rule_lang_python import PythonRuleHandler
from Agent.DIFF.rule.rule_lang_typescript import TypeScriptRuleHandler
from Agent.DIFF.rule.rule_lang_go import GoRuleHandler
from Agent.DIFF.rule.rule_lang_java import JavaRuleHandler
from Agent.DIFF.rule.rule_lang_ruby import RubyRuleHandler

# 导入共享功能
from Agent.DIFF.rule.test_rule_parser import (
    get_handler,
    get_file_language,
    get_workspace_diff,
    extract_python_symbols,
    extract_typescript_symbols,
    extract_go_symbols,
    extract_java_symbols,
    extract_ruby_symbols,
    infer_tags,
    parse_diff_to_units
)

# 导入review_index构建功能
from Agent.DIFF.output_formatting import build_review_index
from Agent.DIFF.git_operations import DiffMode


class RuleParserGUI:
    """规则解析测试工具GUI类"""
    
    def __init__(self, master):
        """初始化GUI界面"""
        self.master = master
        master.title("规则解析测试工具")
        master.geometry("1000x700")
        master.resizable(True, True)
        
        # 设置字体和颜色
        self.font = ("Arial", 10)
        self.bg_color = "#f0f0f0"
        self.button_color = "#4CAF50"
        self.button_text_color = "white"
        self.error_color = "#f44336"
        self.warning_color = "#ff9800"
        self.info_color = "#2196F3"
        
        # 添加样式
        master.configure(bg=self.bg_color)
        
        # 初始化变量
        self.test_mode = IntVar(value=1)
        self.generate_review_index = IntVar(value=1)  # 默认生成review_index
        self.file_path = ""
        
        # 创建主框架
        self.main_frame = Frame(master, bg=self.bg_color, padx=10, pady=10)
        self.main_frame.pack(fill="both", expand=True)
        
        # 创建测试模式选择
        self.create_test_mode_frame()
        
        # 创建输入区域
        self.create_input_frame()
        
        # 创建按钮区域
        self.create_button_frame()
        
        # 创建输出区域
        self.create_output_frame()
        
        # 创建进度条
        self.progress = Progressbar(self.main_frame, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(pady=5, fill="x")
        self.progress.pack_forget()  # 初始隐藏
    
    def create_test_mode_frame(self):
        """创建测试模式选择框架"""
        mode_frame = Frame(self.main_frame, bg=self.bg_color)
        mode_frame.pack(fill="x", pady=5)
        
        Label(mode_frame, text="测试模式:", bg=self.bg_color, font=self.font).pack(anchor="w")
        
        # 创建单选按钮
        Radiobutton(mode_frame, text="默认测试数据", variable=self.test_mode, value=1, bg=self.bg_color, font=self.font).pack(anchor="w")
        Radiobutton(mode_frame, text="检测工作区diff", variable=self.test_mode, value=2, bg=self.bg_color, font=self.font).pack(anchor="w")
        Radiobutton(mode_frame, text="JSON输入", variable=self.test_mode, value=3, bg=self.bg_color, font=self.font).pack(anchor="w")
        Radiobutton(mode_frame, text="从文件读取", variable=self.test_mode, value=4, bg=self.bg_color, font=self.font).pack(anchor="w")
        
        # 添加生成review_index的复选框
        Checkbutton(mode_frame, text="生成最终发送给决策agent的数据(review_index)", variable=self.generate_review_index, bg=self.bg_color, font=self.font).pack(anchor="w", pady=5)
    
    def create_input_frame(self):
        """创建输入区域框架"""
        input_frame = Frame(self.main_frame, bg=self.bg_color)
        input_frame.pack(fill="x", pady=5)
        
        # JSON输入区域
        Label(input_frame, text="JSON输入:", bg=self.bg_color, font=self.font).pack(anchor="w")
        
        # 创建文本框和滚动条
        text_frame = Frame(input_frame)
        text_frame.pack(fill="x")
        
        self.json_text = Text(text_frame, height=10, font=self.font)
        scrollbar = Scrollbar(text_frame, command=self.json_text.yview)
        self.json_text.configure(yscrollcommand=scrollbar.set)
        
        self.json_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 文件选择区域
        file_frame = Frame(input_frame, bg=self.bg_color)
        file_frame.pack(fill="x", pady=5)
        
        self.file_entry = Entry(file_frame, font=self.font)
        self.file_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        Button(file_frame, text="浏览", command=self.browse_file, bg=self.button_color, fg=self.button_text_color, font=self.font).pack(side="right")
    
    def create_button_frame(self):
        """创建按钮区域框架"""
        button_frame = Frame(self.main_frame, bg=self.bg_color)
        button_frame.pack(fill="x", pady=5)
        
        # 创建按钮
        Button(button_frame, text="执行测试", command=self.run_test, bg=self.button_color, fg=self.button_text_color, font=self.font).pack(side="left", padx=5)
        Button(button_frame, text="清空输出", command=self.clear_output, bg="#f44336", fg=self.button_text_color, font=self.font).pack(side="left", padx=5)
        Button(button_frame, text="退出", command=self.master.quit, bg="#9e9e9e", fg=self.button_text_color, font=self.font).pack(side="right", padx=5)
    
    def create_output_frame(self):
        """创建输出区域框架"""
        output_frame = Frame(self.main_frame, bg=self.bg_color)
        output_frame.pack(fill="both", expand=True, pady=5)
        
        Label(output_frame, text="输出结果:", bg=self.bg_color, font=self.font).pack(anchor="w")
        
        # 创建文本框和滚动条
        text_frame = Frame(output_frame)
        text_frame.pack(fill="both", expand=True)
        
        self.output_text = Text(text_frame, height=20, font=self.font)
        scrollbar_y = Scrollbar(text_frame, command=self.output_text.yview)
        scrollbar_x = Scrollbar(text_frame, orient="horizontal", command=self.output_text.xview)
        self.output_text.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        
        self.output_text.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        
        # 设置文本框为只读
        self.output_text.config(state="disabled")
    
    def browse_file(self):
        """浏览文件"""
        filename = filedialog.askopenfilename(
            title="选择输入文件",
            filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
        )
        if filename:
            self.file_entry.delete(0, "end")
            self.file_entry.insert(0, filename)
            self.file_path = filename
    
    def append_output(self, text):
        """追加输出文本"""
        self.output_text.config(state="normal")
        self.output_text.insert("end", text + "\n")
        self.output_text.see("end")
        self.output_text.config(state="disabled")
        self.master.update_idletasks()
    
    def clear_output(self):
        """清空输出"""
        self.output_text.config(state="normal")
        self.output_text.delete(1.0, "end")
        self.output_text.config(state="disabled")
    
    def run_test(self):
        """执行测试"""
        # 清空输出
        self.clear_output()
        
        # 显示进度条
        self.progress.pack(pady=5, fill="x")
        self.progress["value"] = 10
        self.master.update_idletasks()
        
        # 在新线程中执行测试，避免GUI冻结
        threading.Thread(target=self._run_test_thread, daemon=True).start()
    
    def _run_test_thread(self):
        """测试线程"""
        try:
            self.append_output("=== 开始执行测试 ===")
            
            if self.test_mode.get() == 1:
                # 默认测试数据
                self.progress["value"] = 30
                self.master.update_idletasks()
                self.run_default_test()
            elif self.test_mode.get() == 2:
                # 检测工作区diff
                self.progress["value"] = 30
                self.master.update_idletasks()
                self.run_workspace_diff()
            elif self.test_mode.get() == 3:
                # JSON输入
                self.progress["value"] = 30
                self.master.update_idletasks()
                self.run_json_input()
            elif self.test_mode.get() == 4:
                # 从文件读取
                self.progress["value"] = 30
                self.master.update_idletasks()
                self.run_file_input()
            
            self.progress["value"] = 100
            self.master.update_idletasks()
            self.append_output("=== 测试执行完成 ===")
        except Exception as e:
            self.append_output(f"错误: {str(e)}")
            import traceback
            self.append_output(traceback.format_exc())
        finally:
            # 隐藏进度条
            self.progress.pack_forget()
            self.progress["value"] = 0
    
    def run_default_test(self):
        """运行默认测试数据"""
        self.append_output("使用默认测试数据")
        
        # 默认测试数据
        default_data = {
            "file_path": "src/migrations/0001_initial.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 20,
                "removed_lines": 5,
                "hunk_count": 1
            },
            "tags": [],
            "symbol": {
                "kind": "function",
                "name": "test_function",
                "start_line": 10,
                "end_line": 20
            }
        }
        
        metadata = self.process_unit(default_data)
        if metadata:
            self.save_log([metadata])
    
    def run_workspace_diff(self):
        """运行工作区diff检测"""
        self.append_output("正在检测工作区diff...")
        
        # 获取工作区diff
        diff_output = get_workspace_diff()
        if not diff_output:
            self.append_output("未检测到工作区变更")
            return
        
        # 解析diff
        units = parse_diff_to_units(diff_output)
        self.append_output(f"共检测到 {len(units)} 个文件变更")
        
        # 处理每个unit
        all_metadata = []
        for i, unit in enumerate(units, 1):
            self.append_output(f"\n=== 文件 {i}/{len(units)}: {unit.get('file_path')} ===")
            metadata = self.process_unit(unit)
            if metadata:
                all_metadata.append(metadata)
        
        # 保存日志
        self.save_log(all_metadata)
    
    def run_json_input(self):
        """运行JSON输入测试"""
        self.append_output("使用JSON输入")
        
        # 获取JSON输入
        json_text = self.json_text.get(1.0, "end").strip()
        if not json_text:
            messagebox.showerror("错误", "JSON输入不能为空")
            return
        
        try:
            input_data = json.loads(json_text)
            metadata = self.process_unit(input_data)
            if metadata:
                # 如果是列表，直接保存；否则保存为列表
                if isinstance(metadata, list):
                    self.save_log(metadata)
                else:
                    self.save_log([metadata])
        except json.JSONDecodeError as e:
            messagebox.showerror("错误", f"JSON格式错误: {str(e)}")
    
    def run_file_input(self):
        """运行文件输入测试"""
        self.append_output("从文件读取输入")
        
        file_path = self.file_entry.get().strip()
        if not file_path:
            messagebox.showerror("错误", "请选择输入文件")
            return
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                input_data = json.load(f)
            metadata = self.process_unit(input_data)
            if metadata:
                # 如果是列表，直接保存；否则保存为列表
                if isinstance(metadata, list):
                    self.save_log(metadata)
                else:
                    self.save_log([metadata])
        except Exception as e:
            messagebox.showerror("错误", f"读取文件错误: {str(e)}")
    
    def parse_diff_to_units(self, diff_output: str):
        """将git diff输出解析为Unit列表。"""
        # 使用共享功能
        return parse_diff_to_units(diff_output)
    
    def process_unit(self, unit):
        """处理单个unit"""
        # 如果输入是列表，递归处理每个unit
        if isinstance(unit, list):
            all_metadata = []
            for i, u in enumerate(unit, 1):
                self.append_output(f"\n=== 文件 {i}/{len(unit)}: {u.get('file_path', 'unknown')} ===")
                metadata = self.process_unit(u)
                if metadata:
                    all_metadata.append(metadata)
            # 保存日志
            self.save_log(all_metadata)
            return all_metadata
        
        self.append_output(f"输入数据: {json.dumps(unit, indent=2, ensure_ascii=False)}")
        
        # 获取语言
        language = unit.get("language", "python")
        
        # 1. 测试语言处理器
        self.append_output("\n1. 语言处理器测试:")
        handler_cls = get_handler(language)
        handler_result = None
        if handler_cls:
            handler = handler_cls()
            result = handler.match(unit)
            if result:
                handler_result = result.to_dict()
                self.append_output(f"   匹配结果: {json.dumps(handler_result, indent=2, ensure_ascii=False)}")
            else:
                self.append_output("   未匹配到语言规则")
        else:
            self.append_output(f"   未找到语言 '{language}' 的处理器")
        
        # 2. 测试完整规则建议
        self.append_output("\n2. 完整规则建议测试:")
        suggestion = build_rule_suggestion(unit)
        self.append_output(f"   规则建议: {json.dumps(suggestion, indent=2, ensure_ascii=False)}")
        
        # 3. 输出元数据
        self.append_output("\n3. 元数据输出:")
        metadata = {
            "file_path": unit.get("file_path", ""),
            "language": language,
            "rule_suggestion": suggestion,
            "total_changed": unit.get("metrics", {}).get("added_lines", 0) + unit.get("metrics", {}).get("removed_lines", 0),
            "change_type": unit.get("change_type", "modify"),
            "tags": unit.get("tags", []),
            "metrics": unit.get("metrics", {}),
            "symbol": unit.get("symbol", {})
        }
        self.append_output(f"   元数据: {json.dumps(metadata, indent=2, ensure_ascii=False)}")
        
        return metadata
    
    def save_log(self, metadata_list):
        """保存规则解析结果到log目录"""
        import os
        from datetime import datetime
        
        # 创建log目录
        log_dir = os.path.join(os.path.dirname(__file__), "log")
        os.makedirs(log_dir, exist_ok=True)
        
        # 生成日志文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"rule_parser_result_{timestamp}.json")
        
        # 保存日志
        try:
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "total_files": len(metadata_list),
                "files": metadata_list
            }
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
            self.append_output(f"\n日志已保存到: {log_file}")
        except Exception as e:
            self.append_output(f"\n保存日志失败: {str(e)}")
        
        # 生成review_index
        if self.generate_review_index.get() == 1:
            try:
                self.append_output("\n=== 生成review_index（发送给决策agent的数据） ===")
                
                # 构建review_index
                review_index = build_review_index(
                    metadata_list,
                    DiffMode.WORKING,  # 默认使用working模式
                    "main"  # 默认基础分支
                )
                
                # 显示review_index概览
                self.append_output(f"review_index概览:")
                self.append_output(f"  - 元数据: {json.dumps(review_index['review_metadata'], indent=2, ensure_ascii=False)}")
                self.append_output(f"  - 摘要: {json.dumps(review_index['summary'], indent=2, ensure_ascii=False)}")
                self.append_output(f"  - 审查单元数: {len(review_index['units'])}")
                self.append_output(f"  - 文件数: {len(review_index['files'])}")
                
                # 保存review_index到文件
                review_index_file = os.path.join(log_dir, f"review_index_{timestamp}.json")
                with open(review_index_file, "w", encoding="utf-8") as f:
                    json.dump(review_index, f, indent=2, ensure_ascii=False)
                self.append_output(f"\nreview_index已保存到: {review_index_file}")
                
                # 显示完整的review_index
                self.append_output(f"\n完整review_index数据:")
                self.append_output(json.dumps(review_index, indent=2, ensure_ascii=False))
                
            except Exception as e:
                self.append_output(f"\n生成review_index失败: {str(e)}")
                import traceback
                self.append_output(traceback.format_exc())
    
    def run_gui(self):
        """运行GUI"""
        self.master.mainloop()


if __name__ == "__main__":
    root = Tk()
    gui = RuleParserGUI(root)
    gui.run_gui()
