"""Rule parsing and code scanner integration module.

This module provides rule handlers for different programming languages
and code scanner integration for static analysis.
"""

from Agent.DIFF.rule.scanner_base import (
    ScannerIssue,
    BaseScanner,
    normalize_severity,
    VALID_SEVERITIES,
    SEVERITY_MAPPINGS,
)

from Agent.DIFF.rule.scanner_registry import ScannerRegistry

# Import language-specific scanners to trigger registration
# pylint: disable=unused-import
try:
    from Agent.DIFF.rule import scanner_lang_python
except ImportError:
    pass

try:
    from Agent.DIFF.rule import scanner_lang_typescript
except ImportError:
    pass

try:
    from Agent.DIFF.rule import scanner_lang_java
except ImportError:
    pass

try:
    from Agent.DIFF.rule import scanner_lang_go
except ImportError:
    pass

try:
    from Agent.DIFF.rule import scanner_lang_ruby
except ImportError:
    pass

# Import Semgrep universal scanner (multi-language support)
try:
    from Agent.DIFF.rule import scanner_semgrep
except ImportError:
    pass
# pylint: enable=unused-import

__all__ = [
    "ScannerIssue",
    "BaseScanner",
    "normalize_severity",
    "VALID_SEVERITIES",
    "SEVERITY_MAPPINGS",
    "ScannerRegistry",
]
