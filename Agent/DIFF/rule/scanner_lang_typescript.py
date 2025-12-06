"""TypeScript language scanners for code analysis.

This module provides scanner implementations for TypeScript code analysis tools:
- ESLintScanner: ESLint JavaScript/TypeScript linter
- TscScanner: TypeScript compiler type checker

Requirements: 1.4
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue
from Agent.DIFF.rule.scanner_registry import ScannerRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# ESLint Scanner
# =============================================================================

@ScannerRegistry.register("typescript")
class ESLintScanner(BaseScanner):
    """Scanner for ESLint JavaScript/TypeScript linter.
    
    ESLint is a pluggable linting utility for JavaScript and TypeScript.
    It can identify and report on patterns found in ECMAScript/JavaScript code.
    
    Output format: JSON (using --format=json)
    
    Requirements: 1.4
    """
    
    name: str = "eslint"
    language: str = "typescript"
    command: str = "eslint"
    
    # ESLint severity mapping (ESLint uses 1=warning, 2=error)
    ESLINT_SEVERITY_MAP: Dict[int, str] = {
        0: "info",      # off
        1: "warning",   # warn
        2: "error",     # error
    }
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a TypeScript file using ESLint.
        
        Args:
            file_path: Path to the TypeScript file to scan
            content: Optional file content (not used, eslint reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.4, 2.1
        """
        if not self.is_available():
            logger.warning("ESLint is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # ESLint returns non-zero exit codes when issues are found
        if stderr and "error" in stderr.lower() and "oops!" not in stderr.lower():
            logger.warning(f"ESLint stderr: {stderr}")
        
        return self.parse_output(stdout)

    def _build_command_args(self, file_path: str) -> List[str]:
        """Build ESLint command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "--format=json",
            "--no-color",
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse ESLint JSON output.
        
        ESLint JSON format:
        [
            {
                "filePath": "/path/to/file.ts",
                "messages": [
                    {
                        "ruleId": "no-unused-vars",
                        "severity": 2,
                        "message": "'x' is defined but never used.",
                        "line": 1,
                        "column": 5,
                        "nodeType": "Identifier",
                        "endLine": 1,
                        "endColumn": 6
                    }
                ],
                "errorCount": 1,
                "warningCount": 0,
                "fixableErrorCount": 0,
                "fixableWarningCount": 0
            }
        ]
        
        Args:
            output: JSON output from eslint
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            data = json.loads(output)
            
            # ESLint returns an array of file results
            for file_result in data:
                messages = file_result.get("messages", [])
                
                for msg in messages:
                    line = msg.get("line", 0)
                    column = msg.get("column", 0)
                    raw_severity = msg.get("severity", 1)
                    message = msg.get("message", "")
                    rule_id = msg.get("ruleId", "eslint")
                    
                    # Handle null ruleId (can happen for parsing errors)
                    if rule_id is None:
                        rule_id = "eslint-parse-error"
                    
                    # Normalize severity (ESLint uses numeric values)
                    severity = self._map_eslint_severity(raw_severity)
                    
                    issue = ScannerIssue(
                        line=line,
                        column=column,
                        severity=severity,
                        message=message,
                        rule_id=rule_id
                    )
                    issues.append(issue)
                    
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse ESLint JSON output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing ESLint output: {e}")
        
        return issues
    
    def _map_eslint_severity(self, severity: int) -> str:
        """Map ESLint severity to normalized severity.
        
        ESLint uses numeric severity: 0=off, 1=warn, 2=error
        
        Args:
            severity: ESLint severity number
            
        Returns:
            Normalized severity
        """
        if isinstance(severity, int) and severity in self.ESLINT_SEVERITY_MAP:
            return self.ESLINT_SEVERITY_MAP[severity]
        # Handle string severity
        if isinstance(severity, str):
            return self.normalize_severity(severity)
        return "warning"


# =============================================================================
# Tsc Scanner
# =============================================================================

@ScannerRegistry.register("typescript")
class TscScanner(BaseScanner):
    """Scanner for TypeScript compiler (tsc) type checker.
    
    The TypeScript compiler can be used to check for type errors
    without emitting JavaScript output.
    
    Output format: text (file(line,column): error TSxxxx: message)
    
    Requirements: 1.4
    """
    
    name: str = "tsc"
    language: str = "typescript"
    command: str = "tsc"
    
    # TypeScript diagnostic category mapping
    TSC_SEVERITY_MAP: Dict[str, str] = {
        "error": "error",
        "warning": "warning",
        "message": "info",
        "suggestion": "info",
    }
    
    # Pattern to parse tsc output: file(line,column): category TSxxxx: message
    # Example: src/index.ts(10,5): error TS2304: Cannot find name 'foo'.
    OUTPUT_PATTERN = re.compile(
        r'^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*'
        r'(?P<category>\w+)\s+(?P<code>TS\d+):\s*(?P<message>.+)$'
    )
    
    # Alternative pattern for simpler output format
    # Example: file.ts:10:5 - error TS2304: Cannot find name 'foo'.
    ALT_OUTPUT_PATTERN = re.compile(
        r'^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+)\s*-\s*'
        r'(?P<category>\w+)\s+(?P<code>TS\d+):\s*(?P<message>.+)$'
    )
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a TypeScript file using tsc.
        
        Args:
            file_path: Path to the TypeScript file to scan
            content: Optional file content (not used, tsc reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.4, 2.1
        """
        if not self.is_available():
            logger.warning("tsc is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # tsc outputs diagnostics to stdout
        # Combine stdout and stderr for parsing
        output = stdout if stdout else stderr
        
        return self.parse_output(output)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build tsc command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "--noEmit",           # Don't emit output files
            "--pretty", "false",  # Disable colored output for easier parsing
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse tsc output.
        
        tsc output format:
        file(line,column): category TSxxxx: message
        or
        file:line:column - category TSxxxx: message
        
        Args:
            output: Output from tsc command
            
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
            
            # Try primary pattern first
            match = self.OUTPUT_PATTERN.match(line)
            if not match:
                # Try alternative pattern
                match = self.ALT_OUTPUT_PATTERN.match(line)
            
            if match:
                category = match.group('category').lower()
                severity = self._map_tsc_severity(category)
                code = match.group('code')
                message = match.group('message')
                
                issue = ScannerIssue(
                    line=int(match.group('line')),
                    column=int(match.group('column')),
                    severity=severity,
                    message=message,
                    rule_id=code
                )
                issues.append(issue)
        
        return issues
    
    def _map_tsc_severity(self, category: str) -> str:
        """Map tsc diagnostic category to normalized severity.
        
        Args:
            category: tsc diagnostic category (error, warning, message, suggestion)
            
        Returns:
            Normalized severity
        """
        category_lower = category.lower()
        if category_lower in self.TSC_SEVERITY_MAP:
            return self.TSC_SEVERITY_MAP[category_lower]
        return self.normalize_severity(category)
