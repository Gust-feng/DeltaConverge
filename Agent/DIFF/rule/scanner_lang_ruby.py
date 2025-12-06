"""Ruby language scanners for code analysis.

This module provides scanner implementations for Ruby code analysis tools:
- RubocopScanner: RuboCop style checker and linter

Requirements: 1.5
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
# RuboCop Scanner
# =============================================================================

@ScannerRegistry.register("ruby")
class RubocopScanner(BaseScanner):
    """Scanner for RuboCop style checker and linter.
    
    RuboCop is a Ruby static code analyzer and formatter, based on the
    community Ruby style guide. It can detect style violations, potential
    bugs, and security issues.
    
    Output format: JSON (using --format=json)
    
    Requirements: 1.5
    """
    
    name: str = "rubocop"
    language: str = "ruby"
    command: str = "rubocop"
    
    # RuboCop severity mapping
    # RuboCop uses: fatal, error, warning, convention, refactor, info
    RUBOCOP_SEVERITY_MAP: Dict[str, str] = {
        "fatal": "error",
        "error": "error",
        "warning": "warning",
        "convention": "info",
        "refactor": "info",
        "info": "info",
    }

    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Ruby file using RuboCop.
        
        Args:
            file_path: Path to the Ruby file to scan
            content: Optional file content (not used, rubocop reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.5, 2.1
        """
        if not self.is_available():
            logger.warning("RuboCop is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # RuboCop returns non-zero exit codes when issues are found
        if stderr and "error" in stderr.lower():
            logger.warning(f"RuboCop stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build RuboCop command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "--format=json",
            "--force-exclusion",  # Apply exclusions even for explicitly passed files
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args
    
    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse RuboCop JSON output.
        
        RuboCop JSON format:
        {
            "metadata": {...},
            "files": [
                {
                    "path": "file.rb",
                    "offenses": [
                        {
                            "severity": "convention",
                            "message": "...",
                            "cop_name": "Style/StringLiterals",
                            "corrected": false,
                            "correctable": true,
                            "location": {
                                "start_line": 1,
                                "start_column": 1,
                                "last_line": 1,
                                "last_column": 10,
                                "length": 10,
                                "line": 1,
                                "column": 1
                            }
                        }
                    ]
                }
            ],
            "summary": {...}
        }
        
        Args:
            output: JSON output from rubocop
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            data = json.loads(output)
            
            # Get files array
            files_data = data.get("files", [])
            if files_data is None:
                files_data = []
            
            for file_info in files_data:
                offenses = file_info.get("offenses", [])
                if offenses is None:
                    offenses = []
                
                for offense in offenses:
                    # Extract location information
                    location = offense.get("location", {})
                    line = location.get("line", 0)
                    column = location.get("column", 0)
                    
                    # Extract other fields
                    message = offense.get("message", "")
                    cop_name = offense.get("cop_name", "rubocop")
                    raw_severity = offense.get("severity", "info")
                    
                    # Normalize severity
                    severity = self._map_rubocop_severity(raw_severity)
                    
                    issue = ScannerIssue(
                        line=line,
                        column=column,
                        severity=severity,
                        message=message,
                        rule_id=cop_name
                    )
                    issues.append(issue)
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse RuboCop JSON output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing RuboCop output: {e}")
        
        return issues
    
    def _map_rubocop_severity(self, severity: str) -> str:
        """Map RuboCop severity to normalized severity.
        
        Args:
            severity: RuboCop severity string
            
        Returns:
            Normalized severity
        """
        severity_lower = severity.lower()
        if severity_lower in self.RUBOCOP_SEVERITY_MAP:
            return self.RUBOCOP_SEVERITY_MAP[severity_lower]
        return self.normalize_severity(severity)
