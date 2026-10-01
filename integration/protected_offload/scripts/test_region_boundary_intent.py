import unittest
from check_crossover_scenario_intents import qualify


class RegionBoundaryIntentTests(unittest.TestCase):
    def events(self):
        events = []
        for address in ("10000000", "1000fffc", "30000000", "3000fffc"):
            data = f"{0x619ac357 ^ int(address, 16):08x}"
            for direction in ("write", "read"):
                events.append({"kind": "RETIRE", "epoch": "0", "eid": str(len(events)+1),
                               "cycle": str(len(events)+1), "trap": "0", "mem_addr": address,
                               "mem_wmask": "f" if direction == "write" else "0",
                               "mem_rmask": "f" if direction == "read" else "0",
                               "mem_wdata": data, "mem_rdata": data})
        for address, cause in (("10010000", 5), ("10010000", 7),
                               ("20010000", 5), ("20010000", 7),
                               ("20000000", 5), ("2000fffc", 5)):
            events.append({"kind": "RETIRE", "epoch": "0", "eid": str(len(events)+1),
                           "cycle": str(len(events)+1), "trap": "1", "mem_addr": address,
                           "mcause": f"{cause:08x}", "rd_addr": "0"})
        return events

    def result(self, events):
        return qualify("apb_axi__case_4", {}, events)["scenario_intent_status"]

    def test_complete_boundary_matrix_passes(self):
        self.assertEqual(self.result(self.events()), "PASS")

    def test_corrupt_upper_word_readback_fails(self):
        events = self.events()
        events[3]["mem_rdata"] = "00000000"
        self.assertEqual(self.result(events), "FAIL")

    def test_missing_last_region_edge_fails(self):
        self.assertEqual(self.result(self.events()[:6]+self.events()[8:]), "FAIL")

    def test_decode_error_cause_and_register_side_effect_fail(self):
        for field, value in (("mcause", "00000002"), ("rd_addr", "3")):
            events = self.events()
            events[8][field] = value
            self.assertEqual(self.result(events), "FAIL")


if __name__ == "__main__":
    unittest.main()
