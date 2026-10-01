import unittest
from check_crossover_scenario_intents import qualify


class SubmitPressureIntentTests(unittest.TestCase):
    def events(self):
        rows=[{"kind":"SUBMIT", "cycle":str(i+1), "tag":str(53+i), "asid":"1"} for i in range(5)]
        rows.append({"kind":"RETIRE", "cycle":"6", "mem_addr":"4000001c", "mem_rmask":"f", "mem_rdata":"00000042"})
        rows.append({"kind":"SUBMIT_REJECT", "cycle":"7", "tag":"58", "occupancy":"4"})
        rows.extend({"kind":"COMPLETE", "cycle":str(20+i), "tag":str(53+i), "asid":"1", "status":"0", "vectors_done":"1"} for i in range(5))
        return [dict(e, epoch="0", eid=str(i+1)) for i,e in enumerate(rows)]

    def result(self, events):
        return qualify("queues_configuration__case_1", {}, events)["scenario_intent_status"]

    def test_full_queue_rejection_and_drain_pass(self):
        self.assertEqual(self.result(self.events()), "PASS")

    def test_duplicate_tag_is_not_capacity_rejection(self):
        events=self.events();events[6]["tag"]="53"
        self.assertEqual(self.result(events), "FAIL")

    def test_non_full_queue_rejection_fails(self):
        events=self.events();events[6]["occupancy"]="3"
        self.assertEqual(self.result(events), "FAIL")

    def test_missing_completion_or_bad_result_fails(self):
        self.assertEqual(self.result(self.events()[:-1]), "FAIL")
        events=self.events();events[-1]["status"]="5"
        self.assertEqual(self.result(events), "FAIL")


if __name__=="__main__":
    unittest.main()
