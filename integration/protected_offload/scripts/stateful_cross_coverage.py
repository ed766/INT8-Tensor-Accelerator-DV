#!/usr/bin/env python3
"""Supplemental crosses from complete, independently checked RTL traces."""
import csv
import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path
from check_crossover_trace import events
from run_stateful_crossover import ROOT
from stateful_cases import random_cases
csv.field_size_limit(20_000_000)


def contributions(parsed):
    hits=[];busy={};prior=defaultdict(list);invalidates=[];submits=defaultdict(list)
    for e in parsed:
        epoch=e["epoch"];kind=e["kind"]
        if kind=="SUBMIT":
            hits.append(("k_bank",(int(e["k"]),int(e["bank"])),[e]))
            submits[(epoch,e["tag"])].append(e)
        elif kind=="MDIV_BUSY" and e.get("busy")=="1":busy[(epoch,e["pc"])]=e
        elif kind=="RETIRE":
            insn=int(e["insn"],16);start=busy.pop((epoch,e["pc"]),None)
            if start and insn & 0xfe00007f==0x02000033 and e.get("trap")=="0":
                pressure="full" if int(start["comp_occ"])==4 else "not_full"
                hits.append(("m_completion_pressure",((insn>>12)&7,pressure),[start,e]))
        elif kind=="APB":
            hits.append(("apb_direction_wait",(int(e["write"]),"positive" if int(e["wait_cycles"]) else "zero"),[e]))
        elif kind=="TLB_INVALIDATE":invalidates.append(e)
        elif kind=="COMPLETE":
            key=(epoch,e["tag"]);history=submits[key]
            if e["status"]=="0":
                for old,failed_submit in prior[key]:
                    later=[s for s in history if int(s["cycle"])>int(old["cycle"])]
                    if not later or failed_submit is None:continue
                    submit=later[0]
                    if any(submit[field]!=failed_submit[field] for field in ("input_iova","output_iova","input_stride","output_stride","k","batch","asid","bank","generation")):continue
                    repair=[i for i in invalidates if i["epoch"]==epoch and (i.get("all")=="1" or i.get("asid")==submit["asid"]) and int(old["cycle"])<int(i["cycle"])<int(submit["cycle"])]
                    if repair:
                        hits.append(("recovery",(int(old["status"]),int(old["vectors_done"])),[failed_submit,old,repair[-1],submit,e]))
                prior[key]=[]
            else:prior[key].append((e,history[-1] if history else None))
    return hits


def main():
    manifest=json.loads((ROOT/"integration/protected_offload/spec/stateful_crosses.json").read_text())
    bins={}
    for family,spec in manifest["families"].items():
        tuples=spec.get("tuples") or itertools.product(*spec["dimensions"])
        for values in tuples:bins[(family,tuple(values))]=[]
    activity=[];random_by_name={c["name"]:c for c in random_cases()}
    for family in ("all","random"):
        runs={r["scenario"]:r for r in csv.DictReader((ROOT/f"reports/compute_stateful_{family}_runs.csv").open())}
        qualified=list(csv.DictReader((ROOT/f"reports/compute_stateful_{family}_closure.csv").open()))
        for row in qualified:
            run=runs[row["scenario"]];path=ROOT/row["trace"]
            if row["status"]!="PASS" or run["status"]!="PASS" or hashlib.sha256(path.read_bytes()).hexdigest()!=row["trace_sha256"]:
                raise SystemExit("cross coverage requires matching passing qualified traces: "+row["scenario"])
            parsed=events(path)
            if family=="random":
                case=random_by_name[row["scenario"]];spec=case["spec"]
                counts=[sum(e["kind"]=="RETIRE" and int(e.get("insn","0"),16)&0xfe00707f==0x02000033+(op<<12) for e in parsed) for op in range(8)]
                activity.append(dict(scenario=row["scenario"],seed=spec[10],k=spec[1],cache=spec[6],asid=spec[3],qos=spec[4],
                    requested_jobs=9,realized_submits=sum(e["kind"]=="SUBMIT" for e in parsed),
                    realized_completions=sum(e["kind"]=="COMPLETE" for e in parsed),
                    realized_bank1_jobs=sum(e["kind"]=="SUBMIT" and e.get("bank")=="1" for e in parsed),
                    requested_timer_entries=4,realized_timer_entries=sum(e["kind"]=="RETIRE" and e.get("intr")=="1" and e.get("mcause")=="80000007" for e in parsed),
                    requested_stall_percent=case["stall"],observed_axi_wait_events=sum(e["kind"]=="AXI_WAIT" for e in parsed),
                    requested_b_delay=case["b_delay"],requested_r_delay=case["r_delay"],
                    observed_maintenance_commands=sum(e["kind"]=="MAINT_START" for e in parsed),
                    m_opcode_retirements=";".join(map(str,counts)),trace=row["trace"],trace_sha256=row["trace_sha256"],
                    source_build_id=run["source_build_id"],stimulus_instance_sha256=run["stimulus_instance_sha256"]))
            for fam,values,window in contributions(parsed):
                if (fam,values) in bins:
                    bins[(fam,values)].append((row["scenario"],window,row["trace"],row["trace_sha256"]))
    rows=[]
    for (family,values),hits in bins.items():
        tests=list(dict.fromkeys(hit[0] for hit in hits));first=hits[0] if hits else None
        rows.append(dict(bin=family+":"+":".join(map(str,values)),family=family,status="HIT" if hits else "MISS",hit_count=len(hits),
                         first_test=tests[0] if tests else "",all_tests=";".join(tests),
                         witness_event_ids=";".join(e["eid"] for e in first[1]) if first else "",
                         epoch=first[1][0]["epoch"] if first else "",cycle_start=first[1][0]["cycle"] if first else "",
                         cycle_end=first[1][-1]["cycle"] if first else "",trace=first[2] if first else "",trace_sha256=first[3] if first else ""))
    with (ROOT/"reports/compute_stateful_cross_coverage.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    if any(r["realized_submits"]!=9 or r["realized_completions"]!=9 or r["realized_bank1_jobs"]!=4 or r["realized_timer_entries"]!=4 for r in activity):
        raise SystemExit("seeded activity counts do not match the requested workload")
    with (ROOT/"reports/compute_stateful_random_activity.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=activity[0],lineterminator="\n");writer.writeheader();writer.writerows(activity)
    lines=["# Stateful Interaction Coverage","","Supplemental to canonical crossover closure. No scenario-name credit or denominator inflation.","",
           "| Family | Hit / Required | Predicate |","|---|---:|---|"]
    for family,spec in manifest["families"].items():
        group=[r for r in rows if r["family"]==family]
        lines.append(f"| {family} | {sum(r['status']=='HIT' for r in group)}/{len(group)} | {spec['predicate']} |")
    lines += ["","[Event-window witnesses](../reports/compute_stateful_cross_coverage.csv). Every hit requires a matching trace hash, passing simulation, independent replay and scenario activation qualification. Raw traces remain generated artifacts.","",
              "[Seeded requested-versus-realized activity](../reports/compute_stateful_random_activity.csv) records applied knobs, descriptor/completion/bank/IRQ counts, M opcodes and AXI waits. Wait-event count is not a measurement of achieved ready-low duty percentage.","",
              "## Boundaries",""]+["- "+item+"." for item in manifest["exclusions"]]
    (ROOT/"docs/compute_stateful_cross_coverage.md").write_text("\n".join(lines)+"\n")
    print(f"Stateful crosses: {sum(r['status']=='HIT' for r in rows)}/{len(rows)}")
    for row in rows:
        if row["status"]=="MISS":print("MISS "+row["bin"])
    return int(any(r["status"]!="HIT" for r in rows))

if __name__=="__main__":raise SystemExit(main())
