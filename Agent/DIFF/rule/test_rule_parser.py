"""规则解析测试工具：独立运行规则解析，输出元数据。

用于测试和验证规则解析功能，无需完整执行整个系统链路。

使用方法：
1. 直接运行：python test_rule_parser.py
2. 提供JSON输入：python test_rule_parser.py --json '{"file_path": "test.py", "language": "python", ...}'
3. 从文件读取输入：python test_rule_parser.py --file input.json
4. 检测工作区diff：python test_rule_parser.py --workspace
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

# 添加项目根目录到Python路径
sys.path.insert(0, "z:\\Agent代码审查")

from Agent.DIFF.rule.context_decision import build_rule_suggestion
from Agent.DIFF.rule.rule_lang_python import PythonRuleHandler
from Agent.DIFF.rule.rule_lang_typescript import TypeScriptRuleHandler
from Agent.DIFF.rule.rule_lang_go import GoRuleHandler
from Agent.DIFF.rule.rule_lang_java import JavaRuleHandler
from Agent.DIFF.rule.rule_lang_ruby import RubyRuleHandler


def get_handler(language: str):
    """根据语言获取对应的规则处理器。"""
    handlers = {
        "python": PythonRuleHandler,
        "py": PythonRuleHandler,
        "typescript": TypeScriptRuleHandler,
        "javascript": TypeScriptRuleHandler,
        "ts": TypeScriptRuleHandler,
        "js": TypeScriptRuleHandler,
        "go": GoRuleHandler,
        "golang": GoRuleHandler,
        "java": JavaRuleHandler,
        "ruby": RubyRuleHandler,
        "rb": RubyRuleHandler,
    }
    return handlers.get(language.lower())


def get_file_language(file_path: str) -> str:
    """根据文件路径获取语言类型。"""
    ext = file_path.split(".")[-1].lower()
    language_map = {
        "py": "python",
        "ts": "typescript",
        "js": "javascript",
        "go": "go",
        "java": "java",
        "rb": "ruby",
        "yml": "yaml",
        "yaml": "yaml",
        "json": "json",
        "md": "markdown",
        "txt": "text",
    }
    return language_map.get(ext, "unknown")


def get_workspace_diff(include_staged: bool = True) -> str:
    """获取工作区的Git diff，包括暂存区。"""
    try:
        # 获取工作区变更
        result = subprocess.run(
            ["git", "diff", "--name-status", "--diff-filter=ACMRT"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True
        )
        diff_output = result.stdout
        
        # 如果包含暂存区，获取暂存区变更
        if include_staged:
            staged_result = subprocess.run(
                ["git", "diff", "--staged", "--name-status", "--diff-filter=ACMRT"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True
            )
            diff_output += staged_result.stdout
        
        return diff_output
    except subprocess.CalledProcessError as e:
        print(f"获取工作区diff失败: {e}")
        return ""
    except FileNotFoundError:
        print("未找到git命令，请确保已安装git")
        return ""


def extract_python_symbols(file_content: str) -> Dict[str, Any]:
    """提取Python文件中的符号信息。"""
    import ast
    
    symbols = {
        "functions": [],
        "classes": []
    }
    
    try:
        tree = ast.parse(file_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = {
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno
                }
                symbols["functions"].append(func_info)
                # 如果是第一个函数，设置为主要符号
                if "kind" not in symbols:
                    symbols.update({
                        "kind": "function",
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno
                    })
            elif isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno
                }
                symbols["classes"].append(class_info)
                # 如果还没有主要符号，设置类为主要符号
                if "kind" not in symbols:
                    symbols.update({
                        "kind": "class",
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno
                    })
    except SyntaxError:
        pass
    
    return symbols


def extract_typescript_symbols(file_content: str) -> Dict[str, Any]:
    """提取TypeScript文件中的符号信息。"""
    import re
    
    symbols = {
        "functions": [],
        "classes": [],
        "interfaces": []
    }
    
    # 提取函数
    func_pattern = re.compile(r'\b(function|const|let|var)\s+([a-zA-Z_]\w*)\s*=?\s*\([^)]*\)\s*=>?\s*\{')
    for match in func_pattern.finditer(file_content):
        func_info = {
            "name": match.group(2),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["functions"].append(func_info)
        # 如果是第一个函数，设置为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "function",
                "name": match.group(2),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取类
    class_pattern = re.compile(r'\bclass\s+([a-zA-Z_]\w*)\s*')
    for match in class_pattern.finditer(file_content):
        class_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["classes"].append(class_info)
        # 如果还没有主要符号，设置类为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "class",
                "name": match.group(1),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取接口
    interface_pattern = re.compile(r'\binterface\s+([a-zA-Z_]\w*)\s*')
    for match in interface_pattern.finditer(file_content):
        interface_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["interfaces"].append(interface_info)
    
    return symbols


def extract_go_symbols(file_content: str) -> Dict[str, Any]:
    """提取Go文件中的符号信息。"""
    import re
    
    symbols = {
        "functions": [],
        "structs": [],
        "interfaces": []
    }
    
    # 提取函数
    func_pattern = re.compile(r'\bfunc\s+(\([^)]*\s+)?([a-zA-Z_]\w*)\s*\([^)]*\)')
    for match in func_pattern.finditer(file_content):
        func_name = match.group(2)
        if func_name:
            func_info = {
                "name": func_name,
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            }
            symbols["functions"].append(func_info)
            # 如果是第一个函数，设置为主要符号
            if "kind" not in symbols:
                symbols.update({
                    "kind": "function",
                    "name": func_name,
                    "start_line": file_content[:match.start()].count('\n') + 1,
                    "end_line": file_content[:match.end()].count('\n') + 1
                })
    
    # 提取结构体
    struct_pattern = re.compile(r'\btype\s+([a-zA-Z_]\w*)\s+struct\s*\{')
    for match in struct_pattern.finditer(file_content):
        struct_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["structs"].append(struct_info)
        # 如果还没有主要符号，设置结构体为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "class",
                "name": match.group(1),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取接口
    interface_pattern = re.compile(r'\btype\s+([a-zA-Z_]\w*)\s+interface\s*\{')
    for match in interface_pattern.finditer(file_content):
        interface_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["interfaces"].append(interface_info)
    
    return symbols


def extract_java_symbols(file_content: str) -> Dict[str, Any]:
    """提取Java文件中的符号信息。"""
    import re
    
    symbols = {
        "classes": [],
        "methods": [],
        "interfaces": []
    }
    
    # 提取类
    class_pattern = re.compile(r'\b(class|enum)\s+([a-zA-Z_]\w*)\s*')
    for match in class_pattern.finditer(file_content):
        class_info = {
            "name": match.group(2),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["classes"].append(class_info)
        # 如果是第一个类，设置为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "class",
                "name": match.group(2),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取方法
    method_pattern = re.compile(r'\b(public|protected|private|static|final|abstract)\s+[^\s]+\s+([a-zA-Z_]\w*)\s*\([^)]*\)')
    for match in method_pattern.finditer(file_content):
        method_info = {
            "name": match.group(2),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["methods"].append(method_info)
        # 如果还没有主要符号，设置方法为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "function",
                "name": match.group(2),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取接口
    interface_pattern = re.compile(r'\binterface\s+([a-zA-Z_]\w*)\s*')
    for match in interface_pattern.finditer(file_content):
        interface_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["interfaces"].append(interface_info)
    
    return symbols


def extract_ruby_symbols(file_content: str) -> Dict[str, Any]:
    """提取Ruby文件中的符号信息。"""
    import re
    
    symbols = {
        "classes": [],
        "methods": [],
        "modules": []
    }
    
    # 提取类
    class_pattern = re.compile(r'\bclass\s+([a-zA-Z_]\w*)\s*')
    for match in class_pattern.finditer(file_content):
        class_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["classes"].append(class_info)
        # 如果是第一个类，设置为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "class",
                "name": match.group(1),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取方法
    method_pattern = re.compile(r'\bdef\s+([a-zA-Z_]\w*)\s*\([^)]*\)')
    for match in method_pattern.finditer(file_content):
        method_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["methods"].append(method_info)
        # 如果还没有主要符号，设置方法为主要符号
        if "kind" not in symbols:
            symbols.update({
                "kind": "function",
                "name": match.group(1),
                "start_line": file_content[:match.start()].count('\n') + 1,
                "end_line": file_content[:match.end()].count('\n') + 1
            })
    
    # 提取模块
    module_pattern = re.compile(r'\bmodule\s+([a-zA-Z_]\w*)\s*')
    for match in module_pattern.finditer(file_content):
        module_info = {
            "name": match.group(1),
            "start_line": file_content[:match.start()].count('\n') + 1,
            "end_line": file_content[:match.end()].count('\n') + 1
        }
        symbols["modules"].append(module_info)
    
    return symbols


def infer_tags(file_path: str, file_content: str, change_type: str, metrics: Dict[str, Any]) -> List[str]:
    """根据文件内容和变更类型推断标签。"""
    tags = []
    
    # 根据文件路径推断标签
    file_path_lower = file_path.lower()
    if "config" in file_path_lower or "setting" in file_path_lower or "settings" in file_path_lower:
        tags.append("config_file")
    if "test" in file_path_lower or "spec" in file_path_lower:
        tags.append("test_file")
    if "migrat" in file_path_lower:
        tags.append("migration_file")
    if "api" in file_path_lower or "controller" in file_path_lower or "route" in file_path_lower:
        tags.append("api_file")
    if "doc" in file_path_lower or "readme" in file_path_lower or "markdown" in file_path_lower:
        tags.append("doc_file")
    if "model" in file_path_lower or "entity" in file_path_lower or "schema" in file_path_lower:
        tags.append("model_file")
    if "service" in file_path_lower or "business" in file_path_lower:
        tags.append("service_file")
    if "util" in file_path_lower or "helper" in file_path_lower or "common" in file_path_lower:
        tags.append("util_file")
    if "middleware" in file_path_lower or "filter" in file_path_lower:
        tags.append("middleware_file")
    if "static" in file_path_lower or "asset" in file_path_lower or "resource" in file_path_lower:
        tags.append("static_file")
    
    # 根据文件内容推断标签
    if file_content:
        # 导入相关标签
        if "import" in file_content:
            tags.append("has_imports")
        if "import" in file_content and len(file_content.split("\n")) < 20 and len([line for line in file_content.split("\n") if line.strip().startswith("import") or line.strip().startswith("from")]) > len(file_content.split("\n")) * 0.5:
            tags.append("only_imports")
        
        # 注释相关标签
        if "#" in file_content:
            tags.append("has_comments")
        if "#" in file_content and len([line for line in file_content.split("\n") if line.strip().startswith("#")]) > len(file_content.split("\n")) * 0.5:
            tags.append("only_comments")
        
        # 日志相关标签
        if "print" in file_content or "log" in file_content or "logger" in file_content:
            tags.append("has_logging")
        
        # 测试相关标签
        if "assert" in file_content or "test" in file_content.lower() or "spec" in file_content.lower():
            tags.append("has_tests")
        
        # 配置相关标签
        if "config" in file_content.lower() or "setting" in file_content.lower() or "env" in file_content.lower():
            tags.append("has_config")
        
        # 数据库相关标签
        if "db" in file_content.lower() or "database" in file_content.lower() or "sql" in file_content.lower() or "orm" in file_content.lower():
            tags.append("has_database")
        
        # 网络相关标签
        if "http" in file_content.lower() or "request" in file_content.lower() or "response" in file_content.lower() or "api" in file_content.lower():
            tags.append("has_network")
        
        # 安全相关标签
        if "auth" in file_content.lower() or "security" in file_content.lower() or "password" in file_content.lower() or "token" in file_content.lower():
            tags.append("has_security")
    
    # 根据变更类型推断标签
    if change_type == "add":
        tags.append("new_file")
    elif change_type == "delete":
        tags.append("deleted_file")
    elif change_type == "modify":
        tags.append("modified_file")
    elif change_type == "rename":
        tags.append("renamed_file")
    
    # 根据变更行数推断标签
    total_changed = metrics.get("added_lines", 0) + metrics.get("removed_lines", 0)
    if total_changed > 200:
        tags.append("extra_large_change")
    elif total_changed > 100:
        tags.append("large_change")
    elif total_changed > 50:
        tags.append("medium_change")
    elif total_changed < 10:
        tags.append("small_change")
    elif total_changed < 5:
        tags.append("tiny_change")
    
    # 根据变更行数比例推断标签
    added_lines = metrics.get("added_lines", 0)
    removed_lines = metrics.get("removed_lines", 0)
    if added_lines > removed_lines * 2:
        tags.append("mostly_added")
    elif removed_lines > added_lines * 2:
        tags.append("mostly_removed")
    
    return list(set(tags))  # 去重


def parse_diff_to_units(diff_output: str) -> List[Dict[str, Any]]:
    """将git diff输出解析为Unit列表。"""
    units = []
    processed_files = set()  # 用于去重
    file_changes = {}
    
    # 首先收集所有文件的变更信息，处理重复文件
    for line in diff_output.strip().split("\n"):
        if not line:
            continue
        
        # 每行格式：状态 文件名
        status, file_path = line.split("\t", 1)
        
        # 记录文件的最高优先级状态（A > M > R > C > T）
        if file_path not in file_changes:
            file_changes[file_path] = status
        else:
            # 状态优先级：A > M > R > C > T
            current_status = file_changes[file_path]
            priority = {"A": 5, "M": 4, "R": 3, "C": 2, "T": 1}
            if priority.get(status, 0) > priority.get(current_status, 0):
                file_changes[file_path] = status
    
    # 处理每个文件
    for file_path, status in file_changes.items():
        # 确定变更类型
        change_type_map = {
            "A": "add",
            "C": "copy",
            "M": "modify",
            "R": "rename",
            "T": "type_change"
        }
        change_type = change_type_map.get(status, "modify")
        
        # 获取详细的diff信息
        try:
            # 对于不同的变更类型，使用不同的git diff命令
            if status == "A":
                # 新增文件，使用git show获取内容
                diff_detail = subprocess.run(
                    ["git", "show", f":{file_path}"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True
                )
                # 新增文件的所有行都是新增行
                stdout = diff_detail.stdout or ""
                added_lines = len([line for line in stdout.split("\n") if line.strip()])  # 只计算非空行
                removed_lines = 0
                hunk_count = 1
            else:
                # 先尝试工作区diff
                diff_detail = subprocess.run(
                    ["git", "diff", file_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True
                )
                stdout = diff_detail.stdout or ""
                
                # 如果工作区没有变更，尝试暂存区
                if not stdout or stdout.count("\n@@") == 0:
                    diff_detail = subprocess.run(
                        ["git", "diff", "--staged", file_path],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        check=True
                    )
                    stdout = diff_detail.stdout or ""
                
                # 计算变更行数
                added_lines = stdout.count("\n+") - stdout.count("\n+++")
                removed_lines = stdout.count("\n-") - stdout.count("\n---")
                hunk_count = stdout.count("\n@@")
            
            # 提取文件内容以获取符号信息
            file_content = ""
            if status == "A":
                # 新增文件，使用之前获取的内容
                file_content = stdout
            else:
                # 已存在文件，使用git show获取当前内容
                try:
                    file_content_result = subprocess.run(
                        ["git", "show", f"HEAD:{file_path}"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        check=True
                    )
                    file_content = file_content_result.stdout or ""
                except subprocess.CalledProcessError:
                    # 如果无法获取文件内容，使用空字符串
                    file_content = ""
            
            # 提取符号信息
            symbol = {}
            language = get_file_language(file_path)
            if file_content:
                if language == "python":
                    symbol = extract_python_symbols(file_content)
                elif language in ["typescript", "javascript"]:
                    symbol = extract_typescript_symbols(file_content)
                elif language == "go":
                    symbol = extract_go_symbols(file_content)
                elif language == "java":
                    symbol = extract_java_symbols(file_content)
                elif language == "ruby":
                    symbol = extract_ruby_symbols(file_content)
            
            # 推断标签
            metrics_dict = {
                "added_lines": added_lines,
                "removed_lines": removed_lines,
                "hunk_count": hunk_count
            }
            tags = infer_tags(file_path, file_content, change_type, metrics_dict)
            
            # 创建Unit
            unit = {
                "file_path": file_path,
                "language": language,
                "change_type": change_type,
                "metrics": metrics_dict,
                "tags": tags,
                "symbol": symbol
            }
            units.append(unit)
            
        except subprocess.CalledProcessError:
            # 如果仍然无法获取，创建基本Unit
            metrics_dict = {
                "added_lines": 0,
                "removed_lines": 0,
                "hunk_count": 0
            }
            tags = infer_tags(file_path, "", change_type, metrics_dict)
            unit = {
                "file_path": file_path,
                "language": get_file_language(file_path),
                "change_type": change_type,
                "metrics": metrics_dict,
                "tags": tags,
                "symbol": {}
            }
            units.append(unit)
        except UnicodeDecodeError:
            # 处理编码错误
            metrics_dict = {
                "added_lines": 0,
                "removed_lines": 0,
                "hunk_count": 0
            }
            tags = infer_tags(file_path, "", change_type, metrics_dict)
            unit = {
                "file_path": file_path,
                "language": get_file_language(file_path),
                "change_type": change_type,
                "metrics": metrics_dict,
                "tags": tags,
                "symbol": {}
            }
            units.append(unit)
    
    return units


def parse_rule_json(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析规则JSON并输出元数据。"""
    # 获取语言
    language = input_data.get("language", "python")
    
    # 1. 测试语言处理器
    handler_cls = get_handler(language)
    if handler_cls:
        handler = handler_cls()
        result = handler.match(input_data)
        handler_result = result.to_dict() if result else None
    else:
        handler_result = None
    
    # 2. 测试完整规则建议
    suggestion = build_rule_suggestion(input_data)
    
    # 3. 输出元数据
    metadata = {
        "file_path": input_data.get("file_path", ""),
        "language": language,
        "rule_suggestion": suggestion,
        "total_changed": input_data.get("metrics", {}).get("added_lines", 0) + input_data.get("metrics", {}).get("removed_lines", 0),
        "change_type": input_data.get("change_type", "modify"),
        "tags": input_data.get("tags", []),
        "metrics": input_data.get("metrics", {}),
        "symbol": input_data.get("symbol", {}),
        "handler_result": handler_result
    }
    
    return metadata


def process_units(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """处理多个Unit，输出元数据。"""
    print("=== 规则解析测试 ===")
    print(f"共检测到 {len(units)} 个文件变更")
    print()
    
    all_metadata = []
    
    for i, unit in enumerate(units, 1):
        print(f"=== 文件 {i}/{len(units)}: {unit.get('file_path')} ===")
        print(f"输入数据: {json.dumps(unit, indent=2, ensure_ascii=False)}")
        print()
        
        # 处理单个Unit
        metadata = parse_rule_json(unit)
        
        # 打印结果
        print("1. 语言处理器测试:")
        if metadata["handler_result"]:
            print(f"   匹配结果: {json.dumps(metadata['handler_result'], indent=2, ensure_ascii=False)}")
        else:
            print("   未匹配到语言规则")
        print()
        
        print("2. 完整规则建议测试:")
        print(f"   规则建议: {json.dumps(metadata['rule_suggestion'], indent=2, ensure_ascii=False)}")
        print()
        
        print("3. 元数据输出:")
        # 移除handler_result，避免重复输出
        metadata_simple = {k: v for k, v in metadata.items() if k != "handler_result"}
        print(f"   元数据: {json.dumps(metadata_simple, indent=2, ensure_ascii=False)}")
        print()
        
        all_metadata.append(metadata)
    
    return all_metadata


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="规则解析测试工具")
    parser.add_argument("--json", type=str, help="JSON格式的输入数据")
    parser.add_argument("--file", type=str, help="包含JSON输入数据的文件路径")
    parser.add_argument("--workspace", action="store_true", help="检测工作区的Git diff")
    args = parser.parse_args()
    
    units = []
    
    if args.workspace:
        # 检测工作区diff
        print("正在检测工作区diff...")
        diff_output = get_workspace_diff()
        if diff_output:
            units = parse_diff_to_units(diff_output)
        else:
            print("未检测到工作区变更")
            return
    elif args.json:
        # 单个JSON输入
        input_data = json.loads(args.json)
        units = [input_data]
    elif args.file:
        # 从文件读取
        with open(args.file, "r", encoding="utf-8") as f:
            input_data = json.load(f)
        units = [input_data]
    else:
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
        units = [default_data]
    
    # 处理所有Unit
    all_metadata = process_units(units)
    
    # 输出最终结果
    print("=== 最终输出 ===")
    final_output = {
        "total_files": len(all_metadata),
        "files": all_metadata
    }
    print(json.dumps(final_output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
