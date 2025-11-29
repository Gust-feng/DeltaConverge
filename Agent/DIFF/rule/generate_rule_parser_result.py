import json
import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, "z:\\Agent代码审查")

from Agent.DIFF.rule.test_rule_parser import get_workspace_diff, parse_diff_to_units, parse_rule_json

def main():
    """生成规则解析结果并保存为JSON文件。"""
    # 检测工作区diff
    print("正在检测工作区diff...")
    diff_output = get_workspace_diff()
    if not diff_output:
        print("未检测到工作区变更")
        return
    
    # 解析diff为单元
    units = parse_diff_to_units(diff_output)
    print(f"共检测到 {len(units)} 个文件变更")
    
    # 处理每个单元
    all_metadata = []
    for unit in units:
        metadata = parse_rule_json(unit)
        all_metadata.append(metadata)
    
    # 输出最终结果
    final_output = {
        "total_files": len(all_metadata),
        "files": all_metadata
    }
    
    # 保存到文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"log/rule_parser_result_{timestamp}.json"
    
    os.makedirs("log", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
    
    print(f"结果已保存到: {output_file}")
    return final_output

if __name__ == "__main__":
    main()