import unittest
from pathlib import Path
from unittest.mock import patch
from m_permutation_model import cases, expected, operand_class
from run_m_permutations import timing_phase, qualify


class PermutationTests(unittest.TestCase):
    def test_checker_rejects_wrong_result_and_ended_service(self):
        entry = cases("operands")[0]
        start = dict(kind="MDIV_BUSY", busy="1", pc="00000100", cycle="10", epoch="0", eid="1", dma_busy="1")
        retire = dict(kind="RETIRE", pc="00000100", cycle="45", epoch="0", eid="3", insn="02000633",
                      rs1_data=f"{entry['lhs']:08x}", rs2_data=f"{entry['rhs']:08x}", rd_data=f"{entry['expected']:08x}",
                      trap="0", mem_rmask="0", mem_wmask="0", intr="0")
        with patch("run_m_permutations.symbols", return_value=(256,260)):
            with patch("run_m_permutations.events", return_value=[start,retire]):
                self.assertEqual(qualify(entry,Path("unused.trace"))[2], [])
            with patch("run_m_permutations.events", return_value=[start,dict(retire,rd_data="00000001")]):
                self.assertIn("probe_operand_opcode_result_or_side_effect",qualify(entry,Path("unused.trace"))[2])
            with patch("run_m_permutations.events", return_value=[start,dict(kind="DMA_ACTIVE_END",cycle="20"),retire]):
                self.assertIn("service_or_epoch_ended_before_M_retirement",qualify(entry,Path("unused.trace"))[2])

    def test_matrix_sizes_and_unique_names(self):
        for family, size in (("operands", 392), ("timing", 528)):
            rows = cases(family)
            self.assertEqual(len(rows), size)
            self.assertEqual(len({r["name"] for r in rows}), size)

    def test_exception_oracle(self):
        for op in (4,5): self.assertEqual(expected(op,7,0),0xffffffff)
        for op in (6,7): self.assertEqual(expected(op,7,0),7)
        self.assertEqual(expected(4,0x80000000,0xffffffff),0x80000000)
        self.assertEqual(expected(6,0x80000000,0xffffffff),0)
        self.assertEqual(expected(4,0xfffffff9,3),0xfffffffe)
        self.assertEqual(expected(6,0xfffffff9,3),0xffffffff)
        self.assertEqual(expected(2,0xffffffff,0xffffffff),0xffffffff)
        self.assertEqual(expected(3,0xffffffff,0xffffffff),0xfffffffe)

    def test_irq_checker_rejects_wrong_mepc(self):
        entry = dict(cases("timing")[0], repeats=1)
        start = dict(kind="MDIV_BUSY", busy="1", pc="00000100", cycle="10", epoch="0", eid="1")
        irq = dict(kind="IRQ_SET", ext="1", raw="2", muldiv_busy="1", pc="00000100", state="1", iteration="8", cycle="20", eid="2")
        retire = dict(kind="RETIRE", pc="00000100", next_pc="00000104", cycle="45", epoch="0", eid="3", insn="02000633",
                      rs1_data=f"{entry['lhs']:08x}", rs2_data=f"{entry['rhs']:08x}", rd_data=f"{entry['expected']:08x}",
                      trap="0", mem_rmask="0", mem_wmask="0", intr="0")
        handler = dict(kind="RETIRE", pc="00000104", intr="1", mcause="8000000b", mepc="00000100", cycle="46", eid="4")
        with patch("run_m_permutations.symbols", return_value=(256,260)), patch("run_m_permutations.events", return_value=[start,irq,retire,handler]):
            self.assertIn("M_before_IRQ_or_precise_mepc",qualify(entry,Path("unused.trace"))[2])
            handler["mepc"]="00000104"
            self.assertEqual(qualify(entry,Path("unused.trace"))[2], [])

    def test_ordered_operand_classes(self):
        self.assertEqual(operand_class(0,1),"zero")
        self.assertEqual(operand_class(1,0xffffffff),"one")
        self.assertEqual(operand_class(0x80000000,0xffffffff),"all_ones")

    def test_actual_phase_not_requested_delay(self):
        starts=[{"cycle":"10"}];retires=[{"cycle":"50"}]
        irq=dict(cycle="20",pc="00000100",muldiv_busy="1",state="1",iteration="0")
        for iteration, phase in ((0,"early"),(8,"middle"),(24,"late")):
            irq["iteration"]=str(iteration)
            self.assertEqual(timing_phase(irq,starts,retires,256,320),phase)
        irq["state"]="2"
        self.assertEqual(timing_phase(irq,starts,retires,256,320),"finalize")
        irq["state"]="3"
        self.assertEqual(timing_phase(irq,starts,retires,256,320),"response")
        irq["cycle"]="5"
        self.assertEqual(timing_phase(irq,starts,retires,256,320),"before")
        irq["cycle"]="55"
        self.assertEqual(timing_phase(irq,starts,retires,256,320),"after")


if __name__ == "__main__": unittest.main()
