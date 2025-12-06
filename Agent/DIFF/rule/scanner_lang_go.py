"""Go language scanners for code analysis.

This module provides scanner implementations for Go code analysis tools:
- GolangciLintScanner: golangci-lint comprehensive linter
- GoVetScanner: go vet static analysis tool

Requirements: 1.3
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
# GolangciLint Scanner
# =============================================================================

@ScannerRegistry.register("go")
class GolangciLintScanner(BaseScanner):
    """Scanner for golangci-lint comprehensive linter.
    
    golangci-lint is a fast Go linters aggregator that runs multiple
    linters in parallel and provides a unified output format.
    
    Output format: JSON (using --out-format=json)
    
    Requirements: 1.3
    """
    
    name: str = "golangci-lint"
    language: str = "go"
    command: str = "golangci-lint"
    
    # golangci-lint severity mapping
    GOLANGCI_SEVERITY_MAP: Dict[str, str] = {
        "error": "error",
        "warning": "warning",
        "info": "info",
        "high": "error",
        "medium": "warning",
        "low": "info",
    }

    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Go file using golangci-lint.
        
        Args:
            file_path: Path to the Go file to scan
            content: Optional file content (not used, golangci-lint reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.3, 2.1
        """
        if not self.is_available():
            logger.warning("golangci-lint is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # golangci-lint returns non-zero exit codes when issues are found
        if stderr and "error" in stderr.lower() and "level=error" not in stderr.lower():
            logger.warning(f"golangci-lint stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build golangci-lint command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "run",
            "--out-format=json",
            "--issues-exit-code=0",  # Don't fail on issues
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse golangci-lint JSON output.
        
        golangci-lint JSON format:
        {
            "Issues": [
                {
                    "FromLinter": "linter_name",
                    "Text": "message",
                    "Severity": "warning",
                    "SourceLines": [...],
                    "Pos": {
                        "Filename": "file.go",
                        "Offset": 0,
                        "Line": 10,
                        "Column": 5
                    }
                }
            ]
        }
        
        Args:
            output: JSON output from golangci-lint
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            data = json.loads(output)
            
            # Get issues array
            issues_data = data.get("Issues", [])
            if issues_data is None:
                issues_data = []
            
            for item in issues_data:
                # Extract position information
                pos = item.get("Pos", {})
                line = pos.get("Line", 0)
                column = pos.get("Column", 0)
                
                # Extract other fields
                message = item.get("Text", "")
                linter = item.get("FromLinter", "golangci-lint")
                raw_severity = item.get("Severity", "warning")
                
                # Normalize severity
                severity = self._map_golangci_severity(raw_severity)
                
                issue = ScannerIssue(
                    line=line,
                    column=column,
                    severity=severity,
                    message=message,
                    rule_id=linter
                )
                issues.append(issue)
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse golangci-lint JSON output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing golangci-lint output: {e}")
        
        return issues
    
    def _map_golangci_severity(self, severity: str) -> str:
        """Map golangci-lint severity to normalized severity.
        
        Args:
            severity: golangci-lint severity string
            
        Returns:
            Normalized severity
        """
        severity_lower = severity.lower()
        if severity_lower in self.GOLANGCI_SEVERITY_MAP:
            return self.GOLANGCI_SEVERITY_MAP[severity_lower]
        return self.normalize_severity(severity)


# =============================================================================
# GoVet Scanner
# =============================================================================

@ScannerRegistry.register("go")
class GoVetScanner(BaseScanner):
    """Scanner for go vet static analysis tool.
    
    go vet examines Go source code and reports suspicious constructs,
    such as Printf calls whose arguments do not align with the format string.
    
    Output format: text (file:line:column: message)
    
    Requirements: 1.3
    """
    
    name: str = "go-vet"
    language: str = "go"
    command: str = "go"

    # Pattern to parse go vet output: file:line:column: message
    # Also handles: file:line: message (without column)
    OUTPUT_PATTERN = re.compile(
        r'^(?P<file>.+?):(?P<line>\d+):(?:(?P<column>\d+):)?\s*(?P<message>.+)$'
    )
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Go file using go vet.
        
        Args:
            file_path: Path to the Go file to scan
            content: Optional file content (not used, go vet reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.3, 2.1
        """
        if not self.is_available():
            logger.warning("go vet is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # go vet outputs to stderr
        # Combine stdout and stderr for parsing
        output = stderr if stderr else stdout
        
        return self.parse_output(output)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build go vet command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "vet",
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse go vet output.
        
        go vet output format:
        file.go:line:column: message
        or
        file.go:line: message
        
        Args:
            output: Output from go vet command
            
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
            
            # Skip lines that don't look like issue reports
            if line.startswith('#') or line.startswith('vet:'):
                continue
            
            match = self.OUTPUT_PATTERN.match(line)
            if match:
                column_str = match.group('column')
                column = int(column_str) if column_str else 0
                
                message = match.group('message')
                
                # Extract rule_id from message if possible
                rule_id = self._extract_rule_id(message)
                
                issue = ScannerIssue(
                    line=int(match.group('line')),
                    column=column,
                    severity="warning",  # go vet issues are typically warnings
                    message=message,
                    rule_id=rule_id
                )
                issues.append(issue)
        
        return issues
    
    def _extract_rule_id(self, message: str) -> str:
        """Extract rule ID from go vet message.
        
        go vet messages often start with a check name followed by colon,
        e.g., "printf: Sprintf format %d has arg of wrong type"
        
        Args:
            message: go vet error message
            
        Returns:
            Rule ID or "go-vet" if not found
        """
        if not message:
            return "go-vet"
        
        # Check for pattern like "checkname: message"
        colon_idx = message.find(':')
        if colon_idx > 0 and colon_idx < 20:  # Reasonable check name length
            potential_rule = message[:colon_idx].strip()
            # Verify it looks like a rule name (no spaces, alphanumeric)
            if potential_rule and ' ' not in potential_rule:
                return potential_rule
        
        return "go-vet"
