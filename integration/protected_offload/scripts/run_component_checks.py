#!/usr/bin/env python3
from __future__ import annotations
import csv, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
BUILD=ROOT/"build/protected_offload"
REPORT=ROOT/"reports/protected_offload_component_smoke.csv"
CASES=[
 ("axi_lane_adapter","tb_protected_dma_axi_adapter",["integration/protected_offload/rtl/protected_dma_axi_adapter.sv","integration/protected_offload/sim/tb_protected_dma_axi_adapter.sv"]),
 ("iommu_translation","tb_protected_iommu",["integration/protected_offload/vendor/axi/dma_iommu.sv","integration/protected_offload/sim/tb_protected_iommu.sv"]),
 ("descriptor_queue","tb_protected_queue",["integration/protected_offload/rtl/protected_queue_count_next.sv","integration/protected_offload/rtl/protected_offload_dma.sv","integration/protected_offload/sim/tb_protected_queue.sv"]),
 ("descriptor_guard","tb_protected_descriptor_guard",["integration/protected_offload/rtl/protected_queue_count_next.sv","integration/protected_offload/rtl/protected_offload_dma.sv","integration/protected_offload/sim/tb_protected_descriptor_guard.sv"]),
]
def main()->int:
  rows=[]
  for name,top,sources in CASES:
    obj=BUILD/f"component_{name}";cmd=["verilator","--binary","--sv","--timing","--assert","-Wall","-Wno-UNUSEDSIGNAL","-Wno-SYNCASYNCNET","-Wno-BLKSEQ","--top-module",top,"--Mdir",str(obj),*sources]
    build=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
    if build.returncode:rows.append({"component":name,"status":"FAIL","checks":"0","detail":"compile failure"});continue
    run=subprocess.run([str(obj/f"V{top}")],cwd=ROOT,text=True,capture_output=True)
    output=run.stdout+run.stderr
    marker=next((l for l in output.splitlines() if l.startswith("PROTECTED_")),"")
    count="6" if name.startswith("axi") else "5" if name.startswith("iommu") else "10" if name.endswith("guard") else "4"
    rows.append({"component":name,"status":"PASS" if run.returncode==0 else "FAIL","checks":count,"detail":marker})
  REPORT.parent.mkdir(exist_ok=True)
  with REPORT.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(rows)
  passed=sum(r["status"]=="PASS" for r in rows);print(f"PROTECTED_OFFLOAD_COMPONENTS|status={'PASS' if passed==len(rows) else 'FAIL'}|passed={passed}/{len(rows)}")
  return 0 if passed==len(rows) else 1
if __name__=="__main__":raise SystemExit(main())
