#!/usr/bin/env python3
"""Qualify lifetime, retry-context and dirty-eviction RTL defects separately."""
import csv
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from check_crossover_trace import events
from end_to_end_checks import reference_writes

ROOT=Path(__file__).resolve().parents[3]
CASES=(
    ("stateful_retire_reference_pressure","PROTECTED_MUT_RETIRE_REFERENCE_RELEASE","referenced_generation_changed_before_publication"),
    ("stateful_read_permission_downgrade","PROTECTED_MUT_STALE_TRANSLATION","retry_context_permission_stale"),
    ("stateful_cache_alias_dirty_eviction","CACHE_BUG_DIRTY_SKIP","dirty_eviction_data_lost"),
)


def diagnose(parsed,macro):
    if macro=="PROTECTED_MUT_RETIRE_REFERENCE_RELEASE":
        witnesses,errors=reference_writes(parsed)
        return [e for window in witnesses for e in window],errors
    if macro=="PROTECTED_MUT_STALE_TRANSLATION":
        denial=None;invalidated=False;witness=[]
        for e in parsed:
            if e["kind"]=="APB" and e.get("addr")=="30001018" and e.get("wdata")=="04001849":denial=e;invalidated=False
            if denial and e["kind"]=="TLB_INVALIDATE":invalidated=True;witness=[denial,e]
            if invalidated and e["kind"]=="XLATE_RSP" and e.get("tag")=="235" and e.get("write")=="0" and e.get("fault")=="0" and e.get("tlb_hit")=="1":
                return witness+[e],["retry_context_permission_stale"]
        return [],[]
    stores={};eviction=False
    for e in parsed:
        if e["kind"]=="RETIRE" and e.get("mem_wmask")=="f" and e.get("mem_addr") in ("100007e0","100017e0"):stores[e["mem_addr"]]=e
        if e["kind"]=="AXI_AR" and e.get("master")=="0" and e.get("addr")=="100027e0":eviction=True
        if eviction and e["kind"]=="APB" and e.get("write")=="0" and e.get("addr") in stores and e.get("rdata")!=stores[e["addr"]]["mem_wdata"]:
            return [stores[e["addr"]],e],["dirty_eviction_data_lost"]
    return [],[]


def main():
    rows=[];scripts=Path(__file__).parent
    for scenario,macro,bucket in CASES:
        control=subprocess.run([sys.executable,str(scripts/"run_stateful_crossover.py"),"--family",scenario],cwd=ROOT,capture_output=True,text=True)
        report=ROOT/f"reports/compute_stateful_mutation_{macro.lower()}.csv";report.unlink(missing_ok=True)
        mutant=subprocess.run([sys.executable,str(scripts/"run_shared_firmware.py"),"--define",macro],cwd=ROOT,
                              env=dict(os.environ,PROTECTED_STATEFUL=scenario),capture_output=True,text=True)
        runs=list(csv.DictReader(report.open())) if report.is_file() else []
        run=runs[0] if len(runs)==1 else {};path=ROOT/run.get("trace","MISSING")
        parsed=events(path) if path.is_file() else [];witnesses,errors=diagnose(parsed,macro)
        bound=path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==run.get("trace_sha256")
        compiled=bool(parsed) and "CalledProcessError" not in mutant.stdout+mutant.stderr
        passed=control.returncode==0 and compiled and bound and bucket in " ".join(errors) and bool(witnesses)
        rows.append(dict(mutation=macro,status="DETECTED" if passed else "MISSED",nominal_control="PASS" if control.returncode==0 else "FAIL",
                         compile_status="PASS" if compiled else "FAIL",expected_failure=bucket,diagnostic=";".join(errors),
                         activating_event_ids=";".join(e["eid"] for e in witnesses),trace=run.get("trace",""),trace_sha256=run.get("trace_sha256","")))
        if not passed:print(control.stdout[-1600:]+control.stderr[-1600:]+mutant.stdout[-1600:]+mutant.stderr[-1600:])
    with (ROOT/"reports/compute_gap_mutations.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    print(f"Gap RTL mutations: {sum(r['status']=='DETECTED' for r in rows)}/{len(rows)}")
    return int(any(r["status"]!="DETECTED" for r in rows))


if __name__=="__main__":raise SystemExit(main())
