#!/usr/bin/env python3
"""Actual RTL metadata mutation, qualified by an independent read checker."""
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from check_crossover_trace import events
from end_to_end_checks import completion_reads

ROOT=Path(__file__).resolve().parents[3]
SCENARIO="stateful_cross_stage_retry"
MACRO="PROTECTED_MUT_TORN_COMPLETION_METADATA"


def main():
    out=ROOT/"reports/compute_end_to_end_mutations.csv"
    out.unlink(missing_ok=True)
    command=[sys.executable,str(Path(__file__).with_name("run_stateful_crossover.py")),"--family",SCENARIO]
    nominal=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    closure=ROOT/f"reports/compute_stateful_{SCENARIO}_closure.csv"
    rows=list(csv.DictReader(closure.open())) if closure.is_file() else []
    control=nominal.returncode==0 and len(rows)==1 and rows[0]["status"]=="PASS"
    env=dict(os.environ,PROTECTED_STATEFUL=SCENARIO)
    report=ROOT/f"reports/compute_stateful_mutation_{MACRO.lower()}.csv"
    report.unlink(missing_ok=True)
    mutant=subprocess.run([sys.executable,str(Path(__file__).with_name("run_shared_firmware.py")),
                           "--define",MACRO],cwd=ROOT,env=env,text=True,capture_output=True)
    # Mutation runs have separate artifact directories; never inspect nominal
    # traces or infer detection from the outer runner's exit code.
    runs=list(csv.DictReader(report.open())) if report.is_file() else []
    run=runs[-1] if runs else {}
    trace=ROOT/run.get("trace","MISSING")
    parsed=events(trace) if trace.is_file() else []
    witnesses,errors=completion_reads(parsed)
    exact=any(e.startswith("completion_metadata_read_mismatch:") for e in errors)
    bound=trace.is_file() and hashlib.sha256(trace.read_bytes()).hexdigest()==run.get("trace_sha256")
    compiled=bool(parsed) and "CalledProcessError" not in mutant.stdout+mutant.stderr
    detected=control and compiled and bound and exact and bool(witnesses)
    row=dict(mutation=MACRO,status="DETECTED" if detected else "MISSED",nominal_control="PASS" if control else "FAIL",
             compile_status="PASS" if compiled else "FAIL",activated=str(bool(witnesses)).lower(),
             expected_failure="completion_metadata_read_mismatch",diagnostics=json.dumps(errors),
             trace=run.get("trace",""),trace_sha256=run.get("trace_sha256",""))
    with out.open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=row,lineterminator="\n");writer.writeheader();writer.writerow(row)
    print("End-to-end RTL mutation: "+row["status"])
    return 0 if detected else 1


if __name__=="__main__":raise SystemExit(main())
