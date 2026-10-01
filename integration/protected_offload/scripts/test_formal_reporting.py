import unittest
from pathlib import Path
from unittest.mock import patch
from run_formal import task_config, all_cover_goals_reached


class FormalReportingTests(unittest.TestCase):
    def test_actual_completion_task_modes_and_depths(self):
        task=Path(__file__).resolve().parents[1]/"formal/protected_completion_drain.sby"
        self.assertEqual(task_config(task,"prove"),("bmc",32))
        self.assertEqual(task_config(task,"cover"),("cover",40))

    def covers(self,log):
        with patch.object(Path,"exists",return_value=True), patch.object(
                Path,"read_text",side_effect=["cover(a);\ncover(b);\n",log]):
            return all_cover_goals_reached(Path("property.sv"),Path("logfile.txt"))

    def test_every_cover_goal_must_be_reached(self):
        self.assertEqual(self.covers("Reached cover statement at property.sv:1.\n"),(False,1,2))
        self.assertEqual(self.covers("Reached cover statement at property.sv:1.\n"
                                     "Reached cover statement at property.sv:2.\n"),(True,2,2))

    def test_unreached_or_other_harness_cover_is_not_evidence(self):
        self.assertEqual(self.covers("Unreached cover statement at property.sv:1.\n"
                                     "Reached cover statement at other.sv:2.\n"),(False,0,2))

    def test_duplicate_log_line_cannot_replace_another_goal(self):
        self.assertEqual(self.covers("Reached cover statement at property.sv:1.\n"*2),(False,1,2))
