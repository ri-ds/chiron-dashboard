"""Tests for the configurable rules (RuleConfig) added on top of the original
four checks. These prove enable/disable + threshold overrides work, and that
config parsing is tolerant. The original checks' default behavior is covered by
test_checks.py and must remain unchanged (rules=None path)."""

import unittest

from chironval.checks import check_label_consistency, run_all_checks
from chironval.rules import RuleConfig


def meta(ctype="number"):
    return {"permanent_id": "c1", "name": "Concept 1", "concept_type": ctype}


class RuleConfigParsing(unittest.TestCase):
    def test_defaults_match_historical_constants(self):
        rc = RuleConfig()
        self.assertEqual(rc.missing_threshold, 0.30)
        self.assertEqual(rc.isolation_ratio, 0.10)
        self.assertEqual(rc.category_abs_threshold, 50)
        self.assertTrue(rc.missing_rate_enabled)

    def test_partial_dict_keeps_other_defaults(self):
        rc = RuleConfig.from_dict({"missing_threshold": 0.15})
        self.assertEqual(rc.missing_threshold, 0.15)
        self.assertEqual(rc.category_abs_threshold, 50)  # untouched

    def test_bad_value_falls_back_to_default(self):
        rc = RuleConfig.from_dict({"missing_threshold": "not-a-number"})
        self.assertEqual(rc.missing_threshold, 0.30)

    def test_string_boolean_is_coerced(self):
        rc = RuleConfig.from_dict({"numeric_outlier_enabled": "false"})
        self.assertFalse(rc.numeric_outlier_enabled)
        rc2 = RuleConfig.from_dict({"numeric_outlier_enabled": "true"})
        self.assertTrue(rc2.numeric_outlier_enabled)

    def test_unknown_keys_ignored(self):
        rc = RuleConfig.from_dict({"totally_unknown": 5, "missing_threshold": 0.2})
        self.assertEqual(rc.missing_threshold, 0.2)


class DisableAndTuneChecks(unittest.TestCase):
    def test_disabling_missing_rate_suppresses_it(self):
        stats = {"count_missing_values": 40}  # 40/100 = 40% > default 30%
        fired = run_all_checks(meta(), stats, 100, 0.3)  # default path
        self.assertTrue(any(i.kind == "high_missingness" for i in fired))
        off = run_all_checks(meta(), stats, 100, 0.3,
                             rules=RuleConfig.from_dict({"missing_rate_enabled": False}))
        self.assertFalse(any(i.kind == "high_missingness" for i in off))

    def test_lowering_threshold_makes_it_fire(self):
        stats = {"count_missing_values": 20}  # 20/100 = 20% < default 30%
        self.assertFalse(run_all_checks(meta(), stats, 100, 0.3))  # nothing at default
        fired = run_all_checks(meta(), stats, 100, 0.3,
                               rules=RuleConfig.from_dict({"missing_threshold": 0.10}))
        self.assertTrue(any(i.kind == "high_missingness" for i in fired))

    def test_flag_singletons_toggle(self):
        stats = {"values": [{"category": "A", "count": 1}, {"category": "B", "count": 5}]}
        on = check_label_consistency(meta("category"), stats, flag_singletons=True)
        self.assertTrue(any(i.kind == "possible_typo_or_rare_value" for i in on))
        off = check_label_consistency(meta("category"), stats, flag_singletons=False)
        self.assertFalse(any(i.kind == "possible_typo_or_rare_value" for i in off))

    def test_disabling_all_checks_yields_nothing(self):
        stats = {"count_missing_values": 99, "values": [{"category": "x", "count": 1}]}
        rc = RuleConfig.from_dict({
            "missing_rate_enabled": False, "numeric_outlier_enabled": False,
            "label_consistency_enabled": False, "type_plausibility_enabled": False,
        })
        self.assertEqual(run_all_checks(meta("category"), stats, 100, 0.3, rules=rc), [])


if __name__ == "__main__":
    unittest.main()
