import unittest
from check_crossover_scenario_intents import qualify


class CompletionPressureIntentTests(unittest.TestCase):
    def events(self):
        rows=[]
        def add(kind, cycle, **fields):
            rows.append(dict(kind=kind, cycle=str(cycle), eid=str(len(rows)+1), epoch="0", **fields))
        for i in range(5):
            add("SUBMIT", 1+i, tag=str(53+i), asid="1")
        for i in range(4):
            add("COMPLETE_PUBLISH", 10+i, tag=str(53+i), asid="1")
        add("MEM_RSP", 15, tag="57", write="1", committed="1", error="0")
        for i in range(8):
            add("RETIRE", 20+2*i, mem_addr="4000001c", mem_rmask="f", mem_rdata="00000202")
            add("RETIRE", 21+2*i, mem_addr="40000020", mem_rmask="f", mem_rdata="00001010")
        add("COMPLETE", 40, tag="53", asid="1")
        add("COMPLETE_PUBLISH", 41, tag="57", asid="1")
        for i in range(1,5):
            add("COMPLETE", 42+i, tag=str(53+i), asid="1")
        return sorted(rows,key=lambda e:int(e["cycle"]))

    def result(self, events):
        return qualify("queues_configuration__case_2", {}, events)["scenario_intent_status"]

    def test_full_fifo_stall_then_ordered_drain_pass(self):
        self.assertEqual(self.result(self.events()), "PASS")

    def test_uncommitted_fifth_output_fails(self):
        events=self.events()
        next(e for e in events if e["kind"]=="MEM_RSP")["committed"]="0"
        self.assertEqual(self.result(events), "FAIL")

    def test_corrupted_front_fails(self):
        events=self.events()
        next(e for e in events if e.get("mem_addr")=="40000020")["mem_rdata"]="0000dead"
        self.assertEqual(self.result(events), "FAIL")

    def test_early_fifth_publication_fails(self):
        events=self.events()
        next(e for e in events if e["kind"]=="COMPLETE_PUBLISH" and e["tag"]=="57")["cycle"]="39"
        self.assertEqual(self.result(events), "FAIL")

    def test_reordered_drain_fails(self):
        events=self.events()
        next(e for e in events if e["kind"]=="COMPLETE" and e["tag"]=="54")["tag"]="55"
        self.assertEqual(self.result(events), "FAIL")


if __name__=="__main__":
    unittest.main()
