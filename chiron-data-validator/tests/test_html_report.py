"""Unit tests for chironval.html_report.

Run with:  python -m unittest discover   (from the chiron-data-validator/ dir)
"""

import os
import tempfile
import unittest

from chironval.html_report import render_report_html, write_html_report
from chironval.models import DatasetRunResult, Issue, SkippedConcept


def _issue(**overrides):
    base = dict(
        dataset="dataset1_stored",
        concept_id="c1",
        concept_name="Concept One",
        concept_type="category",
        kind="high_missingness",
        severity="medium",
        message="4 missing value(s) vs 6 subject(s)",
        details={},
    )
    base.update(overrides)
    return Issue(**base)


class TestRenderReportHtml(unittest.TestCase):
    def test_standalone_true_returns_full_document(self):
        html = render_report_html([], 0.3, "http://127.0.0.1:8000", standalone=True)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<html", html)
        self.assertIn("<head>", html)
        self.assertIn("<body>", html)
        self.assertIn("<title>Chiron Data Validator Report</title>", html)

    def test_standalone_false_returns_fragment_without_document_shell(self):
        html = render_report_html([], 0.3, "http://127.0.0.1:8000", standalone=False)
        self.assertNotIn("<!doctype", html.lower())
        self.assertNotIn("<html", html.lower())
        self.assertNotIn("<head>", html.lower())
        self.assertNotIn("<body>", html.lower())
        self.assertIn("<title>Chiron Data Validator Report</title>", html)
        self.assertIn("<style>", html)

    def test_no_datasets_still_renders_without_crashing(self):
        html = render_report_html([], 0.3, "http://127.0.0.1:8000")
        self.assertIn("Chiron Data Validator Report", html)
        self.assertIn('<span class="n">0</span>', html)  # total issues tile

    def test_issue_counts_and_severity_appear_in_output(self):
        dr = DatasetRunResult(
            dataset="dataset1_stored",
            total_subjects=6,
            concept_count=2,
            issues=[
                _issue(severity="high", kind="label_inconsistency"),
                _issue(severity="low", kind="possible_typo_or_rare_value", concept_id="c2"),
            ],
        )
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertIn('data-severity="high"', html)
        self.assertIn('data-severity="low"', html)
        self.assertIn('data-kind="label_inconsistency"', html)
        self.assertIn('data-dataset="dataset1_stored"', html)
        # total issues stat tile
        self.assertIn('<span class="n">2</span>', html)

    def test_html_special_characters_are_escaped_not_injected_raw(self):
        # A concept name / message containing HTML-significant characters
        # must not appear unescaped in the output (would break the page or,
        # in the worst case, be a self-XSS if this file is later served
        # rather than opened locally - escape regardless).
        dr = DatasetRunResult(
            dataset="dataset1_stored",
            total_subjects=6,
            concept_count=1,
            issues=[
                _issue(
                    concept_name='<script>alert(1)</script>',
                    message='Category "A&B" <b>bold</b> occurs once',
                )
            ],
        )
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('Category "A&B" <b>bold</b>', html)

    def test_dataset_error_is_rendered_and_does_not_crash(self):
        dr = DatasetRunResult(dataset="dataset3_stored", total_subjects=None, concept_count=0, error="HTTP 403 permission denied")
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertIn("dataset3_stored", html)
        self.assertIn("HTTP 403 permission denied", html)

    def test_no_issues_dataset_renders_no_issues_message(self):
        dr = DatasetRunResult(dataset="dataset2_stored", total_subjects=6, concept_count=10, issues=[])
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertIn("No issues found.", html)

    def test_skipped_concepts_are_rendered(self):
        dr = DatasetRunResult(
            dataset="dataset1_stored",
            total_subjects=6,
            concept_count=5,
            issues=[],
            skipped=[
                SkippedConcept(
                    dataset="dataset1_stored",
                    concept_id="c9",
                    concept_name="Prefiltered Concept",
                    reason_kind="prefiltered",
                    reason="You must provide a prefilter value.",
                )
            ],
        )
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertIn("Prefiltered Concept", html)
        self.assertIn("prefiltered", html)

    def test_search_blob_includes_concept_name_and_id_not_just_message(self):
        # Regression: the concept name/id is only rendered once in the
        # parent .concept-group header, not repeated inside every .issue
        # div. If the client-side search matched against the issue's own
        # textContent (kind + message only), searching by concept name
        # (e.g. "provider") would silently return zero results even for
        # issues that obviously belong to that concept. The searchable
        # text must be exposed via a data attribute that includes the
        # concept id and name.
        dr = DatasetRunResult(
            dataset="dataset1_stored",
            total_subjects=6,
            concept_count=1,
            issues=[
                _issue(
                    concept_id="crp_provider_name",
                    concept_name="provider name",
                    message='Category "Bill Smith" occurs exactly once',
                )
            ],
        )
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        start = html.index('<div class="issue')
        end = html.index("</div>", start)
        issue_div = html[start:end]
        self.assertIn("data-search=", issue_div)
        self.assertIn("provider name", issue_div.lower())
        self.assertIn("crp_provider_name", issue_div.lower())

    def test_kind_and_dataset_filter_checkboxes_reflect_actual_data(self):
        dr = DatasetRunResult(
            dataset="dataset1_stored",
            total_subjects=6,
            concept_count=1,
            issues=[_issue(kind="numeric_outlier")],
        )
        html = render_report_html([dr], 0.3, "http://127.0.0.1:8000")
        self.assertIn('class="kind-filter" value="numeric_outlier"', html)
        self.assertIn('class="dataset-filter" value="dataset1_stored"', html)


class TestWriteHtmlReport(unittest.TestCase):
    def test_writes_report_to_a_valid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.html")
            write_html_report(path, "<html>hello</html>")
            with open(path, "r", encoding="utf-8") as f:
                self.assertIn("hello", f.read())

    def test_missing_parent_directory_raises_informative_oserror_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "does_not_exist", "out.html")
            with self.assertRaises(OSError) as ctx:
                write_html_report(path, "<html>hello</html>")
            self.assertIn(path, str(ctx.exception))

    def test_unwritable_directory_raises_informative_oserror(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.html")
            os.chmod(tmp, 0o500)
            try:
                with self.assertRaises(OSError) as ctx:
                    write_html_report(path, "<html>hello</html>")
                self.assertIn(path, str(ctx.exception))
            finally:
                os.chmod(tmp, 0o700)


if __name__ == "__main__":
    unittest.main()
