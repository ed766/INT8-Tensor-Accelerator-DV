"""A detected defect must match its designated bucket exactly once."""
import csv
import io
import unittest
from unittest.mock import MagicMock, patch

import check_crossover_mutations as checker


class MutationQualificationTests(unittest.TestCase):
    def rows(self):
        return [dict(mutation=name, status="DETECTED", activated="true",
                     compile_status="PASS", nominal_control="PASS",
                     detection="intended_" + name, expected_failure="intended_" + name)
                for name in sorted(checker.REQUIRED)]

    def verdict(self, rows):
        data = io.StringIO()
        writer = csv.DictWriter(data, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        report = MagicMock()
        report.exists.return_value = True
        report.open.return_value = io.StringIO(data.getvalue())
        with patch.object(checker, "REPORT", report), patch("builtins.print"):
            return checker.main()

    def test_matching_designated_failures_pass(self):
        self.assertEqual(self.verdict(self.rows()), 0)

    def test_unrelated_non_generic_failure_does_not_pass(self):
        rows = self.rows()
        rows[0]["detection"] = "different_assertion"
        self.assertEqual(self.verdict(rows), 1)

    def test_duplicate_mutation_row_does_not_pass(self):
        rows = self.rows()
        self.assertEqual(self.verdict(rows + [rows[0]]), 1)


if __name__ == "__main__":
    unittest.main()
