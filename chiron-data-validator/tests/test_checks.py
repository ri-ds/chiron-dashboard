"""Real unit tests for the four check functions in chironval.checks.

These use constructed synthetic statistics payloads shaped exactly like what
the live Chiron dev server actually returns (verified empirically against
http://127.0.0.1:8000 on 2026-07-15 - see README.md), with KNOWN issues baked
in, because the live demo data is small/clean and does not exercise most of
this logic on its own.

Run with:  python -m unittest discover   (from the chiron-data-validator/ dir)
"""

import unittest

from chironval.checks import (
    check_label_consistency,
    check_missing_rate,
    check_numeric_outliers,
    check_type_plausibility,
    run_all_checks,
    _normalize_label,
)


def concept(permanent_id="c1", name="Concept One", concept_type="text"):
    return {"permanent_id": permanent_id, "name": name, "concept_type": concept_type}


class TestNormalizeLabel(unittest.TestCase):
    def test_lowercases_strips_and_collapses_whitespace(self):
        self.assertEqual(_normalize_label("  Male  "), "male")
        self.assertEqual(_normalize_label("MALE"), "male")
        self.assertEqual(_normalize_label("Ma le"), "ma le")
        self.assertEqual(_normalize_label("Ma   le"), "ma le")

    def test_non_string_input_is_stringified(self):
        self.assertEqual(_normalize_label(True), "true")
        self.assertEqual(_normalize_label(42), "42")


class TestMissingRate(unittest.TestCase):
    """Check 1: percent missing = count_missing_values / total_subjects."""

    def test_flags_high_missingness_above_threshold(self):
        # 40% missing, default-style threshold of 0.3 -> should flag.
        stats = {"count_missing_values": 40, "count_subjects_with_missing_values": 5}
        issues = check_missing_rate(concept(), stats, total_subjects=100, threshold=0.3, dataset="ds1")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "high_missingness")
        self.assertAlmostEqual(issues[0].details["rate"], 0.4)
        self.assertEqual(issues[0].dataset, "ds1")

    def test_does_not_flag_below_threshold(self):
        # 10% missing, threshold 0.3 -> should NOT flag.
        stats = {"count_missing_values": 10, "count_subjects_with_missing_values": 2}
        issues = check_missing_rate(concept(), stats, total_subjects=100, threshold=0.3)
        self.assertEqual(issues, [])

    def test_exactly_at_threshold_is_not_flagged(self):
        # rate > threshold is strict, so rate == threshold should not fire.
        stats = {"count_missing_values": 30}
        issues = check_missing_rate(concept(), stats, total_subjects=100, threshold=0.3)
        self.assertEqual(issues, [])

    def test_missing_message_carries_the_limitation_caveat(self):
        stats = {"count_missing_values": 90}
        issues = check_missing_rate(concept(), stats, total_subjects=100, threshold=0.3)
        self.assertIn("silently", issues[0].message.lower())

    def test_no_total_subjects_skips_gracefully(self):
        stats = {"count_missing_values": 90}
        self.assertEqual(check_missing_rate(concept(), stats, total_subjects=None, threshold=0.3), [])
        self.assertEqual(check_missing_rate(concept(), stats, total_subjects=0, threshold=0.3), [])

    def test_missing_count_absent_skips_gracefully(self):
        issues = check_missing_rate(concept(), {}, total_subjects=100, threshold=0.3)
        self.assertEqual(issues, [])

    def test_rate_can_exceed_one_hundred_percent(self):
        # By spec, numerator is value-level, denominator is subject-level;
        # a concept with many rows per subject can exceed 100% "missing".
        stats = {"count_missing_values": 250}
        issues = check_missing_rate(concept(), stats, total_subjects=100, threshold=0.3)
        self.assertEqual(len(issues), 1)
        self.assertGreater(issues[0].details["rate"], 1.0)


class TestNumericOutliers(unittest.TestCase):
    """Check 2: isolated extreme histogram bins, or (fallback) skewed
    min/max/avg with no histogram."""

    def test_flags_isolated_low_outlier_bin(self):
        # Bulk of the data sits in bins with counts ~20-30; one isolated
        # value sits alone in the very first bin, separated by an empty bin.
        histogram = [
            ["[-50 - -40)", 1],   # isolated extreme low outlier
            ["[-40 - -30)", 0],   # gap
            ["[-30 - -20)", 0],   # gap
            ["[0 - 10)", 22],
            ["[10 - 20)", 28],
            ["[20 - 30)", 19],
        ]
        stats = {"histogram_data": histogram}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "numeric_outlier")
        self.assertEqual(issues[0].details["edge"], "minimum")
        self.assertEqual(issues[0].details["bin_count"], 1)

    def test_flags_isolated_high_outlier_bin(self):
        histogram = [
            ["[0 - 10)", 22],
            ["[10 - 20)", 28],
            ["[20 - 30)", 19],
            ["[30 - 40)", 0],  # gap
            ["[9000 - 9010)", 1],  # isolated extreme high outlier
        ]
        stats = {"histogram_data": histogram}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].details["edge"], "maximum")

    def test_does_not_flag_a_normal_smooth_histogram(self):
        # Same shape as a real response observed against the live server for
        # cra_aliquot_number: no isolated bins, nothing should fire.
        histogram = [
            ["[1 - 2)", 10],
            ["[2 - 3)", 5],
            ["[3 - 4)", 3],
            ["[4 - 5)", 1],
            ["[5 - 6]", 2],
        ]
        stats = {"histogram_data": histogram}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(issues, [])

    def test_does_not_flag_when_extreme_bin_not_isolated_by_a_gap(self):
        # Small extreme-bin count but NO empty bin between it and the bulk -
        # by design this should NOT be flagged (not "isolated").
        histogram = [["[0-10)", 1], ["[10-20)", 5], ["[20-30)", 20]]
        stats = {"histogram_data": histogram}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(issues, [])

    def test_ignores_malformed_histogram_entries_without_crashing(self):
        stats = {"histogram_data": [["only one element"], ["fine", 5], None, ["ok", 3]]}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertIsInstance(issues, list)  # must not raise

    def test_fallback_flags_skewed_distribution_when_no_histogram(self):
        # avg sits far closer to min than to max -> should flag as weak signal.
        stats = {"stats": {"count_non_null": 50, "min": 0, "max": 1000, "avg": 5}}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "possible_skewed_distribution")
        self.assertEqual(issues[0].severity, "low")

    def test_fallback_does_not_flag_balanced_distribution(self):
        stats = {"stats": {"count_non_null": 50, "min": 0, "max": 100, "avg": 50}}
        issues = check_numeric_outliers(concept(concept_type="number"), stats)
        self.assertEqual(issues, [])

    def test_fallback_skipped_for_age_shaped_stats(self):
        # age concepts use min_year/max_year/avg_year, not min/max/avg -
        # the fallback should simply not apply (no crash, no false flag).
        stats = {"stats": {"count_non_null": 40, "min_year": 11, "max_year": 41, "avg_year": 29}}
        issues = check_numeric_outliers(concept(concept_type="age"), stats)
        self.assertEqual(issues, [])

    def test_empty_histogram_and_no_stats_is_a_no_op(self):
        self.assertEqual(check_numeric_outliers(concept(), {}), [])
        self.assertEqual(check_numeric_outliers(concept(), {"histogram_data": []}), [])

    def test_isolated_bin_message_hedges_real_subpopulation_possibility(self):
        # Regression: a genuine small clinical subpopulation at a histogram
        # edge (e.g. extreme prematurity) trips the same heuristic as a data
        # error - the message must not read as a definitive verdict.
        histogram = [
            ["[23 - 24)", 3],  # small but genuine extreme-preterm cluster
            ["[24 - 25)", 0],
            ["[25 - 26)", 0],
            ["[37 - 38)", 40],
            ["[38 - 39)", 55],
        ]
        stats = {"histogram_data": histogram}
        issues = check_numeric_outliers(concept(concept_type="number", name="gestational_age_weeks"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "numeric_outlier")
        self.assertIn("symptom, not a", issues[0].message.lower())
        self.assertIn("genuinely real subpopulation", issues[0].message)


class TestLabelConsistency(unittest.TestCase):
    """Check 3: normalization collisions + singleton categories."""

    def test_flags_case_and_whitespace_variants_as_inconsistent(self):
        stats = {
            "values": [
                {"category": "Male", "count": 10, "uniquePatientCount": 8},
                {"category": "male", "count": 3, "uniquePatientCount": 2},
                {"category": " male", "count": 1, "uniquePatientCount": 1},
                {"category": "Female", "count": 12, "uniquePatientCount": 9},
            ]
        }
        issues = check_label_consistency(concept(concept_type="category"), stats)
        collisions = [i for i in issues if i.kind == "label_inconsistency"]
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].details["normalized"], "male")
        self.assertEqual(sorted(collisions[0].details["raw_labels"]), sorted(["Male", "male", " male"]))
        self.assertEqual(collisions[0].details["combined_count"], 14)

    def test_flags_singleton_category_as_lower_severity(self):
        stats = {
            "values": [
                {"category": "Common", "count": 50, "uniquePatientCount": 10},
                {"category": "Rare", "count": 1, "uniquePatientCount": 1},
            ]
        }
        issues = check_label_consistency(concept(concept_type="category"), stats)
        typos = [i for i in issues if i.kind == "possible_typo_or_rare_value"]
        self.assertEqual(len(typos), 1)
        self.assertEqual(typos[0].details["category"], "Rare")
        # singleton severity must be lower than a normalization collision
        self.assertGreater(typos[0].severity_rank(), self._collision_severity_rank())

    def _collision_severity_rank(self):
        stats = {
            "values": [
                {"category": "A", "count": 5, "uniquePatientCount": 1},
                {"category": "a", "count": 5, "uniquePatientCount": 1},
            ]
        }
        issues = check_label_consistency(concept(concept_type="category"), stats)
        return issues[0].severity_rank()

    def test_clean_distinct_categories_are_not_flagged(self):
        stats = {
            "values": [
                {"category": "Male", "count": 10, "uniquePatientCount": 8},
                {"category": "Female", "count": 12, "uniquePatientCount": 9},
            ]
        }
        issues = check_label_consistency(concept(concept_type="category"), stats)
        self.assertEqual(issues, [])

    def test_flat_text_values_flag_case_variants_without_singleton_check(self):
        # text concept stats: plain list of unique strings, no counts at all.
        stats = {"values": ["Aortic Stenosis", "aortic stenosis", "Mitral Regurgitation"]}
        issues = check_label_consistency(concept(concept_type="text"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "label_inconsistency")
        # no possible_typo_or_rare_value should ever appear for flat text (no counts)
        self.assertNotIn("possible_typo_or_rare_value", [i.kind for i in issues])

    def test_boolean_shaped_values_are_handled_like_category(self):
        stats = {
            "values": [
                {"category": "True", "count": 24, "uniquePatientCount": 5},
                {"category": "False", "count": 22, "uniquePatientCount": 4},
            ]
        }
        issues = check_label_consistency(concept(concept_type="boolean"), stats)
        self.assertEqual(issues, [])  # True/False are already distinct after normalization

    def test_no_values_key_is_a_no_op(self):
        self.assertEqual(check_label_consistency(concept(), {}), [])
        self.assertEqual(check_label_consistency(concept(), {"values": []}), [])

    def test_unhashable_flat_values_are_skipped_without_crashing(self):
        # Regression: an unfamiliar concept-type shape (e.g. ontology/
        # undefined - see README "Other known scope limits") can return a
        # flat list whose entries are themselves lists, which are unhashable
        # and must not raise TypeError out of this function.
        stats = {"values": [["ICD10:A01", "ICD10:B02"], ["ICD10:C03"]]}
        issues = check_label_consistency(concept(concept_type="ontology"), stats)
        self.assertEqual(issues, [])  # unhashable entries skipped, nothing to flag

    def test_unhashable_entries_do_not_block_valid_entries_in_same_list(self):
        # A mix of a genuinely colliding pair of strings alongside an
        # unhashable entry should still surface the real collision.
        stats = {"values": ["Male", "male", ["nested", "list"]]}
        issues = check_label_consistency(concept(concept_type="text"), stats)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "label_inconsistency")
        self.assertEqual(issues[0].details["normalized"], "male")


class TestTypePlausibility(unittest.TestCase):
    """Check 4: category concepts with implausibly many distinct values."""

    def test_flags_above_absolute_threshold(self):
        values = [{"category": f"val_{i}", "count": 1, "uniquePatientCount": 1} for i in range(60)]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=1000)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "possible_metadata_mismatch")
        self.assertEqual(issues[0].details["distinct_values"], 60)

    def test_flags_above_relative_threshold_when_enough_subjects(self):
        # 25 distinct values / 100 subjects = 25% > 20% relative threshold,
        # and 100 subjects clears the minimum-subjects floor for this rule.
        values = [{"category": f"val_{i}", "count": 1, "uniquePatientCount": 1} for i in range(25)]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=100)
        self.assertEqual(len(issues), 1)

    def test_small_dataset_does_not_trip_relative_threshold(self):
        # 3 distinct values / 6 subjects = 50%, which WOULD trip the relative
        # rule, but total_subjects is below the minimum-subjects floor
        # (documented guard against false positives on tiny demo datasets).
        values = [{"category": v, "count": 1, "uniquePatientCount": 1} for v in ("A", "B", "C")]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=6)
        self.assertEqual(issues, [])

    def test_only_applies_to_category_concept_type(self):
        values = [{"category": f"val_{i}", "count": 1, "uniquePatientCount": 1} for i in range(60)]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="number_with_categories"), stats, total_subjects=1000)
        self.assertEqual(issues, [])

    def test_reasonable_category_cardinality_is_not_flagged(self):
        values = [{"category": v, "count": 5, "uniquePatientCount": 3} for v in ("Male", "Female", "Other")]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=1000)
        self.assertEqual(issues, [])

    def test_well_populated_controlled_vocabulary_is_not_flagged(self):
        # Regression: 80 distinct ICD-10-style codes, each recurring 60 times
        # across 55 unique patients out of 5000 subjects - a legitimate
        # high-cardinality controlled vocabulary, NOT free text (free text
        # would show near-singleton counts per distinct value, like this
        # tool's own flat "text" values which carry no counts at all).
        values = [
            {"category": f"ICD10:{i:03d}", "count": 60, "uniquePatientCount": 55}
            for i in range(80)
        ]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=5000)
        self.assertEqual(issues, [])

    def test_high_cardinality_free_text_like_pattern_is_still_flagged(self):
        # Same distinct-value count as the controlled-vocabulary case above,
        # but each value occurs essentially once - a genuine free-text-like
        # pattern - so this should still fire.
        values = [{"category": f"val_{i}", "count": 1, "uniquePatientCount": 1} for i in range(80)]
        stats = {"values": values}
        issues = check_type_plausibility(concept(concept_type="category"), stats, total_subjects=5000)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "possible_metadata_mismatch")
        self.assertEqual(issues[0].details["singleton_fraction"], 1.0)


class TestRunAllChecks(unittest.TestCase):
    def test_integration_runs_all_four_checks_and_tags_dataset(self):
        stats = {
            "count_missing_values": 40,
            "count_subjects_with_missing_values": 5,
            "values": [
                {"category": "Male", "count": 10, "uniquePatientCount": 8},
                {"category": "MALE", "count": 1, "uniquePatientCount": 1},
            ],
        }
        issues = run_all_checks(
            concept_meta=concept(concept_type="category"),
            statistics=stats,
            total_subjects=100,
            missing_threshold=0.3,
            dataset="dataset1_stored",
        )
        kinds = {i.kind for i in issues}
        self.assertIn("high_missingness", kinds)
        self.assertIn("label_inconsistency", kinds)
        self.assertIn("possible_typo_or_rare_value", kinds)
        self.assertTrue(all(i.dataset == "dataset1_stored" for i in issues))


if __name__ == "__main__":
    unittest.main()
