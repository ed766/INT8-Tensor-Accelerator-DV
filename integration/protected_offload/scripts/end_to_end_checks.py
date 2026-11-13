"""Independent checks for CPU-visible completion records, not mailbox verdicts."""
from collections import deque


def physical_ownership(parsed):
    """Check actual resolved physical lines, including accesses before translation.

    Translation semantics are independently replayed by check_crossover_trace.
    This checker does not re-walk mutable PTEs or trust the RTL ownership verdict.
    """
    live={};witnesses=[];errors=[]
    def finish(record):
        for access in record["accesses"]:
            line=int(access["addr"],16)&~31
            if line in record["lines"]:
                witnesses.append((record["submit"],record["lines"][line],access))
                errors.append("physical_owned_line_cpu_access: event "+access["eid"])
    for event in parsed:
        key=(event.get("epoch"),event.get("tag"))
        if event["kind"]=="RESET_ASSERT":
            for record in live.values():finish(record)
            live.clear()
        elif event["kind"]=="SUBMIT":live[key]=dict(submit=event,lines={},accesses=[])
        elif event["kind"]=="XLATE_RSP" and event.get("fault")=="0" and key in live:
            live[key]["lines"][int(event["paddr"],16)&~31]=event
        elif event["kind"]=="OWNED_CPU_ACCESS":
            for record in live.values():record["accesses"].append(event)
        elif event["kind"]=="COMPLETE_PUBLISH" and key in live:finish(live.pop(key))
    for record in live.values():finish(record)
    return witnesses,errors


def reference_writes(parsed):
    """Configuration references last through publication, including RETIRE stalls."""
    live={}
    witnesses=[]
    errors=[]
    for event in parsed:
        if event["kind"]=="RESET_ASSERT":live.clear()
        elif event["kind"]=="SUBMIT":live[(event["epoch"],event["tag"])]=event
        elif event["kind"]=="COMPLETE_PUBLISH":live.pop((event["epoch"],event["tag"]),None)
        elif event["kind"]=="APB" and event.get("addr")=="40001010" and event.get("write")=="1" and event.get("error")=="0":
            value=int(event["wdata"],16)
            for descriptor in live.values():
                if ((value>>(8*int(descriptor["bank"])))&255)!=int(descriptor["generation"]):
                    witnesses.append((descriptor,event))
                    errors.append("referenced_generation_changed_before_publication: event "+event["eid"])
    return witnesses,errors


def completion_reads(parsed):
    """Compare APB front-record reads with ordered, replay-checked consumption."""
    errors = []
    witnesses = []
    # Reset is a lifetime boundary even if tags and addresses are reused.
    segments = [[]]
    for event in parsed:
        if event["kind"] == "RESET_ASSERT":
            segments.append([])
        else:
            segments[-1].append(event)
    consumed_by_segment = [deque(e for e in segment if e["kind"] == "COMPLETE")
                           for segment in segments]
    segment_index = 0
    consumed = consumed_by_segment[0]
    pending = deque()
    bus_read = None
    for event in parsed:
        kind = event["kind"]
        if kind == "RESET_ASSERT":
            if consumed:
                errors.append("completion consumption without publication before reset")
            pending.clear()
            bus_read = None
            segment_index += 1
            consumed = consumed_by_segment[segment_index]
        elif kind == "COMPLETE_PUBLISH":
            if not consumed:
                if segment_index == len(segments) - 1:
                    errors.append("completion publication without eventual consumption")
                # An unread record may be discarded only at the next reset.
                record = event
            else:
                record = consumed.popleft()
            if any(event.get(k) != record.get(k) for k in
                   ("epoch", "tag", "asid", "status", "fault_stage", "vectors_done")):
                errors.append("completion publication/consumption metadata mismatch")
            if "fault_iova" in event and event["fault_iova"] != record.get("fault_iova"):
                errors.append("completion publication/consumption fault address mismatch")
            pending.append((event, record))
        elif kind == "APB" and event.get("write") == "0" and event.get("error") == "0" and pending:
            address = event.get("addr")
            if address not in ("40000020", "40000024", "40000028"):
                continue
            publication, record = pending[0]
            expected = {
                "40000020": (int(record["vectors_done"]) << 12) |
                             (int(record["asid"]) << 4) | int(record["status"]),
                "40000024": int(record.get("fault_iova", "0"), 16),
                "40000028": (int(record["fault_stage"]) << 8) | int(record["tag"]),
            }[address]
            if address == "40000024" and "fault_iova" not in record:
                errors.append("completion publication missing fault address")
            if "rdata" not in event or int(event["rdata"], 16) != expected:
                errors.append("completion_metadata_read_mismatch: event " + event["eid"] +
                              " address " + address + " expected " + f"{expected:08x}")
            witnesses.append((publication, event, record))
            if bus_read is not None:
                errors.append("completion read issued before prior retirement")
            bus_read = event
        elif kind == "RETIRE" and bus_read is not None and event.get("intr") == "0":
            if (event.get("epoch") != bus_read["epoch"] or event.get("trap") != "0" or
                event.get("mem_addr") != bus_read["addr"] or event.get("mem_rmask") != "f" or
                event.get("mem_rdata") != bus_read.get("rdata") or
                (event.get("rd_addr") != "0" and event.get("rd_data") != bus_read.get("rdata"))):
                errors.append("completion_read_retirement_mismatch: event " + event["eid"])
            bus_read = None
        elif kind == "COMPLETE":
            if not pending or pending[0][1]["eid"] != event["eid"]:
                errors.append("completion consumption ownership mismatch")
            else:
                pending.popleft()
    if pending or consumed or bus_read is not None:
        errors.append("completion record lifetime not drained")
    return witnesses, errors
