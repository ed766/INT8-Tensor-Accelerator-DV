import unittest
from check_crossover_scenario_intents import qualify


class AsidIsolationIntentTests(unittest.TestCase):
    def events(self):
        rows=[]
        for i,(asid,pa,hit) in enumerate((("1","10001000","0"),("2","10002000","0"),("1","10001000","1"))):
            tag=str(53+i)
            rows.append(dict(kind="XLATE_RSP",cycle=str(10*i+5),tag=tag,asid=asid,iova="80001000",write="0",paddr=pa,tlb_hit=hit,fault="0"))
            rows.append(dict(kind="COMPLETE",cycle=str(10*i+9),tag=tag,asid=asid,status="0",vectors_done="1"))
        rows.append(dict(kind="PTE_WRITE",cycle="12",addr="30001004",data="040008cf00000000"))
        return [dict(e,epoch="0",eid=str(i+1)) for i,e in enumerate(sorted(rows,key=lambda e:int(e["cycle"])))]

    def result(self,events):
        return qualify("translation_recovery__fault_4",{},events)["scenario_intent_status"]

    def test_distinct_context_mappings_pass(self):
        self.assertEqual(self.result(self.events()),"PASS")

    def test_context_aliasing_fails(self):
        events=self.events()
        next(e for e in events if e["kind"]=="XLATE_RSP" and e["tag"]=="54")["paddr"]="10001000"
        self.assertEqual(self.result(events),"FAIL")

    def test_original_context_must_retain_cached_mapping(self):
        events=self.events()
        next(e for e in events if e["kind"]=="XLATE_RSP" and e["tag"]=="55")["tlb_hit"]="0"
        self.assertEqual(self.result(events),"FAIL")

    def test_invalidation_cannot_substitute_for_asid_isolation(self):
        events=self.events()+[dict(kind="TLB_INVALIDATE",epoch="0",cycle="13",eid="99")]
        self.assertEqual(self.result(events),"FAIL")


if __name__=="__main__":
    unittest.main()
