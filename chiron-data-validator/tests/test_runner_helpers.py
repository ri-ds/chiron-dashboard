"""Unit tests for the small pure helpers in chironval.runner (no network)."""

import unittest

from chironval.runner import _classify_skip_reason, _parse_total_subjects


class TestClassifySkipReason(unittest.TestCase):
    def test_prefiltered(self):
        self.assertEqual(
            _classify_skip_reason("You must provide a prefilter value."), "prefiltered"
        )

    def test_permission_denied_by_text(self):
        self.assertEqual(
            _classify_skip_reason("The user doesn't have permission to view this concept."),
            "permission_denied",
        )

    def test_permission_denied_by_403(self):
        self.assertEqual(_classify_skip_reason("HTTP 403 permission denied: ..."), "permission_denied")

    def test_not_found(self):
        self.assertEqual(_classify_skip_reason("HTTP 404 not found: ..."), "not_found")

    def test_network_error(self):
        self.assertEqual(_classify_skip_reason("network error: Connection refused"), "network_error")

    def test_other(self):
        self.assertEqual(_classify_skip_reason("something totally unexpected"), "other")


class TestParseTotalSubjects(unittest.TestCase):
    def test_parses_numeric_string(self):
        self.assertEqual(_parse_total_subjects({"subjectCount": "6"}), 6)

    def test_missing_key_returns_none(self):
        self.assertIsNone(_parse_total_subjects({}))

    def test_non_numeric_string_returns_none_without_raising(self):
        self.assertIsNone(_parse_total_subjects({"subjectCount": "unknown"}))

    def test_none_value_returns_none(self):
        self.assertIsNone(_parse_total_subjects({"subjectCount": None}))


if __name__ == "__main__":
    unittest.main()
