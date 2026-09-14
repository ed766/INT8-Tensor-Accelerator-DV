#!/usr/bin/env python3
from __future__ import annotations
import csv, os, shutil, subprocess, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
FORMAL=ROOT/"integration/protected_offload/formal"
REPORT=ROOT/"reports/protected_offload_formal.csv"
PROPERTIES=[
  ("request_response_accounting","response count never exceeds accepted count"),
  ("single_outstanding_bound","at most one DMA memory operation is active"),
  ("write_address_contract","AW is aligned and describes one 32-bit transfer"),
  ("byte_lane_mapping","32-bit writes select exactly one 64-bit data lane"),
  ("write_completion_order","DMA response follows accepted AW and W"),
  ("read_address_contract","AR is aligned and describes one 32-bit transfer"),
  ("read_completion_order","DMA response follows an accepted AR"),
  ("response_backpressure_stability","response payload remains stable while blocked"),
]
QUEUE_PROPERTIES=[
  ("queue_count_bounded","simultaneous and single-sided updates remain within depth"),
  ("simultaneous_push_pop_preserves_count","concurrent enqueue/dequeue has zero net occupancy change"),
]

def find_sby()->str|None:
  direct=shutil.which("sby")
  if direct:return direct
  roots=[Path(os.environ.get("OSS_CAD_SUITE","")),Path.home()/".cache/oss-cad-suite",
    Path.home()/"ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/oss-cad-suite/oss-cad-suite"]
  for root in roots:
    candidate=root/"bin/sby"
    if candidate.exists():return str(candidate)
  return None

def main()->int:
  sby=find_sby();rows=[];start=time.monotonic()
  if not sby:
    for name,detail in PROPERTIES:rows.append({"property":name,"mode":"bounded_solver_safety","depth":16,"status":"SKIP","cover":"SKIP","runtime_s":"0.00","detail":detail+"; sby unavailable"})
  else:
    for task in ("prove","cover"):shutil.rmtree(FORMAL/f"protected_axi_adapter_{task}",ignore_errors=True)
    for task in ("prove","cover"):shutil.rmtree(FORMAL/f"protected_queue_count_{task}",ignore_errors=True)
    env=os.environ.copy();env["PATH"]=f"{Path(sby).parent}:{env.get('PATH','')}"
    run=subprocess.run([sby,"-f","protected_axi_adapter.sby"],cwd=FORMAL,env=env,text=True,capture_output=True)
    queue_run=subprocess.run([sby,"-f","protected_queue_count.sby"],cwd=FORMAL,env=env,text=True,capture_output=True)
    (ROOT/"build/protected_offload").mkdir(parents=True,exist_ok=True)
    (ROOT/"build/protected_offload/formal.log").write_text(run.stdout+run.stderr+queue_run.stdout+queue_run.stderr)
    prove=(FORMAL/"protected_axi_adapter_prove/status").read_text().startswith("PASS") if (FORMAL/"protected_axi_adapter_prove/status").exists() else False
    cover=(FORMAL/"protected_axi_adapter_cover/status").read_text().startswith("PASS") if (FORMAL/"protected_axi_adapter_cover/status").exists() else False
    elapsed=f"{time.monotonic()-start:.2f}"
    for name,detail in PROPERTIES:rows.append({"property":name,"mode":"bounded_solver_safety","depth":16,"status":"PASS" if prove else "FAIL","cover":"REACHABLE" if cover else "FAIL","runtime_s":elapsed,"detail":detail})
    queue_path=FORMAL/"protected_queue_count_prove/status";queue_cover_path=FORMAL/"protected_queue_count_cover/status"
    queue=queue_path.read_text().startswith("PASS") if queue_path.exists() else False
    queue_cover=queue_cover_path.read_text().startswith("PASS") if queue_cover_path.exists() else False
    for name,detail in QUEUE_PROPERTIES:rows.append({"property":name,"mode":"solver_combinational","depth":1,"status":"PASS" if queue else "FAIL","cover":"REACHABLE" if queue_cover else "FAIL","runtime_s":elapsed,"detail":detail})
  REPORT.parent.mkdir(exist_ok=True)
  with REPORT.open("w",newline="") as h:
    w=csv.DictWriter(h,fieldnames=rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(rows)
  passed=sum(r["status"]=="PASS" for r in rows);skipped=sum(r["status"]=="SKIP" for r in rows)
  print(f"PROTECTED_OFFLOAD_FORMAL|status={'PASS' if passed==len(rows) else 'SKIP' if skipped==len(rows) else 'FAIL'}|properties={passed}/{len(rows)}|covers={sum(r['cover']=='REACHABLE' for r in rows)}/{len(rows)}")
  return 0 if passed==len(rows) or skipped==len(rows) else 1
if __name__=="__main__":raise SystemExit(main())
