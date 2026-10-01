import unittest
from stimulus_provenance import witness_implementation, INDEPENDENT
import hashlib


class StimulusProvenanceTests(unittest.TestCase):
    def test_independent_driver_requires_its_actual_source_hash(self):
        summary=dict(stimulus_origin="independent_firmware_driver",stimulus_generator_sha256="fake")
        with self.assertRaises(ValueError):witness_implementation(summary,[dict(kind="XLATE_RSP")])
        summary["stimulus_generator_sha256"]=hashlib.sha256(INDEPENDENT.read_bytes()).hexdigest()
        self.assertNotEqual(witness_implementation(summary,[dict(kind="XLATE_RSP")]),
                            witness_implementation({},[dict(kind="XLATE_RSP")]))
    def test_names_seeds_and_wrapper_generators_do_not_establish_independence(self):
        witness=[dict(kind="XLATE_RSP",eid="1")]
        a=dict(scenario="permission_case",seed="1",stimulus_origin="directed_scenario_program",
               stimulus_generator_sha256="a")
        b=dict(scenario="cpu_stream_case",seed="2",stimulus_origin="seeded_firmware_schedule",
               stimulus_generator_sha256="b")
        self.assertEqual(witness_implementation(a,witness),witness_implementation(b,witness))

    def test_only_executed_stream_retirement_uses_cpu_generator(self):
        summary=dict(stimulus_origin="generated_cpu_instruction_stream",
                     cpu_stream_start_pc="00001000",cpu_stream_end_pc="00001100")
        common=witness_implementation(summary,[dict(kind="RETIRE",pc="00002000")])
        stream=witness_implementation(summary,[dict(kind="RETIRE",pc="00001004")])
        self.assertNotEqual(common,stream)
        self.assertEqual(common,witness_implementation(summary,[dict(kind="XLATE_RSP")]))

    def test_missing_or_malformed_linked_range_cannot_claim_stream_independence(self):
        summary=dict(stimulus_origin="generated_cpu_instruction_stream",cpu_stream_start_pc="bad!")
        witness=[dict(kind="RETIRE",pc="00001004")]
        self.assertEqual(witness_implementation(summary,witness),witness_implementation({},witness))
