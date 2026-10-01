import unittest
from check_crossover_scenario_intents import qualify


class CachedPermissionIntentTests(unittest.TestCase):
    def events(self):
        rows=[]
        for i,status in enumerate((0,0,0,3,3,0)):
            rows.append(dict(kind="COMPLETE",cycle=str(10*(i+1)),tag=str(53+i),status=str(status),vectors_done="0" if status else "1",asid="1"))
        for tag,write,hit,fault in ((54,1,1,0),(55,0,0,0),(56,1,1,2),(57,1,1,2),(58,1,0,0)):
            rows.append(dict(kind="XLATE_RSP",cycle=str(10*(tag-52)-2),tag=str(tag),write=str(write),iova="80004000",tlb_hit=str(hit),fault=str(fault)))
        for cycle,tag in ((22,55),(52,58)):
            rows.append(dict(kind="TLB_INVALIDATE",cycle=str(cycle),asid="1"))
            rows.append(dict(kind="SUBMIT",cycle=str(cycle+4),tag=str(tag),asid="1"))
        for cycle,value in ((15,"040010c3"),(45,"040010cf")):
            rows.append(dict(kind="PTE_WRITE",cycle=str(cycle),addr="30001010",data="00000000"+value))
        return [dict(e,epoch="0",eid=str(i+1)) for i,e in enumerate(sorted(rows,key=lambda e:int(e["cycle"])))]

    def result(self,events):
        return qualify("translation_recovery__fault_3",{},events)["scenario_intent_status"]

    def test_complete_permission_transition_passes(self):
        self.assertEqual(self.result(self.events()),"PASS")

    def test_upgrade_must_not_bypass_cached_denial(self):
        events=self.events()
        next(e for e in events if e["kind"]=="XLATE_RSP" and e["tag"]=="57")["fault"]="0"
        self.assertEqual(self.result(events),"FAIL")

    def test_invalidation_and_pte_updates_required(self):
        for kind in ("TLB_INVALIDATE","PTE_WRITE"):
            self.assertEqual(self.result([e for e in self.events() if e["kind"]!=kind]),"FAIL")

    def test_post_invalidation_translation_must_miss(self):
        events=self.events()
        next(e for e in events if e["kind"]=="XLATE_RSP" and e["tag"]=="58")["tlb_hit"]="1"
        self.assertEqual(self.result(events),"FAIL")


if __name__=="__main__":
    unittest.main()
