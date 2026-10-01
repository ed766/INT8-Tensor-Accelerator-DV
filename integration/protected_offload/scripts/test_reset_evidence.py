#!/usr/bin/env python3
import unittest
from reset_evidence import phase_reached


class ResetEvidenceTest(unittest.TestCase):
    def test_prolonged_backpressure_requires_measured_wait_and_owner(self):
        events=[{"kind":"APB_WAIT","cycle":"130","epoch":"0","wait_cycles":"128"},
                {"kind":"RESET_ASSERT","cycle":"131","epoch":"1",
                 "host_aw_pending":"1","apb_active":"1"}]
        self.assertTrue(phase_reached(events,"prolonged_backpressure"))
        events[0]["wait_cycles"]="1"
        self.assertFalse(phase_reached(events,"prolonged_backpressure"))
        events[0]["wait_cycles"]="128"
        events[-1]["host_aw_pending"]="0"
        self.assertFalse(phase_reached(events,"prolonged_backpressure"))

    def test_maintenance_reset_requires_started_busy_cache_operation(self):
        events=[{"kind":"MAINT_START","cycle":"10","cache_enabled":"1"},
                {"kind":"RESET_ASSERT","cycle":"12","maint_active":"1"}]
        self.assertTrue(phase_reached(events,"maintenance_invalidation"))
        events[0]["cache_enabled"]="0"
        self.assertFalse(phase_reached(events,"maintenance_invalidation"))
        events[0]["cache_enabled"]="1"
        events.insert(1,{"kind":"MAINT_DONE","cycle":"11"})
        self.assertFalse(phase_reached(events,"maintenance_invalidation"))

    def test_completion_irq_requires_both_pending_states(self):
        events=[{"kind":"RESET_IRQ_SNAPSHOT","cycle":"12","epoch":"1","pending":"2"},
                {"kind":"RESET_ASSERT","cycle":"12","epoch":"1",
                 "completion_pending":"1","completion_occupancy":"1"}]
        self.assertTrue(phase_reached(events,"completion_irq"))
        events[0]["pending"]="0"
        self.assertFalse(phase_reached(events,"completion_irq"))
        events[0]["pending"]="2"
        events[1]["completion_occupancy"]="0"
        self.assertFalse(phase_reached(events,"completion_irq"))

    def test_completion_irq_snapshot_cannot_cross_epochs(self):
        events=[{"kind":"RESET_IRQ_SNAPSHOT","cycle":"12","epoch":"0","pending":"2"},
                {"kind":"RESET_ASSERT","cycle":"12","epoch":"1",
                 "completion_pending":"1","completion_occupancy":"1"}]
        self.assertFalse(phase_reached(events,"completion_irq"))

    def test_output_write_reset_requires_dma_aw_not_cpu_aw(self):
        events=[{"kind":"DMA_AXI_AW","master":"1","cycle":"10"},
                {"kind":"RESET_ASSERT","cycle":"11","mem_pending":"1"}]
        self.assertTrue(phase_reached(events,"accepted_output_write"))
        events[0]["kind"]="AXI_AW"
        self.assertFalse(phase_reached(events,"accepted_output_write"))

    def test_output_write_reset_rejects_already_completed_write(self):
        events=[{"kind":"DMA_AXI_AW","master":"1","cycle":"10"},
                {"kind":"DMA_AXI_B","master":"1","cycle":"11"},
                {"kind":"RESET_ASSERT","cycle":"12","mem_pending":"1"}]
        self.assertFalse(phase_reached(events,"accepted_output_write"))

    def test_pending_response_before_acceptance(self):
        self.assertTrue(phase_reached([{"kind": "RESET_ASSERT", "cycle": "12",
            "mem_response_valid": "1", "mem_pending": "1"}], "mem_rsp"))

    def test_completed_response_is_not_outstanding(self):
        self.assertFalse(phase_reached([{"kind": "MEM_RSP", "cycle": "11"},
            {"kind": "RESET_ASSERT", "cycle": "12", "mem_pending": "0"}], "mem_rsp"))

    def test_unread_completion(self):
        self.assertTrue(phase_reached([{"kind": "RESET_ASSERT", "cycle": "12",
            "completion_pending": "1", "completion_occupancy": "1"}], "completion"))

    def test_consumed_completion_is_not_pending(self):
        self.assertFalse(phase_reached([{"kind": "COMPLETE", "cycle": "11"},
            {"kind": "RESET_ASSERT", "cycle": "12", "completion_pending": "0",
             "completion_occupancy": "0"}], "completion"))

    def test_all_request_phases_require_owned_work(self):
        for phase, kind, field in (("ptw_req", "XLATE_REQ", "xlate_pending"),
                                   ("mem_req", "MEM_REQ", "mem_pending"),
                                   ("apb_wait", "APB_WAIT", "apb_active"),
                                   ("mdiv_busy", "MDIV_BUSY", "muldiv_busy")):
            with self.subTest(phase=phase):
                events = [{"kind": kind, "cycle": "10"},
                          {"kind": "RESET_ASSERT", "cycle": "11", field: "1"}]
                self.assertTrue(phase_reached(events, phase))
                events[-1][field] = "0"
                self.assertFalse(phase_reached(events, phase))

    def test_old_trigger_is_not_accepted(self):
        self.assertFalse(phase_reached([{"kind": "MEM_REQ", "cycle": "1"},
            {"kind": "RESET_ASSERT", "cycle": "12", "mem_pending": "1"}], "mem_req"))

    def test_combined_reset_requires_both_services_active(self):
        events = [{"kind": "DMA_ACTIVE_START", "cycle": "10", "epoch": "0"},
                  {"kind": "CHIPLET_EVT", "cycle": "11", "epoch": "0", "busy": "1"},
                  {"kind": "RESET_ASSERT", "cycle": "12", "epoch": "1",
                   "chip_busy": "1", "dma_busy": "1"}]
        self.assertTrue(phase_reached(events, "combined_busy"))
        events[-1]["chip_busy"] = "0"
        self.assertFalse(phase_reached(events, "combined_busy"))


if __name__ == "__main__":
    unittest.main()
