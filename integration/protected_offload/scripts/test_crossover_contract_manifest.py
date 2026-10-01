"""Keep the release denominator tied to the original behavioral requirements."""
import json
from pathlib import Path
import unittest


class CrossoverContractManifestTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "coverage/compute_crossover_manifest.json"
        self.manifest = json.loads(path.read_text())
        self.contracts = self.manifest["required_scenario_intents"]

    def test_every_family_has_six_explicit_distinct_contracts(self):
        self.assertEqual(len(self.contracts), 48)
        self.assertEqual(len(set(self.contracts.values())), 48)
        for family in self.manifest["families"]:
            self.assertEqual(sum(name.startswith(family + "__") for name in self.contracts), 6)

    def test_substitute_behaviors_cannot_satisfy_original_contracts(self):
        substitutions = {
            "apb_axi__case_4": "delayed_axi_read_and_write_responses",
            "apb_axi__case_5": "device_interrupt_taken",
            "queues_configuration__case_1": "single_job_completion_after_commit",
            "queues_configuration__case_4": "two_job_publish_pop_collision",
            "translation_recovery__fault_1": "input_read_translation_fault",
            "translation_recovery__case_6": "read_write_translation_hit_miss",
        }
        for scenario, substitute in substitutions.items():
            with self.subTest(scenario=scenario):
                self.assertNotEqual(self.contracts[scenario], substitute)


if __name__ == "__main__":
    unittest.main()
