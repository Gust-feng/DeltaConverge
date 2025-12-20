"""Python language scanners for code analysis.

This module provides scanner implementations for Python code analysis tools:
- PylintScanner: Pylint static analysis
- Flake8Scanner: Flake8 style checker
- MypyScanner: Mypy type checker

Requirements: 1.1
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
import time
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue
from Agent.DIFF.rule.scanner_registry import ScannerRegistry

logger = logging.getLogger(__name__)

_UNAVAILABLE_LOG_TTL_SECONDS = 60.0
_unavailable_log_ts_by_module: Dict[str, float] = {}


# =============================================================================
# Pylint Scanner
# =============================================================================

@ScannerRegistry.register("python")
class PylintScanner(BaseScanner):
    """Scanner for Pylint static analysis tool.
    
    Pylint is a comprehensive Python linter that checks for errors,
    coding standards, and code smells.
    
    Output format: JSON (using --output-format=json)
    
    Requirements: 1.1
    """
    
    name: str = "pylint"
    language: str = "python"
    command: str = "pylint"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self._module = "pylint"
        self.command = sys.executable

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
    
    # Pylint message type to severity mapping
    PYLINT_SEVERITY_MAP: Dict[str, str] = {
        "fatal": "error",
        "error": "error",
        "warning": "warning",
        "convention": "info",
        "refactor": "info",
        "information": "info",
        # Single letter codes
        "F": "error",
        "E": "error",
        "W": "warning",
        "C": "info",
        "R": "info",
        "I": "info",
    }
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Python file using Pylint.
        
        Args:
            file_path: Path to the Python file to scan
            content: Optional file content (not used, pylint reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.1, 2.1
        """
        if not self.is_available():
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # Pylint returns non-zero exit codes for various reasons
        # (including finding issues), so we parse output regardless
        if stderr and "error" in stderr.lower():
            logger.warning(f"Pylint stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build Pylint command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "-m",
            self._module,
            "--output-format=json",
            "--reports=no",
            "--score=no",
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse Pylint JSON output.
        
        Args:
            output: JSON output from pylint
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            data = json.loads(output)
            
            for item in data:
                # Extract fields from pylint JSON output
                line = item.get("line", 0)
                column = item.get("column", 0)
                message_type = item.get("type", "info")
                message = item.get("message", "")
                symbol = item.get("symbol", "")
                message_id = item.get("message-id", symbol)
                
                # Normalize severity
                severity = self._map_pylint_severity(message_type)
                
                # Build rule_id from message-id and symbol
                rule_id = message_id if message_id else symbol
                
                issue = ScannerIssue(
                    line=line,
                    column=column,
                    severity=severity,
                    message=message,
                    rule_id=rule_id
                )
                issues.append(issue)
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Pylint JSON output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing Pylint output: {e}")
        
        return issues
    
    def _map_pylint_severity(self, message_type: str) -> str:
        """Map Pylint message type to normalized severity.
        
        Args:
            message_type: Pylint message type (e.g., "error", "warning", "C")
            
        Returns:
            Normalized severity
        """
        if message_type in self.PYLINT_SEVERITY_MAP:
            return self.PYLINT_SEVERITY_MAP[message_type]
        return self.normalize_severity(message_type)


# =============================================================================
# Flake8 Scanner
# =============================================================================

@ScannerRegistry.register("python")
class Flake8Scanner(BaseScanner):
    """Scanner for Flake8 style checker.
    
    Flake8 combines PyFlakes, pycodestyle, and McCabe complexity checker.
    
    Output format: default (file:line:column: code message)
    
    Requirements: 1.1
    """
    
    name: str = "flake8"
    language: str = "python"
    command: str = "flake8"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self._module = "flake8"
        self.command = sys.executable

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
    
    # Flake8 error code prefixes to severity mapping
    FLAKE8_SEVERITY_MAP: Dict[str, str] = {
        "E": "error",    # pycodestyle errors
        "W": "warning",  # pycodestyle warnings
        "F": "error",    # PyFlakes errors
        "C": "info",     # McCabe complexity
        "N": "info",     # pep8-naming
        "D": "info",     # pydocstyle
        "B": "warning",  # flake8-bugbear
        "S": "warning",  # flake8-bandit (security)
    }
    
    # Pattern to parse flake8 output: file:line:column: code message
    OUTPUT_PATTERN = re.compile(
        r'^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s*(?P<code>\w+)\s+(?P<message>.+)$'
    )
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Python file using Flake8.
        
        Args:
            file_path: Path to the Python file to scan
            content: Optional file content (not used, flake8 reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.1, 2.1
        """
        if not self.is_available():
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        if stderr and "error" in stderr.lower():
            logger.warning(f"Flake8 stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build Flake8 command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "-m",
            self._module,
            "--format=default",
            "--show-source",
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse Flake8 output.
        
        Args:
            output: Output from flake8 command
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            match = self.OUTPUT_PATTERN.match(line)
            if match:
                code = match.group('code')
                severity = self._map_flake8_severity(code)
                
                issue = ScannerIssue(
                    line=int(match.group('line')),
                    column=int(match.group('column')),
                    severity=severity,
                    message=match.group('message'),
                    rule_id=code
                )
                issues.append(issue)
        
        return issues
    
    def _map_flake8_severity(self, code: str) -> str:
        """Map Flake8 error code to normalized severity.
        
        Args:
            code: Flake8 error code (e.g., "E501", "W503", "F401")
            
        Returns:
            Normalized severity
        """
        if not code:
            return "info"
        
        # Get first character (category prefix)
        prefix = code[0].upper()
        
        if prefix in self.FLAKE8_SEVERITY_MAP:
            return self.FLAKE8_SEVERITY_MAP[prefix]
        
        return "info"


# =============================================================================
# Mypy Scanner
# =============================================================================

@ScannerRegistry.register("python")
class MypyScanner(BaseScanner):
    """Scanner for Mypy type checker.
    
    Mypy is a static type checker for Python that checks type annotations.
    
    Output format: default (file:line: severity: message)
    
    Requirements: 1.1
    """
    
    name: str = "mypy"
    language: str = "python"
    command: str = "mypy"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self._module = "mypy"
        self.command = sys.executable

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
    
    # Mypy severity mapping
    MYPY_SEVERITY_MAP: Dict[str, str] = {
        "error": "error",
        "warning": "warning",
        "note": "info",
    }
    
    # Pattern to parse mypy output: file:line: severity: message
    # Also handles: file:line:column: severity: message
    OUTPUT_PATTERN = re.compile(
        r'^(?P<file>.+?):(?P<line>\d+):(?:(?P<column>\d+):)?\s*(?P<severity>\w+):\s*(?P<message>.+)$'
    )
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Python file using Mypy.
        
        Args:
            file_path: Path to the Python file to scan
            content: Optional file content (not used, mypy reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.1, 2.1
        """
        if not self.is_available():
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # Mypy outputs to stdout, stderr may contain additional info
        if stderr and "error" in stderr.lower() and "found" not in stderr.lower():
            logger.warning(f"Mypy stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build Mypy command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "-m",
            self._module,
            "--show-column-numbers",
            "--no-error-summary",
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse Mypy output.
        
        Args:
            output: Output from mypy command
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Skip summary lines
            if line.startswith("Found ") or line.startswith("Success:"):
                continue
            
            match = self.OUTPUT_PATTERN.match(line)
            if match:
                column_str = match.group('column')
                column = int(column_str) if column_str else 0
                
                raw_severity = match.group('severity')
                severity = self._map_mypy_severity(raw_severity)
                
                message = match.group('message')
                
                # Extract error code from message if present (e.g., "[arg-type]")
                rule_id = self._extract_error_code(message)
                
                issue = ScannerIssue(
                    line=int(match.group('line')),
                    column=column,
                    severity=severity,
                    message=message,
                    rule_id=rule_id
                )
                issues.append(issue)
        
        return issues
    
    def _map_mypy_severity(self, severity: str) -> str:
        """Map Mypy severity to normalized severity.
        
        Args:
            severity: Mypy severity string
            
        Returns:
            Normalized severity
        """
        severity_lower = severity.lower()
        if severity_lower in self.MYPY_SEVERITY_MAP:
            return self.MYPY_SEVERITY_MAP[severity_lower]
        return self.normalize_severity(severity)
    
    def _extract_error_code(self, message: str) -> str:
        """Extract error code from mypy message.
        
        Mypy error codes appear at the end of messages in brackets,
        e.g., "Argument 1 has incompatible type [arg-type]"
        
        Args:
            message: Mypy error message
            
        Returns:
            Error code or "mypy" if not found
        """
        # Pattern to match error codes like [arg-type], [name-defined]
        code_match = re.search(r'\[([a-z-]+)\]\s*$', message)
        if code_match:
            return code_match.group(1)
        return "mypy"
