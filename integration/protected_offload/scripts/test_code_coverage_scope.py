"""Keep functional decoding in the raw control coverage denominator."""
import unittest

from run_compute_crossover_code_coverage import ROOT, scope_for


class CoverageScopeTests(unittest.TestCase):
    def test_address_decoding_is_not_verification_only(self):
        path = "integration/protected_offload/rtl/rv32_protected_shared_top.sv"
        lines = (ROOT / path).read_text().splitlines()
        for number, text in enumerate(lines, 1):
            if text.strip().startswith("assign ") and "_sel=" in text:
                self.assertEqual(scope_for(path, str(number)), "new_protected_offload_control_rtl")

    def test_shadow_translation_is_verification_only(self):
        path = "integration/protected_offload/rtl/rv32_protected_shared_top.sv"
        lines = (ROOT / path).read_text().splitlines()
        number = next(i for i, text in enumerate(lines, 1) if "root_pte = ownership_pte_shadow" in text)
        self.assertEqual(scope_for(path, str(number)), "verification_ownership_monitor")


if __name__ == "__main__":
    unittest.main()
