"""Scanner base classes and shared helpers for code scanner integration.

This module provides the base infrastructure for integrating code scanners
(linters, type checkers, static analysis tools) into the rule parsing system.

Requirements: 2.1, 2.2, 4.1, 4.4, 6.1
"""

from __future__ import annotations

import json
import logging
import subprocess
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Scanner Issue Data Structure
# =============================================================================

@dataclass
class ScannerIssue:
    """Scanner issue structure representing a detected problem.
    
    Attributes:
        line: Line number where the issue was detected (1-indexed)
        column: Column number where the issue was detected (1-indexed)
        severity: Normalized severity level (error | warning | info)
        message: Human-readable description of the issue
        rule_id: Identifier of the rule that detected the issue
        
    Requirements: 2.1
    """
    line: int
    column: int
    severity: str  # error | warning | info
    message: str
    rule_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.
        
        Returns:
            Dictionary with all fields
            
        Requirements: 2.4
        """
        return {
            "line": self.line,
            "column": self.column,
            "severity": self.severity,
            "message": self.message,
            "rule_id": self.rule_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScannerIssue":
        """Create ScannerIssue from dictionary.
        
        Args:
            data: Dictionary with issue fields
            
        Returns:
            ScannerIssue instance
            
        Requirements: 2.4
        """
        return cls(
            line=data.get("line", 0),
            column=data.get("column", 0),
            severity=data.get("severity", "info"),
            message=data.get("message", ""),
            rule_id=data.get("rule_id", "")
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string.
        
        Returns:
            JSON string representation
            
        Requirements: 2.4
        """
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> "ScannerIssue":
        """Deserialize from JSON string.
        
        Args:
            json_str: JSON string representation
            
        Returns:
            ScannerIssue instance
            
        Requirements: 2.4
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


# =============================================================================
# Severity Normalization
# =============================================================================

# Mapping of common severity values to normalized levels
SEVERITY_MAPPINGS: Dict[str, str] = {
    # Error level
    "error": "error",
    "err": "error",
    "e": "error",
    "fatal": "error",
    "critical": "error",
    "failure": "error",
    "fail": "error",
    
    # Warning level
    "warning": "warning",
    "warn": "warning",
    "w": "warning",
    "caution": "warning",
    
    # Info level
    "info": "info",
    "information": "info",
    "i": "info",
    "note": "info",
    "hint": "info",
    "suggestion": "info",
    "convention": "info",
    "refactor": "info",
    "style": "info",
    "c": "info",  # pylint convention
    "r": "info",  # pylint refactor
}

VALID_SEVERITIES = {"error", "warning", "info"}


def normalize_severity(raw_severity: str) -> str:
    """Normalize severity value to one of: error, warning, info.
    
    Args:
        raw_severity: Raw severity string from scanner output
        
    Returns:
        Normalized severity: "error", "warning", or "info"
        
    Requirements: 2.2
    """
    if not raw_severity:
        return "info"
    
    normalized = raw_severity.lower().strip()
    
    # Direct mapping
    if normalized in SEVERITY_MAPPINGS:
        return SEVERITY_MAPPINGS[normalized]
    
    # Check if already valid
    if normalized in VALID_SEVERITIES:
        return normalized
    
    # Default to info for unknown severities
    return "info"


# =============================================================================
# Base Scanner Class
# =============================================================================

class BaseScanner(ABC):
    """Abstract base class for code scanners.
    
    Provides common functionality for executing external scanner tools,
    parsing their output, and normalizing results.
    
    Attributes:
        name: Scanner identifier (e.g., "pylint", "eslint")
        language: Target language (e.g., "python", "typescript")
        command: Command to execute the scanner
        
    Requirements: 2.1, 2.2, 4.1, 4.4, 6.1
    """
    
    name: str = "base"
    language: str = "unknown"
    command: str = ""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize scanner with configuration.
        
        Configuration is loaded from rule_config.py if not provided explicitly.
        The configuration supports the following keys:
            - enabled: Whether scanner is enabled (default: True)
            - timeout: Execution timeout in seconds (default: 30)
            - extra_args: Additional command line arguments (default: [])
        
        Args:
            config: Scanner configuration dictionary. If None, loads from
                    rule_config.py based on scanner's language and name.
                
        Requirements: 4.1, 4.4, 6.1
        """
        # Load configuration from rule_config if not provided
        if config is None:
            config = self._load_config_from_rule_config()
        
        self.config = config or {}
        self.timeout = self.config.get("timeout", 30)
        self.enabled = self.config.get("enabled", True)
        self.extra_args: List[str] = self.config.get("extra_args", [])
        self._available: Optional[bool] = None
        
        logger.debug(
            f"Initialized scanner {self.name} with config: "
            f"enabled={self.enabled}, timeout={self.timeout}, "
            f"extra_args={self.extra_args}"
        )
    
    def _load_config_from_rule_config(self) -> Dict[str, Any]:
        """Load scanner configuration from rule_config.py.
        
        Returns:
            Configuration dictionary for this scanner
            
        Requirements: 4.1, 4.4
        """
        try:
            from Agent.DIFF.rule.rule_config import get_scanner_config
            return get_scanner_config(self.language, self.name)
        except ImportError:
            logger.warning(
                f"Could not import rule_config, using default config for {self.name}"
            )
            return {}
        except Exception as e:
            logger.warning(
                f"Error loading config for scanner {self.name}: {e}"
            )
            return {}
    
    @abstractmethod
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a file and return detected issues.
        
        Args:
            file_path: Path to the file to scan
            content: Optional file content (if not provided, read from file_path)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1
        """
        pass
    
    @abstractmethod
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse scanner output and extract issues.
        
        Args:
            output: Raw output from the scanner command
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1
        """
        pass
    
    def is_available(self) -> bool:
        """Check if the scanner tool is available on the system.
        
        Logs a warning if the scanner is not available, allowing the system
        to gracefully skip unavailable scanners.
        
        Returns:
            True if the scanner command is available, False otherwise
            
        Requirements: 4.2
        """
        if self._available is not None:
            return self._available
        
        if not self.command:
            self._available = False
            logger.warning(
                f"Scanner {self.name} has no command configured, marking as unavailable"
            )
            return False
        
        # Check if command exists in PATH
        self._available = shutil.which(self.command) is not None
        
        if not self._available:
            logger.warning(
                f"Scanner {self.name} is not available: command '{self.command}' "
                f"not found in PATH. Install {self.name} to enable this scanner."
            )
        
        return self._available
    
    def normalize_severity(self, raw_severity: str) -> str:
        """Normalize severity value to standard levels.
        
        Args:
            raw_severity: Raw severity string from scanner output
            
        Returns:
            Normalized severity: "error", "warning", or "info"
            
        Requirements: 2.2
        """
        return normalize_severity(raw_severity)
    
    def _decode_output(self, data: bytes) -> str:
        """Decode subprocess output with fallback encodings.
        
        Args:
            data: Raw bytes from subprocess
            
        Returns:
            Decoded string
        """
        if not data:
            return ""
        # Try UTF-8 first (most common for modern tools)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        # Try system default encoding (GBK on Chinese Windows)
        try:
            import locale
            return data.decode(locale.getpreferredencoding(), errors="replace")
        except Exception:
            pass
        # Final fallback with replacement
        return data.decode("utf-8", errors="replace")
    
    def _execute_command(
        self, 
        args: List[str], 
        cwd: Optional[str] = None,
        input_data: Optional[str] = None
    ) -> Tuple[int, str, str]:
        """Execute scanner command with timeout handling.
        
        Executes the scanner command with a configurable timeout. If the command
        times out, the process is terminated and partial results are returned
        if available.
        
        Args:
            args: Command arguments (including the command itself)
            cwd: Working directory for command execution
            input_data: Optional input to pass to stdin
            
        Returns:
            Tuple of (return_code, stdout, stderr)
            - return_code: Process exit code, or -1 for timeout/error
            - stdout: Standard output from the process
            - stderr: Standard error from the process, or error message
            
        Requirements: 4.3, 6.1
        """
        process = None
        try:
            # Use Popen for better control over timeout and process termination
            # NOTE: Do NOT use text=True to avoid encoding issues on Windows
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if input_data else None,
                cwd=cwd
            )
            
            try:
                input_bytes = input_data.encode("utf-8") if input_data else None
                stdout_bytes, stderr_bytes = process.communicate(
                    input=input_bytes,
                    timeout=self.timeout
                )
                stdout = self._decode_output(stdout_bytes)
                stderr = self._decode_output(stderr_bytes)
                return process.returncode, stdout, stderr
                
            except subprocess.TimeoutExpired:
                # Timeout occurred - terminate process and get partial results
                logger.warning(
                    f"Scanner {self.name} timed out after {self.timeout} seconds. "
                    f"Terminating process and returning partial results."
                )
                
                # Try to get partial output before killing
                partial_stdout = ""
                partial_stderr = ""
                
                try:
                    # First try graceful termination
                    process.terminate()
                    try:
                        # Wait briefly for graceful termination
                        stdout_bytes, stderr_bytes = process.communicate(timeout=2)
                        partial_stdout = self._decode_output(stdout_bytes)
                        partial_stderr = self._decode_output(stderr_bytes)
                    except subprocess.TimeoutExpired:
                        # Force kill if still running
                        process.kill()
                        stdout_bytes, stderr_bytes = process.communicate()
                        partial_stdout = self._decode_output(stdout_bytes)
                        partial_stderr = self._decode_output(stderr_bytes)
                except Exception as term_error:
                    logger.debug(f"Error during process termination: {term_error}")
                    # Ensure process is killed
                    try:
                        process.kill()
                    except Exception:
                        pass
                
                timeout_msg = (
                    f"Scanner {self.name} timed out after {self.timeout} seconds. "
                    f"Consider increasing timeout in configuration."
                )
                
                # Return partial results if available (Requirements 4.3)
                if partial_stdout:
                    logger.info(
                        f"Returning partial results from {self.name} after timeout"
                    )
                    return -1, partial_stdout, timeout_msg
                
                return -1, "", timeout_msg
                
        except FileNotFoundError:
            error_msg = f"Scanner command not found: {args[0] if args else 'unknown'}"
            logger.warning(error_msg)
            return -1, "", error_msg
            
        except PermissionError:
            error_msg = f"Permission denied executing scanner command: {args[0] if args else 'unknown'}"
            logger.warning(error_msg)
            return -1, "", error_msg
            
        except Exception as e:
            error_msg = f"Scanner execution error: {str(e)}"
            logger.warning(error_msg)
            return -1, "", error_msg
            
        finally:
            # Ensure process is cleaned up
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=1)
                except Exception:
                    pass
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build command arguments for scanning a file.
        
        Override this method in subclasses to customize command construction.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [self.command]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def set_timeout(self, timeout: int) -> None:
        """Set the execution timeout for this scanner.
        
        Args:
            timeout: Timeout in seconds (must be positive)
            
        Requirements: 4.3, 6.1
        """
        if timeout <= 0:
            logger.warning(
                f"Invalid timeout value {timeout} for scanner {self.name}, "
                f"using default of 30 seconds"
            )
            timeout = 30
        
        self.timeout = timeout
        logger.debug(f"Set timeout for scanner {self.name} to {timeout} seconds")
    
    def get_timeout(self) -> int:
        """Get the current execution timeout.
        
        Returns:
            Timeout in seconds
            
        Requirements: 6.1
        """
        return self.timeout
    
    def get_scanner_info(self) -> Dict[str, Any]:
        """Get scanner metadata.
        
        Returns:
            Dictionary with scanner information
        """
        return {
            "name": self.name,
            "language": self.language,
            "command": self.command,
            "available": self.is_available(),
            "enabled": self.enabled,
            "timeout": self.timeout
        }
    
    def check_availability_with_reason(self) -> Tuple[bool, str]:
        """Check scanner availability and return reason if unavailable.
        
        This method provides detailed information about why a scanner
        might not be available, useful for debugging and user feedback.
        Uses is_available() for the actual check to support subclass overrides.
        
        Returns:
            Tuple of (is_available, reason_message)
            
        Requirements: 4.2
        """
        if not self.enabled:
            return False, f"Scanner {self.name} is disabled in configuration"
        
        if not self.command:
            return False, f"Scanner {self.name} has no command configured"
        
        # Use is_available() to support subclass overrides (e.g., for testing)
        if self.is_available():
            command_path = shutil.which(self.command)
            if command_path:
                return True, f"Scanner {self.name} is available at {command_path}"
            else:
                return True, f"Scanner {self.name} is available"
        
        return False, (
            f"Scanner {self.name} command '{self.command}' not found in PATH. "
            f"Please install {self.name} to enable this scanner."
        )
    
    def safe_scan(
        self, 
        file_path: str, 
        content: Optional[str] = None
    ) -> Tuple[List[ScannerIssue], Optional[str]]:
        """Safely scan a file with comprehensive error handling.
        
        This method wraps the scan() method with error handling to ensure
        that failures are caught and reported without raising exceptions.
        
        Args:
            file_path: Path to the file to scan
            content: Optional file content
            
        Returns:
            Tuple of (issues_list, error_message)
            - issues_list: List of ScannerIssue instances (may be empty)
            - error_message: Error message if scan failed, None if successful
            
        Requirements: 6.4
        """
        # Check availability first
        if not self.enabled:
            return [], f"Scanner {self.name} is disabled"
        
        if not self.is_available():
            return [], f"Scanner {self.name} is not available"
        
        try:
            issues = self.scan(file_path, content)
            return issues, None
        except FileNotFoundError as e:
            error_msg = f"File not found: {file_path}"
            logger.warning(f"Scanner {self.name}: {error_msg}")
            return [], error_msg
        except PermissionError as e:
            error_msg = f"Permission denied: {file_path}"
            logger.warning(f"Scanner {self.name}: {error_msg}")
            return [], error_msg
        except subprocess.TimeoutExpired as e:
            error_msg = f"Scan timed out after {self.timeout} seconds"
            logger.warning(f"Scanner {self.name}: {error_msg}")
            return [], error_msg
        except Exception as e:
            error_msg = f"Scan failed: {str(e)}"
            logger.warning(f"Scanner {self.name}: {error_msg}")
            return [], error_msg
