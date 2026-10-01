import unittest
from check_crossover_scenario_intents import qualify


class AccessLegalityIntentTests(unittest.TestCase):
    def events(self):
        return [{"kind": "RETIRE", "eid": str(i), "epoch": "0", "cycle": str(i),
                 "trap": "1", "mcause": f"{cause:08x}", "rd_addr": "0",
                 "mem_rmask": "0", "mem_wmask": "0"}
                for i, cause in enumerate((5, 7, 4, 6), 1)]

    def test_exact_precise_traps_pass(self):
        result = qualify("apb_axi__case_5", {}, self.events())
        self.assertEqual(result["scenario_intent_status"], "PASS")

    def test_illegal_instruction_is_not_store_access_fault(self):
        events = self.events()
        events[1]["mcause"] = "00000002"
        self.assertEqual(qualify("apb_axi__case_5", {}, events)["scenario_intent_status"], "FAIL")

    def test_side_effects_fail(self):
        for field, value in (("rd_addr", "5"), ("mem_wmask", "f")):
            events = self.events()
            events[0][field] = value
            self.assertEqual(qualify("apb_axi__case_5", {}, events)["scenario_intent_status"], "FAIL")

    def test_bus_issue_on_faulting_edge_fails(self):
        events = self.events()
        events.append({"kind": "AXI_AR", "epoch": "0", "cycle": "1", "eid": "5"})
        self.assertEqual(qualify("apb_axi__case_5", {}, events)["scenario_intent_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
