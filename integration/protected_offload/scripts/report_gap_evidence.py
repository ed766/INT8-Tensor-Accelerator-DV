#!/usr/bin/env python3
"""Audit advanced crosses and contention from execution-bound event windows."""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from check_crossover_trace import events
from reset_evidence import phase_reached
from stateful_cases import cases,random_cases

ROOT=Path(__file__).resolve().parents[3]
csv.field_size_limit(20_000_000)


def contributions(parsed):
    prior=defaultdict(list);active={};invalidates=[];owned={};maintenance=None
    for event in parsed:
        kind=event["kind"];key=(event["epoch"],event.get("tag"))
        if kind=="SUBMIT":active[key]=event;owned[key]=event
        elif kind=="COMPLETE_PUBLISH":owned.pop(key,None)
        elif kind=="MAINT_START" and event.get('cache_enabled')=='1':
            maintenance=(event,'device' if owned else 'free')
        elif kind=="MAINT_DONE" and maintenance:
            start,phase=maintenance
            if start['cmd']!=event['cmd']:raise ValueError('maintenance command changed within trace window')
            if phase==('device' if owned else 'free'):
                yield 'cache_maintenance',(phase,int(event['cmd']),'error' if event['error']=='1' else 'success'),[start,event]
            maintenance=None
        elif kind=="RESET_ASSERT":active.clear();prior.clear();invalidates=[];owned.clear();maintenance=None
        elif kind=="TLB_INVALIDATE":invalidates.append(event)
        elif kind=="XLATE_RSP" and event.get("fault") in ("0","2"):
            yield "permission",(int(event["write"]),int(event["tlb_hit"]),"allow" if event["fault"]=="0" else "deny"),[event]
        elif kind=="RETIRE" and event.get("trap")=="0" and int(event.get("insn","0"),16)&0xfe00007f==0x02000033:
            for source,field in (("timer","irq_timer_level"),("external","irq_level")):
                if event.get(field)=="1":yield "irq_pending_m_retirement",(source,"enabled" if int(event["mstatus"],16)&8 else "masked"),[event]
        elif kind=="COMPLETE":
            submit=active.pop(key,None)
            if event["status"]!="0" and submit:prior[key].append((submit,event))
            elif event["status"]=="0" and submit:
                for attempt,(old_submit,failed) in enumerate(prior.pop(key,[])):
                    fields=("input_iova","output_iova","k","batch","asid","bank","generation")
                    if any(submit[f]!=old_submit[f] for f in fields):continue
                    repair=[e for e in invalidates if e["epoch"]==event["epoch"] and
                            (e.get("all")=="1" or e.get("asid")==submit["asid"]) and
                            int(failed["cycle"])<int(e["cycle"])<int(submit["cycle"])]
                    if repair:
                        count=int(failed["vectors_done"]);batch=int(submit["batch"])
                        prefix="first" if count==0 else "last" if count==batch-1 else "middle"
                        yield "recovery",(int(failed["status"]),prefix),[old_submit,failed,repair[-1],submit,event]
                        yield "retry_attempt",(int(failed['status']),'first' if attempt==0 else 'repeated'),[old_submit,failed,repair[-1],submit,event]


def write_csv(path,rows):
    with path.open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)


def main():
    manifest=json.loads((ROOT/"integration/protected_offload/spec/gap_crosses.json").read_text())
    bins={(family,tuple(values)):[] for family,spec in manifest["families"].items() for values in spec["tuples"]}
    definitions={c["name"]:c for c in cases()+random_cases()}
    performance=[]
    for lane in ("all","random"):
        runs={r["scenario"]:r for r in csv.DictReader((ROOT/f"reports/compute_stateful_{lane}_runs.csv").open())}
        qualified=list(csv.DictReader((ROOT/f"reports/compute_stateful_{lane}_closure.csv").open()))
        expected={c["name"] for c in (cases() if lane=="all" else random_cases())}
        if set(runs)!=expected:raise SystemExit("advanced coverage requires the complete current scenario manifest")
        if set(runs)!=set(row["scenario"] for row in qualified):raise SystemExit("qualification/run mismatch")
        for row in qualified:
            run=runs[row["scenario"]];path=ROOT/row["trace"]
            if row["status"]!="PASS" or run["status"]!="PASS" or hashlib.sha256(path.read_bytes()).hexdigest()!=row["trace_sha256"]:
                raise SystemExit("advanced coverage requires qualified bound execution: "+row["scenario"])
            parsed=events(path);case=definitions[row["scenario"]]
            hits=list(contributions(parsed))
            if case["family"]=="gap_reset" and phase_reached(parsed,case["spec"][-1]):
                hits.append(("reset_boundary",(case["spec"][-1],),[e for e in parsed if e["kind"]=="RESET_ASSERT"]))
                owners={'ptw_req':('ptw','ptw_pending'),'accepted_output_write':('payload_write','mem_pending'),
                        'dma_b_wait':('payload_response','mem_pending'),'mem_rsp':('payload_read','mem_pending'),
                        'host_w_wait':('host_write','host_aw_pending'),'maintenance_invalidation':('maintenance','maint_active')}
                if case['spec'][-1] in owners:
                    owner,field=owners[case['spec'][-1]]
                    snapshots=[e for e in parsed if e['kind']=='RESET_ASSERT' and e.get(field)=='1']
                    for snapshot in snapshots:
                        before=parsed[:parsed.index(snapshot)]
                        label='MEM_REQ' if owner.startswith('payload') else 'PTW_REQ' if owner=='ptw' else 'AXI_AW' if owner=='host_write' else 'MAINT_START'
                        request=next((e for e in reversed(before) if e['kind']==label),None)
                        if request and (not owner.startswith('payload') or
                            request.get('write')==('0' if owner=='payload_read' else '1')):
                            hits.append(('reset_owner',(owner,case['spec'][-1]),[request,snapshot]))
            for family,values,window in hits:
                if (family,values) in bins:bins[(family,values)].append((row,case,window))
            if case["family"]=="gap_contention":
                for master in ("1","3"):
                    offers=[e for e in parsed if e["kind"]=="FABRIC_AR_OFFER" and e.get("master")==master and int(e["addr"],16)>>16==0x1000]
                    grants=[e for e in offers if e["accepted"]=="1"]
                    responses=[e for e in parsed if e["kind"]=="FABRIC_R_ACCEPT" and e.get("master")==master]
                    # These SRAM-target single-beat reads complete in acceptance order.
                    # This is a checked environment contract, not an AXI-wide order rule.
                    latencies=[int(r['cycle'])-int(g['cycle']) for g,r in zip(grants,responses)]
                    if any(n<0 or n>2048 for n in latencies):
                        raise SystemExit("finite target-progress assumption violated: "+row['scenario'])
                    waits=[];start=None
                    for e in offers:
                        if start is None:start=int(e["cycle"])
                        if e["accepted"]=="1":waits.append(int(e["cycle"])-start);start=None
                    gaps=[int(b["cycle"])-int(a["cycle"]) for a,b in zip(grants,grants[1:])]
                    performance.append(dict(scenario=row["scenario"],requested_stall_percent=case["stall"],master=master,
                        offered_cycles=len(offers),accepted_requests=len(grants),accepted_read_beats=len(responses),
                        max_arbitration_wait=max(waits,default=0),mean_arbitration_wait=f"{sum(waits)/len(waits):.3f}" if waits else "NA",
                        max_service_gap=max(gaps,default=0),age_override_grants=sum(e["kind"]=="FABRIC_AGE_GRANT" and e.get("master")==master for e in parsed),
                        target_progress_bound_cycles=2048,max_accepted_read_latency=max(latencies,default=0),
                        trace=row["trace"],trace_sha256=row["trace_sha256"]))
    rows=[]
    for (family,values),hits in bins.items():
        tests=list(dict.fromkeys(h[0]["scenario"] for h in hits));origins={h[1]["code"] for h in hits}
        # Different seeds from the same template do not count as independent construction.
        minimum=manifest["families"][family]["minimum_tests"]
        first=hits[0] if hits else None
        rows.append(dict(bin=family+":"+":".join(map(str,values)),family=family,status="HIT" if hits else "MISS",
            robustness="PASS" if len(origins)>=minimum else "GAP",minimum_independent_templates=minimum,independent_templates=len(origins),
            hit_count=len(hits),first_test=tests[0] if tests else "",all_tests=";".join(tests),
            witness_event_ids=";".join(e["eid"] for e in first[2]) if first else "",epoch=first[2][0]["epoch"] if first else "",
            trace=first[0]["trace"] if first else "",trace_sha256=first[0]["trace_sha256"] if first else ""))
    write_csv(ROOT/"reports/compute_gap_cross_coverage.csv",rows)
    write_csv(ROOT/"reports/compute_gap_contention.csv",performance)
    if any(r["accepted_requests"]!=r["accepted_read_beats"] for r in performance):
        raise SystemExit("contender or DMA read transactions not drained")
    lines=["# Advanced Crossover Coverage","",f"Observed bins: {sum(r['status']=='HIT' for r in rows)}/{len(rows)}. Robustness gaps: {sum(r['robustness']=='GAP' for r in rows)}.","",
           "| Family | Hit / required | Independent-template gaps |","|---|---:|---:|"]
    for family in manifest["families"]:
        group=[r for r in rows if r["family"]==family]
        lines.append(f"| {family} | {sum(r['status']=='HIT' for r in group)}/{len(group)} | {sum(r['robustness']=='GAP' for r in group)} |")
    lines.extend(["","[Trace windows](../reports/compute_gap_cross_coverage.csv) and [measured contention](../reports/compute_gap_contention.csv).",""]+manifest["exclusions"])
    (ROOT/"docs/compute_gap_cross_coverage.md").write_text("\n".join(lines)+"\n")
    print(lines[2])
    return int(any(r["status"]!="HIT" or r["robustness"]!="PASS" for r in rows))


if __name__=="__main__":raise SystemExit(main())
