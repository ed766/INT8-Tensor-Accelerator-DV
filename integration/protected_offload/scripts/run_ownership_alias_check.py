#!/usr/bin/env python3
"""Qualify a legal alias control and a precisely activated negative check."""
import csv
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from check_crossover_trace import events

ROOT=Path(__file__).resolve().parents[3]


def run_case(positive,negative_name,address,tag,pte_address=None,pte_value=None):
    scripts=Path(__file__).parent
    control=subprocess.run([sys.executable,str(scripts/"run_stateful_crossover.py"),"--family",positive],cwd=ROOT)
    env=dict(os.environ,PROTECTED_STATEFUL=negative_name)
    negative=subprocess.run([sys.executable,str(scripts/"run_shared_firmware.py")],cwd=ROOT,env=env)
    path=ROOT/f"reports/compute_stateful_{negative_name}_runs.csv"
    rows=list(csv.DictReader(path.open())) if path.is_file() else []
    row=rows[0] if len(rows)==1 else {}
    trace=ROOT/row.get("trace","MISSING")
    parsed=events(trace) if trace.is_file() else []
    setups=[e for e in parsed if e["kind"]=="APB_SETUP" and e.get("addr")==address and e.get("write")=="0"]
    remaps=[e for e in parsed if e["kind"]=="APB" and e.get("addr")==pte_address and e.get("wdata")==pte_value and e.get("write")=="1"]
    submits=[e for e in parsed if e["kind"]=="SUBMIT" and e.get("tag")==tag]
    log=(trace.parent/"simulation.log").read_text() if (trace.parent/"simulation.log").is_file() else ""
    handlers=[e for e in parsed if e['kind']=='RETIRE' and e.get('intr')=='1' and e.get('mcause')=='80000007']
    context=remaps if pte_address else handlers
    active=bool(setups and context and submits and int(submits[-1]["cycle"])<int(setups[-1]["cycle"]) and
                (int(context[-1]['cycle'])<int(submits[-1]['cycle']) if pte_address else
                 int(submits[-1]['cycle'])<int(context[-1]['cycle'])<int(setups[-1]['cycle'])))
    exact="OWNERSHIP_VIOLATION: CPU accessed owned line "+address in log
    bound=trace.is_file() and hashlib.sha256(trace.read_bytes()).hexdigest()==row.get("trace_sha256")
    passed=control.returncode==0 and negative.returncode==0 and row.get("status")=="PASS" and active and exact and bound
    result=dict(scenario=negative_name,status="PASS" if passed else "FAIL",
                nominal_control="PASS" if control.returncode==0 else "FAIL",negative_activated=str(active).lower(),
                intended_diagnostic=str(exact).lower(),witness_event_ids=";".join(e["eid"] for e in context[-1:]+submits[-1:]+setups[-1:]),
                trace=row.get("trace",""),trace_sha256=row.get("trace_sha256",""))
    return result


def main():
    rows=[run_case("stateful_stale_mapping_unowned_page","stateful_stale_mapping_owned_page","10006000","237","30001018","04001ccf"),
          run_case("stateful_alias_unowned_line","stateful_alias_owned_line","10006004","250","30001020","040018cf"),
          run_case("stateful_handler_cached_arithmetic","stateful_handler_owned_line","10001000","53")]
    with (ROOT/"reports/compute_ownership_alias_check.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    print(f"Physical alias checker: {sum(r['status']=='PASS' for r in rows)}/{len(rows)}")
    return int(any(r["status"]!="PASS" for r in rows))


if __name__=="__main__":raise SystemExit(main())
