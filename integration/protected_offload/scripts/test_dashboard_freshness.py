"""Independent-driver evidence must not bypass dashboard freshness checks."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_crossover_dashboard as dashboard


class DashboardFreshnessTest(unittest.TestCase):
    def test_independent_driver_checker_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = root / "integration/protected_offload/scripts/check_crossover_trace.py"
            checker.parent.mkdir(parents=True)
            checker.write_text("checker-version-one\n")
            report = root / "reports/compute_crossover_independent_model.csv"
            report.parent.mkdir()
            digest = hashlib.sha256(checker.read_bytes()).hexdigest()
            report.write_text("status,checker_sha256,observer_build_id\n"
                              f"PASS,{digest},actual-observer-build\n")
            with patch.object(dashboard, "ROOT", root):
                self.assertEqual(dashboard.report_status(str(report.relative_to(root)))[0], "PASS")
                checker.write_text("checker-version-two\n")
                self.assertEqual(dashboard.report_status(str(report.relative_to(root)))[0], "STALE")

    def test_independent_driver_missing_observer_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checker = root / "integration/protected_offload/scripts/check_crossover_trace.py"
            checker.parent.mkdir(parents=True)
            checker.write_text("checker\n")
            report = root / "reports/compute_crossover_independent_model.csv"
            report.parent.mkdir()
            digest = hashlib.sha256(checker.read_bytes()).hexdigest()
            report.write_text(f"status,checker_sha256,observer_build_id\nPASS,{digest},\n")
            with patch.object(dashboard, "ROOT", root):
                self.assertEqual(dashboard.report_status(str(report.relative_to(root)))[0], "STALE")


if __name__ == "__main__":
    unittest.main()
