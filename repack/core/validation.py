"""Validation utilities for preventing false negatives.

Addresses:
1. Output validation: check that expected files exist and are non-empty
2. Log scanning: detect ERROR/FATAL patterns even when return code is 0
"""

import logging
import os
import re
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# Default error patterns to scan for in log files
DEFAULT_ERROR_PATTERNS = [
    re.compile(r"\bERROR\b", re.IGNORECASE),
    re.compile(r"\bFATAL\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b", re.IGNORECASE),
    re.compile(r"\bAborted\b", re.IGNORECASE),
    re.compile(r"\bSegmentation fault\b", re.IGNORECASE),
    re.compile(r"\bcore dump\b", re.IGNORECASE),
]


class LogScanner:
    """Scans log files for error patterns.

    Even when a process exits with code 0, the log may contain ERROR lines
    indicating partial failure. This catches false-negative status O.
    """

    def __init__(self, extra_patterns: Optional[List[str]] = None,
                 ignore_patterns: Optional[List[str]] = None):
        self.patterns = list(DEFAULT_ERROR_PATTERNS)
        if extra_patterns:
            self.patterns.extend(re.compile(p, re.IGNORECASE) for p in extra_patterns)

        self.ignore_patterns: List[re.Pattern] = []
        if ignore_patterns:
            self.ignore_patterns = [
                re.compile(p, re.IGNORECASE) for p in ignore_patterns
            ]

    def scan(self, log_path: str) -> List[str]:
        """Scan a log file for error patterns.

        Returns:
            List of matching error lines (empty = no errors found).
        """
        if not os.path.exists(log_path):
            return [f"Log file not found: {log_path}"]

        errors: List[str] = []
        with open(log_path, errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                line = line.rstrip()
                if self._is_error(line):
                    errors.append(f"L{line_no}: {line}")

        return errors

    def _is_error(self, line: str) -> bool:
        """Check if a line matches any error pattern (and no ignore pattern).

        Lines starting with '#' are treated as log headers (written by the
        executor) and are always skipped.
        """
        if line.lstrip().startswith("#"):
            return False
        for ignore in self.ignore_patterns:
            if ignore.search(line):
                return False
        for pattern in self.patterns:
            if pattern.search(line):
                return True
        return False


class OutputValidator:
    """Validates that kit outputs are complete.

    Each kit declares expected outputs via get_expected_outputs().
    This validator checks:
    - All expected files exist
    - All expected files are non-empty
    - No unexpected errors in log
    """

    def __init__(self, log_scanner: Optional[LogScanner] = None):
        self.log_scanner = log_scanner or LogScanner()

    def validate(self, output_path: str, expected_files: List[str],
                 log_path: Optional[str] = None) -> "ValidationResult":
        """Validate kit output.

        Args:
            output_path: Directory containing kit outputs.
            expected_files: List of relative file paths expected to exist.
            log_path: Optional log file to scan for errors.

        Returns:
            ValidationResult with pass/fail and details.
        """
        missing: List[str] = []
        empty: List[str] = []
        log_errors: List[str] = []

        # Check expected files
        for rel_path in expected_files:
            full_path = os.path.join(output_path, rel_path)
            if not os.path.exists(full_path):
                missing.append(rel_path)
            elif os.path.isfile(full_path) and os.path.getsize(full_path) == 0:
                empty.append(rel_path)

        # Scan log for errors
        if log_path:
            log_errors = self.log_scanner.scan(log_path)

        return ValidationResult(
            passed=len(missing) == 0 and len(empty) == 0 and len(log_errors) == 0,
            missing_files=missing,
            empty_files=empty,
            log_errors=log_errors,
        )


class ValidationResult:
    """Result of output validation."""

    def __init__(self, passed: bool, missing_files: List[str],
                 empty_files: List[str], log_errors: List[str]):
        self.passed = passed
        self.missing_files = missing_files
        self.empty_files = empty_files
        self.log_errors = log_errors

    def summary(self) -> str:
        if self.passed:
            return "PASS"
        parts = []
        if self.missing_files:
            parts.append(f"Missing files: {', '.join(self.missing_files)}")
        if self.empty_files:
            parts.append(f"Empty files: {', '.join(self.empty_files)}")
        if self.log_errors:
            parts.append(f"Log errors ({len(self.log_errors)}): "
                         + "; ".join(self.log_errors[:3]))
            if len(self.log_errors) > 3:
                parts.append(f"  ... and {len(self.log_errors) - 3} more")
        return " | ".join(parts)

    def __repr__(self) -> str:
        return f"ValidationResult(passed={self.passed})"
