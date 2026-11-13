"""Checker sensitivity tests, explicitly not RTL mutation evidence."""
import copy
import unittest
from check_crossover_trace import events, check
from run_stateful_crossover import ROOT, qualify
from stateful_cross_coverage import contributions
from run_stateful_mutations import arithmetic_witness
from stateful_cases import random_cases


class StatefulQualification(unittest.TestCase):
    def test_missing_activating_events_fail(self):
        for code, suffix, removed in (
            (1, "irq_fault_timer", "IRQ_SOURCE_EDGE"), (3, "irq_wfi_timer", "RETIRE"),
            (10, "reset_m_dma_finalize", "RESET_ASSERT"), (20, "tag_wrap", "SUBMIT"),
            (31, "permission_hit", "TLB_INVALIDATE"), (32, "repeated_retry", "COMPLETE"),
            (41, "cache_maint_retry", "MAINT_DONE"), (50, "pressure_75", "MDIV_BUSY"),
            (60, "round_ties", "ACCEL_CFG"),
        ):
            name = "stateful_" + suffix
            parsed = events(ROOT / f"build/protected_offload/shared_firmware/{name}/crossover.trace")
            with self.subTest(name=name):
                self.assertFalse(qualify(parsed, code, name)[1])
                self.assertTrue(qualify([e for e in parsed if e["kind"] != removed], code, name)[1])

    def test_second_retry_prefix_is_exact(self):
        name = "stateful_repeated_retry"
        parsed = copy.deepcopy(events(ROOT / f"build/protected_offload/shared_firmware/{name}/crossover.trace"))
        second = [e for e in parsed if e["kind"] == "COMPLETE" and e["tag"] == "254"][1]
        second["vectors_done"] = "0"
        self.assertTrue(qualify(parsed, 32, name)[1])

    def test_tlb_replacement_regression(self):
        result = check(ROOT / "build/protected_offload/shared_firmware/stateful_tlb_eviction/crossover.trace", strict_schema=True)
        self.assertEqual(result["status"], "PASS", result["errors"])

    def test_new_edge_scenarios_require_activating_events(self):
        for code,suffix,removed in ((70,"csr_edges","APB"),(71,"input_permission","COMPLETE"),
                (72,"input_bus_error","COMPLETE"),(73,"invalid_generation","SUBMIT_REJECT"),
                (74,"queue_full_recover","SUBMIT_REJECT"),(75,"pop_wait","APB"),
                (76,"last_output_retry","COMPLETE"),(78,"m_corners_live","RETIRE"),
                (77,"mailbox_reserved","APB")):
            name="stateful_"+suffix
            parsed=events(ROOT/f"build/protected_offload/shared_firmware/{name}/crossover.trace")
            with self.subTest(name=name):
                self.assertFalse(qualify(parsed,code,name)[1])
                self.assertTrue(qualify([e for e in parsed if e["kind"]!=removed],code,name)[1])

    def test_recovery_cross_requires_repair_and_matching_descriptor(self):
        parsed=events(ROOT/"build/protected_offload/shared_firmware/stateful_repeated_retry/crossover.trace")
        recovered={v for f,v,w in contributions(parsed) if f=="recovery"}
        self.assertEqual(recovered,{(5,0),(5,1)})
        self.assertFalse(any(f=="recovery" for f,v,w in contributions([e for e in parsed if e["kind"]!="TLB_INVALIDATE"])))
        changed=copy.deepcopy(parsed)
        for e in changed:
            if e["kind"]=="SUBMIT" and e["tag"]=="254":e["input_iova"]=f"{int(e['input_iova'],16)+int(e['seq'])*4096:08x}"
        self.assertFalse(any(f=="recovery" for f,v,w in contributions(changed)))

    def test_random_matrix_is_not_cache_stall_correlated(self):
        rows=random_cases()
        self.assertEqual(len({(r['spec'][6],r['stall']) for r in rows}),8)
        self.assertEqual(len({(r['spec'][1],r['spec'][6]) for r in rows}),10)

    def test_generic_failure_is_not_arithmetic_mutation_detection(self):
        e=dict(kind="RETIRE",insn="02004033",rs1_data="fffffff9",rs2_data="00000003",retire_order="9",eid="31")
        self.assertFalse(arithmetic_witness([e],["timeout"],"iss_signed_quotient"))
        self.assertFalse(arithmetic_witness([e],["order 8: rd value incorrect"],"iss_signed_quotient"))
        self.assertEqual(arithmetic_witness([e],["order 9: rd value incorrect"],"iss_signed_quotient"),"31")
        e['rs1_data']="00000007"
        self.assertFalse(arithmetic_witness([e],["order 9: rd value incorrect"],"iss_signed_quotient"))

    def test_reserved_mailbox_requires_both_offsets(self):
        name="stateful_mailbox_reserved"
        parsed=events(ROOT/f"build/protected_offload/shared_firmware/{name}/crossover.trace")
        self.assertFalse(qualify(parsed,77,name)[1])
        self.assertTrue(qualify([e for e in parsed if not (e['kind']=='APB' and e.get('addr')=='40001ff8')],77,name)[1])


if __name__ == "__main__": unittest.main()
