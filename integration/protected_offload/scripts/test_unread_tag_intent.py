import unittest
from check_crossover_scenario_intents import qualify


class UnreadTagIntentTests(unittest.TestCase):
    def event(self, kind, cycle, tag="53", epoch="0"):
        return {"kind": kind, "cycle": str(cycle), "eid": str(cycle),
                "epoch": epoch, "tag": tag, "asid": "1", "status": "0"}

    def result(self, events):
        return qualify("queues_configuration__case_4", {}, events)["scenario_intent_status"]

    def test_reject_after_publish_before_pop_passes(self):
        self.assertEqual(self.result([self.event("COMPLETE_PUBLISH", 10),
                                     self.event("SUBMIT_REJECT", 20),
                                     self.event("COMPLETE", 30)]), "PASS")

    def test_active_duplicate_does_not_cover_unread_duplicate(self):
        self.assertEqual(self.result([self.event("SUBMIT_REJECT", 5),
                                     self.event("COMPLETE_PUBLISH", 10),
                                     self.event("COMPLETE", 30)]), "FAIL")

    def test_consumed_completion_no_longer_qualifies(self):
        self.assertEqual(self.result([self.event("COMPLETE_PUBLISH", 10),
                                     self.event("COMPLETE", 15),
                                     self.event("SUBMIT_REJECT", 20),
                                     self.event("COMPLETE", 30)]), "FAIL")

    def test_wrong_identity_or_epoch_fails(self):
        for tag, epoch in (("54", "0"), ("53", "1")):
            events = [self.event("COMPLETE_PUBLISH", 10),
                      self.event("SUBMIT_REJECT", 20, tag, epoch),
                      self.event("COMPLETE", 30)]
            self.assertEqual(self.result(events), "FAIL")

    def test_reaccepted_live_tag_fails(self):
        self.assertEqual(self.result([self.event("COMPLETE_PUBLISH", 10),
                                     self.event("SUBMIT_REJECT", 20),
                                     self.event("SUBMIT", 25),
                                     self.event("COMPLETE", 30)]), "FAIL")


if __name__ == "__main__":
    unittest.main()
