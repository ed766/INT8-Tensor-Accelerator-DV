#!/usr/bin/env python3
"""Generate event-correlated closure evidence for the compute crossover."""
from __future__ import annotations
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
from check_crossover_trace import events as load_events  # noqa: E402
DIRECTED=ROOT/"reports/compute_crossover_directed.csv"
MODEL=ROOT/"reports/compute_crossover_model.csv"
MANIFEST=ROOT/"integration/protected_offload/coverage/compute_crossover_manifest.json"
CSV_OUT=ROOT/"reports/compute_crossover_coverage.csv"
MD_OUT=ROOT/"reports/compute_crossover_coverage.md"

def _num(event, key, default=0):
    try:
        value=event.get(key, default)
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return default

def _hex_num(event, key, default=0):
    try:
        return int(str(event[key]), 16)
    except (KeyError, TypeError, ValueError):
        return default

def _kinds(events, *required):
    kinds={event.get("kind") for event in events}
    return all(item in kinds for item in required)

def _has_m_dma_overlap(events):
    starts=[event for event in events if event.get("kind") == "DMA_ACTIVE_START"]
    ends=[event for event in events if event.get("kind") == "DMA_ACTIVE_END"]
    def is_m(event):
        try:
            insn=int(event.get("insn", "0"), 16)
        except ValueError:
            return False
        return (insn & 0x7f) == 0x33 and ((insn >> 25) & 0x7f) == 1
    return any(event.get("kind") == "RETIRE" and is_m(event) and
               any(start.get("epoch") == event.get("epoch") == end.get("epoch") and
                   start.get("tag") == end.get("tag") and
                   _num(start, "cycle") <= _num(event, "cycle") < _num(end, "cycle")
                   for start in starts for end in ends)
               for event in events)

def _completion_after_memory(events):
    submissions={event.get("tag"):event for event in events if event.get("kind")=="SUBMIT"}
    responses=[event for event in events if event.get("kind")=="MEM_RSP" and
               event.get("write")=="1" and event.get("committed")=="1" and event.get("error")=="0"]
    for done in (event for event in events if event.get("kind")=="COMPLETE_PUBLISH" and event.get("status")=="0"):
        submit=submissions.get(done.get("tag"))
        matched=[event for event in responses if event.get("tag")==done.get("tag") and
                 event.get("epoch")==done.get("epoch") and _num(event,"cycle")<_num(done,"cycle")]
        consumed=next((event for event in events if event.get("kind")=="COMPLETE" and
                       event.get("tag")==done.get("tag") and event.get("asid")==done.get("asid") and
                       event.get("status")==done.get("status") and _num(event,"cycle")>_num(done,"cycle")),None)
        if submit and _num(submit,"cycle")<_num(done,"cycle") and matched and consumed:
            return [submit,max(matched,key=lambda event:_num(event,"cycle")),done,consumed]
    return []

PREDICATE_WITNESS = {
    "rv32m_dma_overlap": "RETIRE", "apb_wait_state": "APB",
    "reset_epoch_recovery": "RESET_RELEASE", "translation_fault": "XLATE_RSP",
    "interrupt_delivery": "RETIRE", "completion_after_memory": "COMPLETE_PUBLISH",
    "referenced_bank_rejection": "APB", "unrelated_cpu_access_during_owned_buffers": "OWNERSHIP",
    "aes_int8_overlap": "CHIPLET_EVT", "transport_backpressure": "APB_WAIT",
    "chiplet_sleep_wake_during_offload": "CHIPLET_POWER",
    "rv32m_interrupt_pending_at_retirement": "MDIV_BUSY",
    "transport_payload_identity": "ACCEL_IN",
    "independent_translation_result": "XLATE_RSP",
    "maintenance_lifecycle": "MAINT_START",
}


def _evidence_window(row, wanted=None):
    path=ROOT / row["trace"]
    if not path.exists():
        return "", ""
    trace=load_events(path)
    if wanted == "M_RETIRE":
        selected=[event for event in trace if event.get("kind")=="RETIRE" and
                  ((int(event.get("insn","0"),16)&0x7f)==0x33) and
                  (((int(event.get("insn","0"),16)>>25)&0x7f)==1)]
    else:
        selected=[event for event in trace if wanted is None or event.get("kind") == wanted]
    if not selected:
        return "", ""
    # Event-only points are reachability summaries; cite one exact event, not
    # an interval that could be misread as a same-window cross.
    event_id=selected[0].get("eid", "")
    return event_id, event_id

def _row(point_type, point, status, hits, evidence, wanted=None, witnesses=None):
    if wanted is None and point_type == "required_predicate":
        wanted = PREDICATE_WITNESS.get(point)
    first=hits[0]["scenario"] if hits else "NOT_REACHED"
    witness_events=(witnesses or {}).get(first, [])
    if witness_events:
        # A witness is an event set.  Preserve trace chronology even when the
        # predicate is assembled from independently searched event classes.
        witness_events=sorted(witness_events,key=lambda event:_num(event,"eid",-1))
        ids=[event.get("eid","") for event in witness_events]
        first_eid=ids[0]
        # Witness events are often separated by long stretches of unrelated
        # traffic. A dense numeric range would overstate the correlation.
        window=",".join(ids)
        witness_ids=";".join(ids)
    else:
        # Scenario/family rows are accounting summaries, not evidence points.
        # Never manufacture a witness from the first arbitrary trace event.
        first_eid,window=("NOT_A_WITNESS", "") if point_type == "family" else (_evidence_window(hits[0], wanted) if hits else ("", ""))
        witness_ids=first_eid
    return {"point_type":point_type,"point":point,"status":status,"hit_count":len(hits),
            "first_test":first,"first_event_id":first_eid,"event_window":window,
            "witness_event_ids":witness_ids,
            "manifest_sha256":hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            "directed_report_sha256":hashlib.sha256(DIRECTED.read_bytes()).hexdigest(),
            "generator_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "contributing_tests":";".join(row["scenario"] for row in hits),"evidence":evidence}


def _witnesses(point, ev, row):
    kinds=[event for event in ev if event.get("epoch")=="0"]
    if point=="rv32m_interrupt_pending_at_retirement":
        busy_start=irq=busy_end=None
        for event in kinds:
            if event.get("kind")=="MDIV_BUSY" and event.get("busy")=="1":
                busy_start=event
            elif busy_start and event.get("kind")=="IRQ_SET" and irq is None and _num(event,"cycle")>=_num(busy_start,"cycle"):
                irq=event
            elif busy_start and irq and event.get("kind")=="MDIV_BUSY" and event.get("busy")=="0":
                busy_end=event
                break
        if not (busy_start and irq and busy_end):return []
        is_m=lambda event: (int(event.get("insn","0"),16)&0x7f)==0x33 and (((int(event.get("insn","0"),16)>>25)&0x7f)==1)
        mret=next((event for event in kinds if event.get("kind")=="RETIRE" and is_m(event) and
                   _num(event,"cycle")>=_num(busy_start,"cycle")),None)
        intr=next((event for event in kinds if event.get("kind")=="RETIRE" and event.get("intr")=="1" and
                   mret is not None and _num(event,"cycle")>_num(mret,"cycle")),None)
        if (mret and intr and _num(irq,"cycle")<=_num(mret,"cycle") and
            _num(intr,"retire_order")==_num(mret,"retire_order")+1 and intr.get("pc")==mret.get("next_pc")):
            return [busy_start,irq,busy_end,mret,intr]
        return []
    if point=="rv32m_dma_overlap":
        starts=[event for event in kinds if event.get("kind")=="DMA_ACTIVE_START"]
        ends=[event for event in kinds if event.get("kind")=="DMA_ACTIVE_END"]
        m_events=[event for event in kinds if event.get("kind")=="RETIRE" and
                  ((int(event.get("insn","0"),16)&0x7f)==0x33) and
                  (((int(event.get("insn","0"),16)>>25)&0x7f)==1)]
        for start in starts:
            end=next((event for event in ends if event.get("epoch")==start.get("epoch") and
                      event.get("tag")==start.get("tag") and _num(event,"cycle")>_num(start,"cycle")),None)
            found=next((event for event in m_events if end and event.get("epoch")==start.get("epoch") and
                        _num(start,"cycle")<_num(event,"cycle")<_num(end,"cycle")),None)
            if found and end:return [start,found,end]
        return []
    if point=="transport_payload_identity":
        for response in (event for event in kinds if event.get("kind")=="MEM_RSP" and
                         event.get("write")=="0" and event.get("error")=="0"):
            match=next((event for event in kinds if event.get("kind")=="ACCEL_IN" and
                        event.get("epoch")==response.get("epoch") and event.get("tag")==response.get("tag") and
                        event.get("vector")==response.get("vector") and event.get("data")==response.get("rdata") and
                        _num(event,"cycle")>=_num(response,"cycle")),None)
            if match:return [response,match]
        return []
    if point=="independent_translation_result":
        for response in (event for event in kinds if event.get("kind")=="XLATE_RSP" and
                         _num(event,"fault")==0 and "paddr" in event and "tlb_hit" in event):
            request=next((event for event in kinds if event.get("kind")=="XLATE_REQ" and
                          event.get("epoch")==response.get("epoch") and event.get("txn")==response.get("txn") and
                          event.get("tag")==response.get("tag") and event.get("vector")==response.get("vector")),None)
            if request:return [request,response]
        return []
    if point=="maintenance_lifecycle":
        for start in (event for event in kinds if event.get("kind")=="MAINT_START"):
            done=next((event for event in kinds if event.get("kind")=="MAINT_DONE" and
                       event.get("epoch")==start.get("epoch") and event.get("cmd")==start.get("cmd") and
                       _num(event,"cycle")>_num(start,"cycle")),None)
            if done:return [start,done]
        return []
    if point=="apb_wait_state":
        return [event for event in kinds if event.get("kind")=="APB" and _num(event,"wait_cycles")>0][:1]
    if point=="reset_epoch_recovery":
        for asserted in (event for event in ev if event.get("kind")=="RESET_ASSERT"):
            if not (_num(asserted,"xlate_pending") or _num(asserted,"mem_pending") or
                    _num(asserted,"apb_active") or _num(asserted,"chip_busy") or
                    _num(asserted,"maint_active")):
                continue
            released=next((event for event in ev if event.get("kind")=="RESET_RELEASE" and
                           event.get("epoch")==asserted.get("epoch") and
                           _num(event,"cycle")>_num(asserted,"cycle")),None)
            if released:
                epoch=released.get("epoch")
                recovered=next((event for event in ev if event.get("kind") in ("COMPLETE","FIRMWARE_DONE") and
                                event.get("epoch")==epoch and _num(event,"cycle")>_num(released,"cycle")),None)
                if recovered:
                    return [asserted,released,recovered]
        return []
    if point=="translation_fault":
        for response in (event for event in kinds if event.get("kind")=="XLATE_RSP" and _num(event,"fault")!=0):
            request=next((event for event in kinds if event.get("kind")=="XLATE_REQ" and
                          event.get("txn")==response.get("txn") and event.get("tag")==response.get("tag") and
                          event.get("vector")==response.get("vector") and
                          _num(event,"cycle")<_num(response,"cycle")),None)
            if request:return [request,response]
        return []
    if point=="interrupt_delivery":
        for take in (event for event in kinds if event.get("kind")=="RETIRE" and event.get("intr")=="1"):
            external = bool(_num(take,"irq_level") and (_hex_num(take,"mie") & (1 << 11)))
            timer = bool(_num(take,"irq_timer_level") and (_hex_num(take,"mie") & (1 << 7)))
            cause = _hex_num(take,"mcause") & 0x7fffffff
            source = next((event for event in kinds if event.get("kind")=="IRQ_SET" and
                           _num(event,"cycle")<=_num(take,"cycle")),None) if external else None
            if (external and source and cause==11) or (timer and cause==7):
                return [source,take] if source else [take]
        return []
    if point=="completion_after_memory":
        return _completion_after_memory(kinds)
    if point=="referenced_bank_rejection":
        ownership=[event for event in kinds if event.get("kind")=="OWNERSHIP" and _num(event,"count")>0]
        rejected=[event for event in kinds if event.get("kind")=="APB" and event.get("write")=="1" and
                  event.get("error")=="1" and event.get("addr") in ("40001010","40001014")]
        if ownership and rejected and _num(ownership[-1],"cycle")<_num(rejected[-1],"cycle"):
            return [ownership[-1],rejected[-1]]
        return []
    if point=="unrelated_cpu_access_during_owned_buffers":
        if row.get("cache")!="1":return []
        owned=next((event for event in kinds if event.get("kind")=="OWNERSHIP" and _num(event,"count")>0),None)
        during=next((event for event in kinds if event.get("kind")=="OWNED_CPU_ACCESS" and owned is not None and
                     _num(event,"cycle")>=_num(owned,"cycle") and int(event.get("addr","0"),16)==0x10008000),None)
        start=next((event for event in kinds if event.get("kind")=="MAINT_START" and during is not None and
                    _num(event,"cycle")>_num(during,"cycle")),None)
        done=next((event for event in kinds if event.get("kind")=="MAINT_DONE" and start is not None and
                   _num(event,"cycle")>_num(start,"cycle")),None)
        # This required pass is a positive control: unrelated shared memory is
        # accessed during buffer ownership and must remain legal. Negative
        # owned-buffer access is covered by the expected-fail lane.
        if row.get("scenario")!="cache_ownership__case_6":return []
        return [owned,during,start,done] if owned and during and start and done and _num(start,"cycle")<=_num(done,"cycle") else []
    if point=="aes_int8_overlap":
        intervals=[];started=None
        for event in kinds:
            if event.get("kind")=="CHIPLET_EVT":
                if _num(event,"busy") and started is None:started=event
                if not _num(event,"busy") and started is not None:
                    intervals.append((started,event));started=None
        for start,end in intervals:
            activity=next((event for event in kinds if event.get("kind") in ("ACCEL_CMD","ACCEL_IN","ACCEL_OUT") and
                           _num(start,"cycle")<=_num(event,"cycle")<=_num(end,"cycle")),None)
            if activity:return [start,activity,end]
        return []
    if point=="chiplet_sleep_wake_during_offload":
        power=[event for event in kinds if event.get("kind")=="CHIPLET_POWER"]
        states=[_num(event,"state") for event in power]
        sleep_index=next((i for i,state in enumerate(states) if state==2),None)
        wake=next((event for i,event in enumerate(power) if sleep_index is not None and i>sleep_index and _num(event,"state")==0),None)
        if sleep_index is None or wake is None:return []
        start=power[sleep_index]
        # This scenario runs the accelerator while the chiplet is in SLEEP,
        # while the chiplet's accepted AES transfer itself remains busy across
        # the sleep interval and completes only after restoration.
        job=next((event for event in kinds if event.get("kind")=="ACCEL_CMD" and
                  _num(start,"cycle")<_num(event,"cycle")<_num(wake,"cycle")),None)
        accel_result=next((event for event in kinds if event.get("kind")=="ACCEL_OUT" and
                           job is not None and event.get("tag")==job.get("tag") and
                           _num(start,"cycle")<_num(event,"cycle")<_num(wake,"cycle")),None)
        busy=next((event for event in kinds if event.get("kind")=="CHIPLET_EVT" and
                   _num(event,"busy")==1 and _num(event,"cycle")<=_num(start,"cycle")),None)
        done=next((event for event in kinds if event.get("kind")=="CHIPLET_EVT" and
                   _num(event,"busy")==0 and busy is not None and
                   _num(event,"cycle")>=_num(wake,"cycle")),None)
        return [busy,start,job,accel_result,wake,done] if all((busy,job,accel_result,done)) else []
    if point=="transport_backpressure":
        return [event for event in kinds if event.get("kind")=="AXI_WAIT"][:1]
    return []

def main():
    manifest=json.loads(MANIFEST.read_text())
    directed=list(csv.DictReader(DIRECTED.open()))
    model={Path(row["trace"]).parent.name: row for row in csv.DictReader(MODEL.open())}
    rows=[]
    for family in manifest["families"]:
        hits=[row for row in directed if row["family"] == family and row["status"] == "PASS"
              and model.get(Path(row["trace"]).parent.name, {}).get("status") == "PASS"]
        rows.append(_row("family", family, "PASS" if len(hits) >= 6 else "FAIL", hits,
                         "RTL trace + transaction replay"))

    # These are executable crossover predicates, not scenario-name bins.  A
    # predicate is credited only when the event window is present in a passing
    # RTL trace.  Missing signals intentionally remain FAIL until stimulus and
    # observer support are added; this prevents a family sweep from claiming
    # queue, reset, power, or concurrency closure it did not exercise.
    predicate_points = tuple(manifest["required_predicates"])
    if len(set(predicate_points)) != len(predicate_points):
        raise SystemExit("coverage manifest contains duplicate required predicates")
    missing_implementations = set(predicate_points) - set(PREDICATE_WITNESS)
    if missing_implementations:
        raise SystemExit("coverage predicates lack explicit witness implementation: " + ",".join(sorted(missing_implementations)))
    for point in predicate_points:
        hits=[]
        witnesses={}
        for row in directed:
            if row["status"] != "PASS" or model.get(Path(row["trace"]).parent.name, {}).get("status") != "PASS":
                continue
            trace_path=ROOT / row["trace"]
            if trace_path.exists():
                found=_witnesses(point,load_events(trace_path),row)
                if found:
                    hits.append(row)
                    witnesses[row["scenario"]]=found
        rows.append(_row("required_predicate", point, "PASS" if hits else "FAIL", hits,
                         "predicate-specific event IDs + independent replay", witnesses=witnesses))
    # Event coverage is counted from the observer trace itself.  Model-summary
    # CSV columns are intentionally not used as a proxy for event presence.
    for event in manifest["required_events"]:
        hits=[]
        for row in directed:
            if row["status"] != "PASS" or model.get(Path(row["trace"]).parent.name, {}).get("status") != "PASS":
                continue
            trace_path=ROOT / row["trace"]
            if not trace_path.exists():
                continue
            ev=load_events(trace_path)
            if event == "M_RETIRE":
                has_event=any(e.get("kind")=="RETIRE" and _num(e,"m_ext")==1 and
                              ((int(e.get("insn","0"),16)&0x7f)==0x33) and
                              (((int(e.get("insn","0"),16)>>25)&0x7f)==1) for e in ev)
            else:
                has_event=any(e.get("kind")==event for e in ev)
            if has_event: hits.append(row)
        rows.append(_row("event", event, "PASS" if hits else "FAIL", hits,
                         "passing RTL observer traces", "RETIRE" if event == "M_RETIRE" else event))
    CSV_OUT.parent.mkdir(exist_ok=True)
    with CSV_OUT.open("w",newline="") as out:
        writer=csv.DictWriter(out,fieldnames=rows[0].keys(),lineterminator="\n"); writer.writeheader();writer.writerows(rows)
    required=[row for row in rows if row["point_type"] == "required_predicate"]
    MD_OUT.write_text("# Compute Crossover Coverage\n\n"
        f"Supplemental family/event reachability (not closure bins): **{sum(row['status'] == 'PASS' for row in rows if row['point_type'] in ('family','event'))} / {sum(row['point_type'] in ('family','event') for row in rows)}**.\n\n"
        f"Observed executable predicates: **{sum(row['status'] == 'PASS' for row in required)} / {len(required)}**. This is not the planned transaction-cross coverage closure.\n\n"
        "A predicate is credited only from its listed event IDs in a passing RTL trace. `NOT_REACHED` is a verification gap, not a pass. The comma-separated witness IDs are exact; they do not imply that intervening trace events belong to the same coverage sample.\n\n"
        "| Type | Point | Status | Hits | First test | First event | Window |\n|---|---|---:|---:|---|---:|---|\n"+
        "".join(f"| {row['point_type']} | `{row['point']}` | {row['status']} | {row['hit_count']} | `{row['first_test']}` | `{row['first_event_id']}` | `{row['event_window']}` |\n" for row in rows)+
        "\nCoverage is trace-derived from the real firmware integration top. It does not inflate the accelerator or chiplet canonical denominators.\n")
    predicate_pass=sum(row["status"] == "PASS" for row in required)
    print(f"Compute crossover observed predicates: {predicate_pass} / {len(required)}; supplemental family/event rows are not closure bins")
    raise SystemExit(predicate_pass != len(required))

if __name__ == "__main__": main()
