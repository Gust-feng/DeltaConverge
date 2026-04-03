"""内核端口接口定义

定义新内核与外部系统交互的抽象接口（Port）。
所有 Port 均为 Protocol 类型，支持依赖注入和适配器模式。
"""

# 存储接口
from .stores import ArtifactStore, ScanServicePort, SessionStore

# LLM 接口
from .llm import (
    LLMClientPort,
    LLMFactoryPort,
    LLMResponse,
    Message,
    MessageRole,
    StreamChunk,
    StreamObserver,
    ToolCall,
    ToolSpec,
)

# 流处理接口
from .stream import (
    StreamBuffer,
    StreamEvent,
    StreamEventType,
    StreamPort,
    StreamState,
)

# Git 接口
from .git import (
    CommitInfo,
    DiffHunk,
    DiffMode,
    DiffResult,
    FileChange,
    FileDiff,
    GitConfig,
    GitPort,
)

# Diff 上下文接口
from .diff import (
    ContextBundle,
    ContextLevel,
    DiffContext,
    DiffPort,
    DiffUnit,
)

# 对话状态接口
from .conversation import (
    ConversationConfig,
    ConversationPort,
    ConversationState,
)

# 工具系统接口
from .tool import (
    ApprovalMode,
    ToolCallResult,
    ToolCategory,
    ToolDefinition,
    ToolPolicy,
    ToolPolicyPort,
    ToolRegistryPort,
    ToolRuntimePort,
)

# 提示词接口
from .prompt import (
    PromptLimits,
    PromptPort,
    PromptStyle,
    PromptTemplate,
    PromptTemplateRegistry,
    ReviewPrompt,
    ReviewPromptConfig,
)

# 上下文管理接口
from .context import (
    CacheStrategy,
    ContextCachePort,
    ContextPort,
    ContextRequest,
    ContextResult,
    FileContext,
)

__all__ = [
    # Stores
    "ArtifactStore",
    "SessionStore",
    "ScanServicePort",
    # LLM
    "LLMClientPort",
    "LLMFactoryPort",
    "LLMResponse",
    "Message",
    "MessageRole",
    "StreamChunk",
    "StreamObserver",
    "ToolCall",
    "ToolSpec",
    # Stream
    "StreamBuffer",
    "StreamEvent",
    "StreamEventType",
    "StreamPort",
    "StreamState",
    # Git
    "CommitInfo",
    "DiffHunk",
    "DiffMode",
    "DiffResult",
    "FileChange",
    "FileDiff",
    "GitConfig",
    "GitPort",
    # Diff
    "ContextBundle",
    "ContextLevel",
    "DiffContext",
    "DiffPort",
    "DiffUnit",
    # Conversation
    "ConversationConfig",
    "ConversationPort",
    "ConversationState",
    # Tool
    "ApprovalMode",
    "ToolCallResult",
    "ToolCategory",
    "ToolDefinition",
    "ToolPolicy",
    "ToolPolicyPort",
    "ToolRegistryPort",
    "ToolRuntimePort",
    # Prompt
    "PromptLimits",
    "PromptPort",
    "PromptStyle",
    "PromptTemplate",
    "PromptTemplateRegistry",
    "ReviewPrompt",
    "ReviewPromptConfig",
    # Context
    "CacheStrategy",
    "ContextCachePort",
    "ContextPort",
    "ContextRequest",
    "ContextResult",
    "FileContext",
]
