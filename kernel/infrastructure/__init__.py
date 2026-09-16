from .persistence import FileArtifactStore, SQLiteKernelStore, utc_now
from .scan import (
    LegacyScanCacheSnapshot,
    build_issues_by_severity,
    build_linked_payload,
    build_scan_artifact_payload,
    build_scan_result,
    build_scan_summary,
    is_scan_complete,
    read_legacy_scan_cache,
    wait_for_scan_completion,
)

# Legacy adapters
from .llm_adapter import LegacyLLMClient, LegacyLLMFactory
from .git_adapter import LegacyGitAdapter
from .diff_adapter import LegacyDiffAdapter
from .conversation_adapter import LegacyConversationAdapter
from .tool_adapter import LegacyToolRegistry, LegacyToolRuntime, LegacyToolPolicy
from .prompt_adapter import LegacyPromptAdapter
from .context_adapter import LegacyContextAdapter, LegacyContextCache
from .stream_adapter import LegacyStreamAdapter
from .config_adapter import LegacyConfigAdapter
from .rule_adapter import LegacyRuleAdapter
from .project_adapter import LegacyProjectAdapter, LegacyProjectDiffAdapter

__all__ = [
    # Persistence
    "FileArtifactStore",
    "LegacyScanCacheSnapshot",
    "SQLiteKernelStore",
    "build_issues_by_severity",
    "build_linked_payload",
    "build_scan_artifact_payload",
    "build_scan_result",
    "build_scan_summary",
    "is_scan_complete",
    "read_legacy_scan_cache",
    "utc_now",
    "wait_for_scan_completion",
    # Adapters
    "LegacyLLMClient",
    "LegacyLLMFactory",
    "LegacyGitAdapter",
    "LegacyDiffAdapter",
    "LegacyConversationAdapter",
    "LegacyToolRegistry",
    "LegacyToolRuntime",
    "LegacyToolPolicy",
    "LegacyPromptAdapter",
    "LegacyContextAdapter",
    "LegacyContextCache",
    "LegacyStreamAdapter",
    "LegacyConfigAdapter",
    "LegacyRuleAdapter",
    "LegacyProjectAdapter",
    "LegacyProjectDiffAdapter",
]
