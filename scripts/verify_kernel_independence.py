"""新内核独立性验证脚本

验证新内核是否能够：
1. 通过 Port 接口与 Agent/ 模块交互
2. 不直接导入 Agent/ 模块（除了适配器内部）
3. 成功初始化所有 Stages
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_port_imports():
    """测试 Port 接口导入"""
    print("✓ 测试 Port 接口导入...")
    try:
        from kernel.ports import (
            LLMClientPort,
            LLMFactoryPort,
            GitPort,
            DiffPort,
            ConversationPort,
            ToolRegistryPort,
            ToolRuntimePort,
            ToolPolicyPort,
            PromptPort,
            ContextPort,
            StreamPort,
        )
        print("  ✓ 所有 Port 接口导入成功")
        return True
    except Exception as e:
        print(f"  ✗ Port 接口导入失败: {e}")
        return False


def test_adapter_creation():
    """测试适配器创建"""
    print("\n✓ 测试适配器创建...")
    try:
        from kernel.infrastructure import (
            LegacyLLMFactory,
            LegacyGitAdapter,
            LegacyDiffAdapter,
            LegacyConversationAdapter,
            LegacyToolRegistry,
            LegacyToolRuntime,
            LegacyToolPolicy,
            LegacyPromptAdapter,
            LegacyContextAdapter,
            LegacyStreamAdapter,
        )
        
        # 创建适配器实例
        llm_factory = LegacyLLMFactory()
        git_adapter = LegacyGitAdapter()
        diff_adapter = LegacyDiffAdapter()
        conv_adapter = LegacyConversationAdapter()
        tool_registry = LegacyToolRegistry()
        tool_runtime = LegacyToolRuntime()
        tool_policy = LegacyToolPolicy()
        prompt_adapter = LegacyPromptAdapter()
        context_adapter = LegacyContextAdapter()
        stream_adapter = LegacyStreamAdapter()
        
        print("  ✓ 所有适配器创建成功")
        return True
    except Exception as e:
        print(f"  ✗ 适配器创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_stage_initialization():
    """测试 Stage 初始化"""
    print("\n✓ 测试 Stage 初始化...")
    try:
        from kernel.infrastructure import (
            LegacyLLMFactory,
            LegacyGitAdapter,
            LegacyDiffAdapter,
        )
        from kernel.application.stages.diff_stage import DiffStage
        from kernel.application.stages.llm_setup_stage import LLMSetupStage
        
        # 模拟 store 和 artifact_store
        class MockStore:
            def register_artifact(self, artifact):
                pass
        
        mock_store = MockStore()
        llm_factory = LegacyLLMFactory()
        git_port = LegacyGitAdapter()
        diff_port = LegacyDiffAdapter()
        
        # 创建 Stages
        diff_stage = DiffStage(
            store=mock_store,
            artifact_store=mock_store,
            git_port=git_port,
            diff_port=diff_port,
        )
        
        llm_setup_stage = LLMSetupStage(llm_factory=llm_factory)
        
        print("  ✓ DiffStage 初始化成功")
        print("  ✓ LLMSetupStage 初始化成功")
        return True
    except Exception as e:
        print(f"  ✗ Stage 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_kernel_independence():
    """检查内核独立性（检查是否有直接的 Agent/ 导入）"""
    print("\n✓ 检查内核独立性...")
    
    kernel_dir = project_root / "kernel"
    agent_imports = []
    
    # 排除适配器和测试文件
    exclude_patterns = [
        "infrastructure",  # 适配器允许导入 Agent/
        "test_",
        "__pycache__",
    ]
    
    for py_file in kernel_dir.rglob("*.py"):
        # 跳过排除的文件
        if any(pattern in str(py_file) for pattern in exclude_patterns):
            continue
        
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "from Agent" in line or "import Agent" in line:
                    agent_imports.append((py_file, i, line.strip()))
        except Exception:
            continue
    
    if agent_imports:
        print("  ⚠ 发现以下 Agent/ 导入（适配器外）：")
        for file, line_no, line in agent_imports[:10]:
            rel_path = file.relative_to(project_root)
            print(f"    {rel_path}:{line_no} - {line}")
        print(f"  总计: {len(agent_imports)} 处导入")
        return False
    else:
        print("  ✓ 内核代码（适配器外）无直接 Agent/ 导入")
        return True


def main():
    """主测试函数"""
    print("="*60)
    print("新内核独立性验证")
    print("="*60)
    
    results = {
        "Port 接口导入": test_port_imports(),
        "适配器创建": test_adapter_creation(),
        "Stage 初始化": test_stage_initialization(),
        "内核独立性": check_kernel_independence(),
    }
    
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 所有测试通过！新内核基本具备独立运行能力。")
    else:
        print("⚠️  部分测试失败，需要进一步调试。")
    print("="*60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
