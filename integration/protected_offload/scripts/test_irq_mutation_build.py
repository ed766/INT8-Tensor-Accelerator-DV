import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_crossover_mutations as runner


class IRQMutationBuildTest(unittest.TestCase):
    def test_fresh_build_directories_and_failure_logs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            def compile_failure(command):
                obj = Path(command[command.index("--Mdir") + 1])
                self.assertTrue(obj.is_dir())
                return subprocess.CompletedProcess(command, 1, "compiler stdout\n", "compiler failure\n")
            with patch.object(runner, "run", side_effect=compile_failure):
                for mutant, name in ((False, "irq_nominal"), (True, "irq_mutant")):
                    result = runner.irq_build(mutant)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual("-DPROTECTED_MUT_LOST_SIMULTANEOUS_IRQ" in result.args, mutant)
                    self.assertEqual((Path(directory) / "build/protected_offload/mutations" / name / "build.log").read_text(),
                                     "compiler stdout\ncompiler failure\n")


if __name__ == "__main__":
    unittest.main()
