"""Semgrep universal scanner for multi-language code analysis.

This module provides a Semgrep-based scanner that supports multiple programming
languages through a single Python dependency, eliminating the need for
language-specific toolchains (Node.js, JDK, Go, Ruby, etc.).

Supported languages: Python, TypeScript, JavaScript, Java, Go, Ruby, C, C++, etc.

Requirements:
- pip install semgrep
- No additional language runtimes required

Usage:
    The scanner is automatically registered for multiple languages.
    It integrates with the existing scanner infrastructure and rule system.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue
from Agent.DIFF.rule.scanner_registry import ScannerRegistry

logger = logging.getLogger(__name__)

_UNAVAILABLE_LOG_TTL_SECONDS = 60.0
_unavailable_log_ts_by_module: Dict[str, float] = {}


# =============================================================================
# Semgrep Severity Mapping
# =============================================================================

SEMGREP_SEVERITY_MAP: Dict[str, str] = {
    "error": "error",
    "warning": "warning",
    "info": "info",
    "note": "info",
    # Semgrep specific levels
    "ERROR": "error",
    "WARNING": "warning",
    "INFO": "info",
}


# =============================================================================
# Semgrep Scanner Implementation
# =============================================================================

class SemgrepScanner(BaseScanner):
    """Universal scanner using Semgrep for multi-language code analysis.
    
    Semgrep is a fast, open-source static analysis tool that supports
    many programming languages out of the box. It uses pattern matching
    and can detect security vulnerabilities, bugs, and code style issues.
    
    Features:
    - Multi-language support (Python, JS/TS, Java, Go, Ruby, C/C++, etc.)
    - No language runtime dependencies required
    - Configurable rule sets (auto, security, performance, etc.)
    - JSON output for easy parsing
    
    Configuration options (via rule_config.py):
    - enabled: Whether scanner is enabled (default: True)
    - timeout: Execution timeout in seconds (default: 60)
    - extra_args: Additional CLI arguments (default: [])
    - config: Rule configuration (default: "auto")
    
    Attributes:
        name: Scanner identifier ("semgrep")
        language: Target language for this instance
        command: Command to execute ("semgrep")
    """
    
    name: str = "semgrep"
    command: str = "semgrep"
    
    def __init__(self, language: str, config: Optional[Dict[str, Any]] = None):
        """Initialize Semgrep scanner for a specific language.
        
        Args:
            language: Target programming language
            config: Scanner configuration dictionary
        """
        self.language = language
        super().__init__(config)

        self._module = "semgrep"
        self.command = sys.executable
        
        # Semgrep-specific configuration
        self.rule_config = self.config.get("config", "auto")
        
        # Default timeout is higher for Semgrep (first run downloads rules)
        if self.timeout == 30:  # Default base timeout
            self.timeout = self.config.get("timeout", 60)
    
    def is_available(self, refresh: bool = False) -> bool:
        spec = importlib.util.find_spec(self._module)
        ok = spec is not None
        if not ok:
            key = f"python_module:{self._module}"
            now = time.time()
            last = _unavailable_log_ts_by_module.get(key, 0.0)
            if (now - last) >= _UNAVAILABLE_LOG_TTL_SECONDS:
                _unavailable_log_ts_by_module[key] = now
                logger.warning(
                    f"Scanner {self.name} is not available: python module '{self._module}' "
                    f"is not installed. Install {self.name} to enable this scanner."
                )
        return ok
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build Semgrep command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "-m",
            self._module,
            "--json",           # JSON output for parsing
            "--quiet",          # Suppress progress output
            "--no-git-ignore",  # Don't respect .gitignore (scan target file)
            "--config",
            self.rule_config,
        ]
        
        # Add language filter for better performance
        lang_map = {
            "python": "python",
            "typescript": "typescript",
            "javascript": "javascript",
            "java": "java",
            "go": "go",
            "ruby": "ruby",
            "c": "c",
            "cpp": "cpp",
            "csharp": "csharp",
            "rust": "rust",
            "kotlin": "kotlin",
            "swift": "swift",
            "php": "php",
            "scala": "scala",
        }
        
        semgrep_lang = lang_map.get(self.language.lower())
        if semgrep_lang:
            args.append(f"--lang={semgrep_lang}")
        
        # Add extra args from configuration
        args.extend(self.extra_args)
        
        # Target file
        args.append(file_path)
        
        return args
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a file using Semgrep.
        
        Args:
            file_path: Path to the file to scan
            content: Optional file content (not used, Semgrep reads from file)
            
        Returns:
            List of ScannerIssue instances
        """
        if not self.is_available():
            return []
        
        # Verify file exists
        if not os.path.isfile(file_path):
            logger.warning(f"File not found for Semgrep scan: {file_path}")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # Semgrep returns non-zero for findings, so we parse regardless
        if stderr and "error" in stderr.lower() and "timeout" not in stderr.lower():
            # Only log actual errors, not timeout messages (handled by base class)
            logger.debug(f"Semgrep stderr: {stderr[:200]}")
        
        return self.parse_output(stdout)
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse Semgrep JSON output.
        
        Semgrep JSON output format:
        {
            "results": [
                {
                    "check_id": "rule-id",
                    "path": "file.py",
                    "start": {"line": 1, "col": 1},
                    "end": {"line": 1, "col": 10},
                    "extra": {
                        "message": "Description",
                        "severity": "ERROR|WARNING|INFO",
                        "metadata": {...}
                    }
                },
                ...
            ],
            "errors": [...],
            "version": "..."
        }
        
        Args:
            output: JSON output from Semgrep
            
        Returns:
            List of ScannerIssue instances
        """
        if not output or not output.strip():
            return []
        
        issues: List[ScannerIssue] = []
        
        try:
            data = json.loads(output)
            
            # Process results
            for result in data.get("results", []):
                try:
                    # Extract position
                    start = result.get("start", {}) or {}
                    line = int(start.get("line", 0))
                    column = int(start.get("col", 0))
                    
                    # Extract extra info
                    extra = result.get("extra", {}) or {}
                    message = extra.get("message", "")
                    
                    # Normalize severity
                    raw_severity = str(extra.get("severity", "info")).lower()
                    severity = self._map_semgrep_severity(raw_severity)
                    
                    # Get rule ID
                    rule_id = result.get("check_id", "semgrep")
                    
                    # Skip if no meaningful content
                    if not message and not rule_id:
                        continue
                    
                    issue = ScannerIssue(
                        line=line,
                        column=column,
                        severity=severity,
                        message=message,
                        rule_id=rule_id
                    )
                    issues.append(issue)
                    
                except Exception as item_error:
                    logger.debug(f"Failed to parse Semgrep result item: {item_error}")
                    continue
            
            # Log errors from Semgrep (for debugging)
            errors = data.get("errors", [])
            if errors:
                logger.debug(f"Semgrep reported {len(errors)} error(s) during scan")
                    
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Semgrep JSON output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing Semgrep output: {e}")
        
        return issues
    
    def _map_semgrep_severity(self, severity: str) -> str:
        """Map Semgrep severity to normalized severity.
        
        Args:
            severity: Semgrep severity string
            
        Returns:
            Normalized severity: "error", "warning", or "info"
        """
        if severity in SEMGREP_SEVERITY_MAP:
            return SEMGREP_SEVERITY_MAP[severity]
        return self.normalize_severity(severity)
    
    def get_scanner_info(self) -> Dict[str, Any]:
        """Get scanner metadata including Semgrep-specific info.
        
        Returns:
            Dictionary with scanner information
        """
        info = super().get_scanner_info()
        info["rule_config"] = self.rule_config
        info["multi_language"] = True
        return info


# =============================================================================
# Scanner Factory and Registration
# =============================================================================

def _create_semgrep_scanner_class(language: str) -> type:
    """Create a language-specific Semgrep scanner class.
    
    This factory creates subclasses of SemgrepScanner with the language
    attribute set, allowing proper registration with ScannerRegistry.
    
    Args:
        language: Target programming language
        
    Returns:
        A SemgrepScanner subclass for the specified language
    """
    class LanguageSemgrepScanner(SemgrepScanner):
        """Language-specific Semgrep scanner."""
        
        def __init__(self, config: Optional[Dict[str, Any]] = None):
            super().__init__(language=language, config=config)
    
    # Set class attributes for identification
    LanguageSemgrepScanner.language = language
    LanguageSemgrepScanner.__name__ = f"Semgrep{language.title()}Scanner"
    LanguageSemgrepScanner.__qualname__ = f"Semgrep{language.title()}Scanner"
    
    return LanguageSemgrepScanner


# Languages supported by Semgrep (subset of commonly used)
SEMGREP_SUPPORTED_LANGUAGES = [
    "python",
    "typescript", 
    "javascript",
    "java",
    "go",
    "ruby",
    "c",
    "cpp",
    "csharp",
    "rust",
    "kotlin",
    "swift",
    "php",
    "scala",
]


def register_semgrep_scanners(languages: Optional[List[str]] = None) -> None:
    """Register Semgrep scanner for multiple languages.
    
    This function creates and registers Semgrep scanner instances for
    each specified language, integrating with the existing scanner
    infrastructure.
    
    Args:
        languages: List of languages to register. If None, registers
                   for all supported languages.
    """
    target_languages = languages or SEMGREP_SUPPORTED_LANGUAGES
    
    for lang in target_languages:
        try:
            scanner_class = _create_semgrep_scanner_class(lang)
            ScannerRegistry.register(lang)(scanner_class)
            logger.debug(f"Registered Semgrep scanner for language: {lang}")
        except Exception as e:
            logger.warning(f"Failed to register Semgrep scanner for {lang}: {e}")


# Auto-register Semgrep scanners for common languages on module import
# This ensures Semgrep is available alongside language-specific scanners
register_semgrep_scanners()


__all__ = [
    "SemgrepScanner",
    "SEMGREP_SUPPORTED_LANGUAGES",
    "register_semgrep_scanners",
]
