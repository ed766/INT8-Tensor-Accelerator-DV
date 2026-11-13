#!/usr/bin/env python3
"""Report supplemental end-to-end predicates from execution-bound traces."""
import csv
import hashlib
from pathlib import Path
from check_crossover_trace import events,check
from run_stateful_crossover import qualify
from stateful_cases import cases
from end_to_end_checks import completion_reads

ROOT=Path(__file__).resolve().parents[3]


def main():
    source=ROOT/"reports/compute_stateful_all_runs.csv"
    runs={r["scenario"]:r for r in csv.DictReader(source.open())}
    rows=[]
    for case in cases():
        if case["family"]!="end_to_end":continue
        run=runs.get(case["name"],{})
        path=ROOT/run.get("trace","MISSING")
        errors=[];witnesses=[];parsed=[]
        if not path.is_file():errors.append("execution trace missing")
        else:
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if run.get("status")!="PASS" or digest!=run.get("trace_sha256"):errors.append("execution/provenance failure")
            parsed=events(path)
            checked=check(path,strict_schema=True)
            if checked["status"]!="PASS":errors.append(checked["errors"])
            witnesses,intent=qualify(parsed,case["code"],case["name"]);errors.extend(intent)
        reads=completion_reads(parsed)[0]
        rows.append(dict(scenario=case["name"],status="FAIL" if errors else "PASS",cycles=run.get("cycles",""),
                         accepted_jobs=sum(e["kind"]=="SUBMIT" for e in parsed),
                         consumed_completions=sum(e["kind"]=="COMPLETE" for e in parsed),
                         independently_checked_record_reads=len(reads),
                         witness_count=len(witnesses),event_ids=";".join(e["eid"] for e in witnesses),
                         trace=run.get("trace",""),trace_sha256=run.get("trace_sha256",""),errors=";".join(errors)))
    with (ROOT/"reports/compute_end_to_end_closure.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    text=["# End-to-End Closure Snapshot","",
          f"Qualified RTL scenarios: {sum(r['status']=='PASS' for r in rows)}/{len(rows)}. Canonical closure denominators are unchanged.","",
          "| Scenario | Result | Cycles | Accepted jobs | Consumed completions | Checked record reads |",
          "|---|---|---:|---:|---:|---:|"]
    text.extend(f"| {r['scenario']} | {r['status']} | {r['cycles']} | {r['accepted_jobs']} | {r['consumed_completions']} | {r['independently_checked_record_reads']} |" for r in rows)
    text.extend(["","Reset-aborted jobs need not produce completions. Record-read replay matches publication and consumption within reset boundaries, including reused tags after reboot.",
                 "","Trace IDs and SHA-256 bindings: [CSV](compute_end_to_end_closure.csv). This is supplemental scenario evidence, not a new Cartesian cross-coverage percentage."])
    (ROOT/"reports/compute_end_to_end_closure.md").write_text("\n".join(text)+"\n")
    print(text[2])
    return int(any(r["status"]!="PASS" for r in rows))


if __name__=="__main__":raise SystemExit(main())
