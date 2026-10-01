import unittest
from check_crossover_scenario_intents import qualify


class PermissionDenialIntentTests(unittest.TestCase):
    def events(self, write):
        return [
            {"kind":"XLATE_RSP", "eid":"1", "cycle":"10", "epoch":"0", "tag":"53", "write":str(write), "fault":"2"},
            {"kind":"COMPLETE", "eid":"2", "cycle":"20", "epoch":"0", "tag":"53", "status":"3" if write else "2", "fault_stage":"3" if write else "1", "vectors_done":"0"},
        ]

    def result(self, write, events):
        name=f"translation_recovery__fault_{2 if write else 1}"
        return qualify(name, {}, events)["scenario_intent_status"]

    def test_real_permission_denials_pass(self):
        for write in (0,1):
            self.assertEqual(self.result(write,self.events(write)),"PASS")

    def test_missing_mapping_is_not_permission_denial(self):
        for write in (0,1):
            events=self.events(write);events[0]["fault"]="1"
            self.assertEqual(self.result(write,events),"FAIL")

    def test_fault_cannot_mutate_output_or_issue_denied_read(self):
        for write in (0,1):
            events=self.events(write)+[{"kind":"MEM_REQ", "write":str(write), "epoch":"0", "eid":"3", "cycle":"15"}]
            self.assertEqual(self.result(write,events),"FAIL")

    def test_wrong_completion_identity_fails(self):
        for write in (0,1):
            events=self.events(write);events[1]["tag"]="54"
            self.assertEqual(self.result(write,events),"FAIL")


if __name__=="__main__":
    unittest.main()
