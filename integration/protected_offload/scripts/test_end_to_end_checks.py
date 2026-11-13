"""Checker sensitivity is separate from actual RTL mutation evidence."""
import copy
import unittest
from check_crossover_trace import events
from end_to_end_checks import completion_reads,physical_ownership,reference_writes
from run_stateful_crossover import ROOT,qualify
from stateful_cases import cases


class EndToEndChecks(unittest.TestCase):
    def test_effective_physical_mapping_not_latest_pte(self):
        submit=dict(kind="SUBMIT",epoch="0",tag="7",eid="s",bank="0",generation="1")
        access=dict(kind="OWNED_CPU_ACCESS",epoch="0",eid="a",addr="10006004")
        translated=dict(kind="XLATE_RSP",epoch="0",tag="7",eid="x",fault="0",paddr="10006000")
        # Delayed translation must still detect an earlier forbidden access.
        self.assertTrue(physical_ownership([submit,access,translated])[1])
        access["addr"]="10007000"
        self.assertFalse(physical_ownership([submit,access,translated])[1])

    def test_physical_ownership_does_not_cross_reset(self):
        submit=dict(kind="SUBMIT",epoch="0",tag="7",eid="s")
        translated=dict(kind="XLATE_RSP",epoch="0",tag="7",eid="x",fault="0",paddr="10006000")
        access=dict(kind="OWNED_CPU_ACCESS",epoch="1",eid="a",addr="10006000")
        self.assertFalse(physical_ownership([submit,translated,dict(kind="RESET_ASSERT"),access])[1])

    def test_configuration_reference_ends_at_publication_not_retire(self):
        submit=dict(kind="SUBMIT",epoch="0",tag="7",eid="s",bank="1",generation="2")
        write=dict(kind="APB",epoch="0",eid="w",addr="40001010",write="1",error="0",wdata="00000300")
        self.assertTrue(reference_writes([submit,write])[1])
        self.assertFalse(reference_writes([submit,dict(kind="COMPLETE_PUBLISH",epoch="0",tag="7"),write])[1])

    @staticmethod
    def record(kind, epoch, eid, **fields):
        return dict(kind=kind, epoch=str(epoch), eid=eid, tag="7", asid="1",
                    status="0", fault_stage="0", vectors_done="1",
                    fault_iova="00000000", **fields)

    def test_reset_discards_unread_record_not_rebooted_tag(self):
        publication = self.record("COMPLETE_PUBLISH", 0, "p0")
        reboot = self.record("COMPLETE_PUBLISH", 1, "p1")
        consumed = self.record("COMPLETE", 1, "c1")
        trace = [publication, dict(kind="RESET_ASSERT", epoch="0", eid="reset"), reboot, consumed]
        self.assertFalse(completion_reads(trace)[1])
        reboot["epoch"] = "0"
        self.assertTrue(completion_reads(trace)[1])

    def test_reset_between_metadata_read_and_retirement(self):
        trace = [self.record("COMPLETE_PUBLISH", 0, "p0"),
                 dict(kind="APB",epoch="0",eid="r0",addr="40000024",write="0",error="0",rdata="00000000"),
                 dict(kind="RESET_ASSERT",epoch="0",eid="reset"),
                 self.record("COMPLETE_PUBLISH",1,"p1"),self.record("COMPLETE",1,"c1")]
        self.assertFalse(completion_reads(trace)[1])
        trace[1]["rdata"]="10000000"
        self.assertTrue(any("completion_metadata_read_mismatch" in e for e in completion_reads(trace)[1]))

    def test_ghost_consumption_after_reset_is_rejected(self):
        trace = [self.record("COMPLETE_PUBLISH",0,"p0"),
                 dict(kind="RESET_ASSERT",epoch="0",eid="reset"),self.record("COMPLETE",1,"ghost")]
        self.assertTrue(completion_reads(trace)[1])

    def test_fault_address_cannot_change_between_publication_and_pop(self):
        publication=self.record("COMPLETE_PUBLISH",0,"p")
        consumed=self.record("COMPLETE",0,"c")
        consumed["fault_iova"]="80006000"
        self.assertTrue(completion_reads([publication,consumed])[1])

    def test_all_scenarios_require_real_witnesses(self):
        removed={81:"MDIV_BUSY",82:"COMPLETE",83:"RETIRE",84:"RETIRE",
                 85:"RESET_IRQ_SNAPSHOT",86:"TLB_INVALIDATE",87:"XLATE_RSP",88:"CHIPLET_POWER"}
        for case in cases():
            if case["family"]!="end_to_end":continue
            parsed=events(ROOT/f"build/protected_offload/shared_firmware/{case['name']}/crossover.trace")
            with self.subTest(scenario=case["name"]):
                self.assertFalse(qualify(parsed,case["code"],case["name"])[1])
                self.assertTrue(qualify([e for e in parsed if e["kind"]!=removed[case["code"]]],case["code"],case["name"])[1])

    def test_each_front_record_word_is_independently_checked(self):
        original=events(ROOT/"build/protected_offload/shared_firmware/stateful_cross_stage_retry/crossover.trace")
        self.assertFalse(completion_reads(original)[1])
        for addr in ("40000020","40000024","40000028"):
            parsed=copy.deepcopy(original)
            event=next(e for e in parsed if e["kind"]=="APB" and e.get("addr")==addr and e.get("write")=="0")
            event["rdata"]=f"{int(event['rdata'],16)^1:08x}"
            with self.subTest(address=addr):
                self.assertTrue(any(e.startswith("completion_metadata_read_mismatch:") for e in completion_reads(parsed)[1]))

    def test_missing_apb_read_data_fails_closed(self):
        parsed=events(ROOT/"build/protected_offload/shared_firmware/stateful_cross_stage_retry/crossover.trace")
        for e in parsed:
            if e["kind"]=="APB":e.pop("rdata",None)
        self.assertTrue(completion_reads(parsed)[1])

    def test_common_mode_corrupt_load_trace_is_not_trusted(self):
        parsed=events(ROOT/"build/protected_offload/shared_firmware/stateful_cross_stage_retry/crossover.trace")
        event=next(e for e in parsed if e["kind"]=="RETIRE" and e.get("mem_addr")=="40000020" and e.get("mem_rmask")=="f")
        value=f"{int(event['mem_rdata'],16)^1:08x}"
        event["mem_rdata"]=value;event["rd_data"]=value
        self.assertTrue(any(e.startswith("completion_read_retirement_mismatch:") for e in completion_reads(parsed)[1]))


if __name__=="__main__":unittest.main()
