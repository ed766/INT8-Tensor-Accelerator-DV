"""Predicate sensitivity independent of firmware mailbox success."""
import unittest
from pathlib import Path
from unittest.mock import patch
from run_live_m_interactions import qualify


class LiveWitnessTests(unittest.TestCase):
    def run_events(self, rows, mode):
        with patch("run_live_m_interactions.events", return_value=rows), patch(
                "run_live_m_interactions.check_host_trace", return_value={"status": "PASS"}):
            return qualify(Path("unused"), mode)

    def test_dual_requires_both_engines_live(self):
        rows = [dict(kind="DMA_ACTIVE_START"),
                dict(kind="RETIRE", insn="02000033", trap="0", eid="1")]
        self.assertTrue(self.run_events(rows, "dual_0")[1])
        rows.insert(1, dict(kind="CHIPLET_EVT", busy="1"))
        self.assertFalse(self.run_events(rows, "dual_0")[1])
        self.assertTrue(self.run_events(rows, "dual_4")[1])

    def test_sleep_requires_actual_restore(self):
        rows = [dict(kind="DMA_ACTIVE_START"),
                dict(kind="CHIPLET_POWER", state="2", cycle="2", eid="2"),
                dict(kind="RETIRE", insn="02000033", trap="0", eid="3")]
        self.assertTrue(self.run_events(rows, "sleep")[1])
        rows.append(dict(kind="CHIPLET_POWER", state="0", cycle="4", eid="4"))
        rows.append(dict(kind="CHIPLET_EVT", done="1", busy="0", cycle="5", eid="5"))
        self.assertFalse(self.run_events(rows, "sleep")[1])

    def test_irq_requires_retirement_before_entry_and_precise_mepc(self):
        rows = [dict(kind="DMA_ACTIVE_START"),
                dict(kind="IRQ_SET", muldiv_busy="1", ext="1", cycle="2", eid="2"),
                dict(kind="RETIRE", insn="02004033", trap="0", cycle="3", eid="3", next_pc="00000004"),
                dict(kind="RETIRE", insn="00000013", intr="1", cycle="4", eid="4", mepc="00000004")]
        self.assertFalse(self.run_events(rows, "irq")[1])
        rows[-1]["mepc"] = "00000000"
        self.assertTrue(self.run_events(rows, "irq")[1])


if __name__ == "__main__":
    unittest.main()
