import unittest
from check_crossover_scenario_intents import qualify


class InactiveBankIntentTests(unittest.TestCase):
    def events(self):
        records = [
            {"kind": "SUBMIT", "bank": "0", "generation": "7", "tag": "53"},
            {"kind": "APB", "write": "1", "addr": "40001010", "wdata": "0000ff07", "error": "0"},
            {"kind": "RETIRE", "mem_addr": "40001010", "mem_rmask": "f", "mem_rdata": "0000ff07"},
            {"kind": "ACCEL_CFG", "bank": "1", "data": "0000005a"},
            {"kind": "APB", "write": "1", "addr": "40001010", "wdata": "00000007", "error": "0"},
            {"kind": "RETIRE", "mem_addr": "40001010", "mem_rmask": "f", "mem_rdata": "00000007"},
            {"kind": "COMPLETE_PUBLISH", "tag": "53"},
        ]
        return [dict(event, epoch="0", cycle=str(i+1), eid=str(i+1)) for i, event in enumerate(records)]

    def result(self, events):
        return qualify("queues_configuration__case_6", {}, events)["scenario_intent_status"]

    def test_live_free_bank_program_and_wrap_pass(self):
        self.assertEqual(self.result(self.events()), "PASS")

    def test_wrong_bank_and_rejected_generation_fail(self):
        for index, field, value in ((3, "bank", "0"), (4, "error", "1"), (5, "mem_rdata", "00000008")):
            events = self.events()
            events[index][field] = value
            self.assertEqual(self.result(events), "FAIL")

    def test_update_after_completion_does_not_cover_live_update(self):
        events = self.events()
        events[-1]["cycle"] = "3"
        self.assertEqual(self.result(events), "FAIL")


if __name__ == "__main__":
    unittest.main()
