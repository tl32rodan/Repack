"""Tests for false-negative prevention: output validation and log scanning."""

import os
import tempfile
import unittest

from repack.core.validation import LogScanner, OutputValidator


class TestLogScanner(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_log(self, content: str) -> str:
        path = os.path.join(self.tmpdir, "test.log")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_clean_log(self):
        path = self._write_log("INFO: all good\nDone successfully\n")
        scanner = LogScanner()
        errors = scanner.scan(path)
        self.assertEqual(errors, [])

    def test_detect_error(self):
        path = self._write_log("INFO: starting\nERROR: something broke\nINFO: done\n")
        scanner = LogScanner()
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 1)
        self.assertIn("ERROR", errors[0])

    def test_detect_fatal(self):
        path = self._write_log("FATAL: cannot continue\n")
        scanner = LogScanner()
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 1)

    def test_detect_failed(self):
        path = self._write_log("Step 3 FAILED\n")
        scanner = LogScanner()
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 1)

    def test_case_insensitive(self):
        path = self._write_log("error: lowercase\nError: mixed\n")
        scanner = LogScanner()
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 2)

    def test_custom_pattern(self):
        path = self._write_log("VIOLATION: timing constraint\n")
        scanner = LogScanner(extra_patterns=[r"\bVIOLATION\b"])
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 1)

    def test_ignore_pattern(self):
        """Patterns like 'ERROR_COUNT: 0' should be ignorable."""
        path = self._write_log("ERROR_COUNT: 0\nERROR: real problem\n")
        scanner = LogScanner(ignore_patterns=[r"ERROR_COUNT:\s*0"])
        errors = scanner.scan(path)
        self.assertEqual(len(errors), 1)
        self.assertIn("real problem", errors[0])

    def test_missing_log(self):
        scanner = LogScanner()
        errors = scanner.scan("/nonexistent/path.log")
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])


class TestOutputValidator(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _create_file(self, rel_path: str, content: str = "data") -> str:
        full = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        return full

    def test_all_files_present(self):
        self._create_file("a.lib")
        self._create_file("b.db")
        validator = OutputValidator()
        result = validator.validate(self.tmpdir, ["a.lib", "b.db"])
        self.assertTrue(result.passed)

    def test_missing_file(self):
        self._create_file("a.lib")
        validator = OutputValidator()
        result = validator.validate(self.tmpdir, ["a.lib", "b.db"])
        self.assertFalse(result.passed)
        self.assertIn("b.db", result.missing_files)

    def test_empty_file(self):
        self._create_file("a.lib", content="")
        validator = OutputValidator()
        result = validator.validate(self.tmpdir, ["a.lib"])
        self.assertFalse(result.passed)
        self.assertIn("a.lib", result.empty_files)

    def test_log_error_fails_validation(self):
        """Even with all files present, log errors should fail validation."""
        self._create_file("a.lib")
        log_path = self._create_file("run.log", "ERROR: oops\n")
        validator = OutputValidator()
        result = validator.validate(self.tmpdir, ["a.lib"], log_path=log_path)
        self.assertFalse(result.passed)
        self.assertTrue(len(result.log_errors) > 0)

    def test_no_expected_files_still_scans_log(self):
        """When expected_files=[], only log scanning runs."""
        log_path = self._create_file("run.log", "ERROR: something\n")
        validator = OutputValidator()
        result = validator.validate(self.tmpdir, [], log_path=log_path)
        self.assertFalse(result.passed)

    def test_clean_pass(self):
        """All files present + clean log = PASS."""
        self._create_file("output.lib")
        log_path = self._create_file("run.log", "INFO: all good\n")
        validator = OutputValidator()
        result = validator.validate(
            self.tmpdir, ["output.lib"], log_path=log_path
        )
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
