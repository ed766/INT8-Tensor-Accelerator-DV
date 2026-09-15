#!/usr/bin/env python3
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3]
BUILD=ROOT/"build/protected_offload/irq_aggregator";BUILD.mkdir(parents=True,exist_ok=True)
subprocess.run(["verilator","--binary","--sv","--timing","--assert","-Wall","-Wno-BLKSEQ","-Wno-SYNCASYNCNET","-Wno-UNUSEDSIGNAL","--top-module","tb_protected_irq_aggregator","--Mdir",str(BUILD/"obj"),str(ROOT/"integration/protected_offload/rtl/protected_irq_aggregator.sv"),str(ROOT/"integration/protected_offload/sim/tb_protected_irq_aggregator.sv")],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
run=subprocess.run([str(BUILD/"obj/Vtb_protected_irq_aggregator")],cwd=ROOT,text=True,capture_output=True,check=True)
if "PROTECTED_IRQ_AGGREGATOR|status=PASS" not in run.stdout:raise SystemExit("IRQ aggregator did not report PASS")
print("Protected interrupt aggregator: PASS")
