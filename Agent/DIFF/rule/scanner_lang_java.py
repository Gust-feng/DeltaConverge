"""Java language scanners for code analysis.

This module provides scanner implementations for Java code analysis tools:
- CheckstyleScanner: Checkstyle code style checker
- PMDScanner: PMD static analysis tool

Requirements: 1.2
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue
from Agent.DIFF.rule.scanner_registry import ScannerRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# Checkstyle Scanner
# =============================================================================

@ScannerRegistry.register("java")
class CheckstyleScanner(BaseScanner):
    """Scanner for Checkstyle code style checker.
    
    Checkstyle is a development tool to help programmers write Java code
    that adheres to a coding standard.
    
    Output format: XML (default)
    
    Requirements: 1.2
    """
    
    name: str = "checkstyle"
    language: str = "java"
    command: str = "checkstyle"
    
    # Checkstyle severity mapping
    CHECKSTYLE_SEVERITY_MAP: Dict[str, str] = {
        "error": "error",
        "warning": "warning",
        "info": "info",
        "ignore": "info",
    }
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Java file using Checkstyle.
        
        Args:
            file_path: Path to the Java file to scan
            content: Optional file content (not used, checkstyle reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.2, 2.1
        """
        if not self.is_available():
            logger.warning("Checkstyle is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # Checkstyle outputs XML to stdout
        # Non-zero exit code may indicate issues found
        if stderr and "error" in stderr.lower():
            logger.warning(f"Checkstyle stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build Checkstyle command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "-f", "xml",  # XML output format
        ]
        args.extend(self.extra_args)
        args.append(file_path)
        return args

    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse Checkstyle XML output.
        
        Checkstyle XML format:
        <checkstyle version="...">
            <file name="...">
                <error line="..." column="..." severity="..." message="..." source="..."/>
            </file>
        </checkstyle>
        
        Args:
            output: XML output from checkstyle
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            root = ET.fromstring(output)
            
            # Find all file elements
            for file_elem in root.findall('.//file'):
                # Find all error elements within each file
                for error_elem in file_elem.findall('error'):
                    line = int(error_elem.get('line', '0'))
                    column = int(error_elem.get('column', '0'))
                    raw_severity = error_elem.get('severity', 'warning')
                    message = error_elem.get('message', '')
                    source = error_elem.get('source', '')
                    
                    # Extract rule_id from source (e.g., "com.puppycrawl.tools.checkstyle.checks.naming.LocalVariableNameCheck")
                    rule_id = self._extract_rule_id(source)
                    
                    # Normalize severity
                    severity = self._map_checkstyle_severity(raw_severity)
                    
                    issue = ScannerIssue(
                        line=line,
                        column=column,
                        severity=severity,
                        message=message,
                        rule_id=rule_id
                    )
                    issues.append(issue)
                    
        except ET.ParseError as e:
            logger.warning(f"Failed to parse Checkstyle XML output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing Checkstyle output: {e}")
        
        return issues
    
    def _map_checkstyle_severity(self, severity: str) -> str:
        """Map Checkstyle severity to normalized severity.
        
        Args:
            severity: Checkstyle severity string
            
        Returns:
            Normalized severity
        """
        severity_lower = severity.lower()
        if severity_lower in self.CHECKSTYLE_SEVERITY_MAP:
            return self.CHECKSTYLE_SEVERITY_MAP[severity_lower]
        return self.normalize_severity(severity)
    
    def _extract_rule_id(self, source: str) -> str:
        """Extract rule ID from Checkstyle source attribute.
        
        The source attribute contains the full class name of the check,
        e.g., "com.puppycrawl.tools.checkstyle.checks.naming.LocalVariableNameCheck"
        We extract just the check name.
        
        Args:
            source: Full source class name
            
        Returns:
            Short rule ID
        """
        if not source:
            return "checkstyle"
        
        # Get the last part of the class name
        parts = source.split('.')
        if parts:
            rule_name = parts[-1]
            # Remove "Check" suffix if present
            if rule_name.endswith('Check'):
                rule_name = rule_name[:-5]
            return rule_name
        
        return "checkstyle"


# =============================================================================
# PMD Scanner
# =============================================================================

@ScannerRegistry.register("java")
class PMDScanner(BaseScanner):
    """Scanner for PMD static analysis tool.
    
    PMD is a source code analyzer that finds common programming flaws
    like unused variables, empty catch blocks, unnecessary object creation, etc.
    
    Output format: XML
    
    Requirements: 1.2
    """
    
    name: str = "pmd"
    language: str = "java"
    command: str = "pmd"
    
    # PMD priority to severity mapping
    # PMD priorities: 1 (highest) to 5 (lowest)
    PMD_PRIORITY_MAP: Dict[str, str] = {
        "1": "error",
        "2": "error",
        "3": "warning",
        "4": "warning",
        "5": "info",
    }
    
    def scan(self, file_path: str, content: Optional[str] = None) -> List[ScannerIssue]:
        """Scan a Java file using PMD.
        
        Args:
            file_path: Path to the Java file to scan
            content: Optional file content (not used, PMD reads from file)
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 1.2, 2.1
        """
        if not self.is_available():
            logger.warning("PMD is not available on the system")
            return []
        
        args = self._build_command_args(file_path)
        return_code, stdout, stderr = self._execute_command(args)
        
        # PMD outputs XML to stdout
        if stderr and "error" in stderr.lower():
            logger.warning(f"PMD stderr: {stderr}")
        
        return self.parse_output(stdout)
    
    def _build_command_args(self, file_path: str) -> List[str]:
        """Build PMD command arguments.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            List of command arguments
        """
        args = [
            self.command,
            "check",  # PMD 7.x uses subcommands
            "-f", "xml",  # XML output format
            "-d", file_path,  # Directory/file to analyze
        ]
        args.extend(self.extra_args)
        return args

    def parse_output(self, output: str) -> List[ScannerIssue]:
        """Parse PMD XML output.
        
        PMD XML format:
        <pmd version="..." timestamp="...">
            <file name="...">
                <violation beginline="..." begincolumn="..." endline="..." endcolumn="..."
                           rule="..." ruleset="..." priority="..." externalInfoUrl="...">
                    Message text
                </violation>
            </file>
        </pmd>
        
        Args:
            output: XML output from PMD
            
        Returns:
            List of ScannerIssue instances
            
        Requirements: 2.1, 2.2
        """
        if not output or not output.strip():
            return []
        
        issues = []
        try:
            root = ET.fromstring(output)
            
            # Find all file elements
            for file_elem in root.findall('.//file'):
                # Find all violation elements within each file
                for violation_elem in file_elem.findall('violation'):
                    line = int(violation_elem.get('beginline', '0'))
                    column = int(violation_elem.get('begincolumn', '0'))
                    priority = violation_elem.get('priority', '3')
                    rule = violation_elem.get('rule', 'pmd')
                    message = violation_elem.text.strip() if violation_elem.text else ''
                    
                    # Map priority to severity
                    severity = self._map_pmd_priority(priority)
                    
                    issue = ScannerIssue(
                        line=line,
                        column=column,
                        severity=severity,
                        message=message,
                        rule_id=rule
                    )
                    issues.append(issue)
                    
        except ET.ParseError as e:
            logger.warning(f"Failed to parse PMD XML output: {e}")
        except Exception as e:
            logger.warning(f"Error parsing PMD output: {e}")
        
        return issues
    
    def _map_pmd_priority(self, priority: str) -> str:
        """Map PMD priority to normalized severity.
        
        PMD uses priorities 1-5, where 1 is highest priority.
        
        Args:
            priority: PMD priority string (1-5)
            
        Returns:
            Normalized severity
        """
        if priority in self.PMD_PRIORITY_MAP:
            return self.PMD_PRIORITY_MAP[priority]
        return "warning"
