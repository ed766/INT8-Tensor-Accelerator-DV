"""Reset reachability must demonstrate owned work, not a completed transfer."""


def phase_reached(events: list[dict[str, str]], phase: str) -> bool:
    resets = [event for event in events if event.get("kind") == "RESET_ASSERT"]
    if len(resets) != 1:
        return False
    reset = resets[0]
    if phase.startswith("metadata_"):
        address={"metadata_status":"40000020","metadata_address":"40000024","metadata_stage":"40000028"}[phase]
        return reset.get("completion_pending")=="1" and any(
            e.get("kind")=="APB" and e.get("addr")==address and e.get("write")=="0" and
            0<=int(reset["cycle"])-int(e["cycle"])<=2 for e in events[:events.index(reset)])
    if phase=="publication":
        return reset.get("completion_pending")=="1" and any(
            e.get("kind")=="COMPLETE_PUBLISH" and 0<=int(reset["cycle"])-int(e["cycle"])<=2
            for e in events[:events.index(reset)])
    if phase=="before_pop":
        return reset.get("completion_pending")=="1" and reset.get("apb_active")=="1"
    if phase=="dma_b_wait":
        before=events[:events.index(reset)]
        aw=next((e for e in reversed(before) if e.get("kind")=="DMA_AXI_AW"),None)
        return bool(reset.get("mem_pending")=="1" and aw and not any(
            e.get("kind")=="DMA_AXI_B" and int(e["cycle"])>=int(aw["cycle"]) for e in before))
    if phase == "multiple_owners":
        snapshots=[e for e in events if e.get("kind")=="RESET_IRQ_SNAPSHOT" and
                   e.get("epoch")==reset.get("epoch") and e.get("cycle")==reset.get("cycle")]
        return (all(reset.get(k)=="1" for k in ("muldiv_busy","dma_busy","mem_pending","completion_pending")) and
                len(snapshots)==1 and int(snapshots[0].get("pending","0"))&2!=0)
    if phase.startswith("m_dma_"):
        before=events[:events.index(reset)]
        start=next((event for event in reversed(before) if event.get("kind")=="MDIV_BUSY" and event.get("busy")=="1"),None)
        return bool(reset.get("muldiv_busy")=="1" and reset.get("dma_busy")=="1" and start and
                    start.get("dma_busy")=="1" and
                    (phase!="m_dma_response" or reset.get("muldiv_result_valid")=="1"))
    if phase == "prolonged_backpressure":
        before=events[:events.index(reset)]
        waits=[event for event in before if event.get("kind")=="APB_WAIT" and
               event.get("epoch")!=reset.get("epoch") and int(event.get("wait_cycles","0"))>=128 and
               0<=int(reset["cycle"])-int(event["cycle"])<=2]
        return bool(waits and reset.get("host_aw_pending")=="1" and reset.get("apb_active")=="1")
    if phase == "maintenance_invalidation":
        before=events[:events.index(reset)]
        start=next((event for event in reversed(before) if event.get("kind")=="MAINT_START" and
                    event.get("cache_enabled")=="1"),None)
        return bool(start and reset.get("maint_active")=="1" and
                    not any(event.get("kind")=="MAINT_DONE" and
                            int(event["cycle"])>=int(start["cycle"]) for event in before))
    if phase == "completion_irq":
        snapshots=[event for event in events if event.get("kind")=="RESET_IRQ_SNAPSHOT" and
                   event.get("epoch")==reset.get("epoch") and event.get("cycle")==reset.get("cycle")]
        return (reset.get("completion_pending")=="1" and
                int(reset.get("completion_occupancy","0"))>0 and len(snapshots)==1 and
                (int(snapshots[0].get("pending","0"))&2)!=0)
    if phase == "accepted_output_write":
        before = events[:events.index(reset)]
        aw = next((event for event in reversed(before) if event.get("kind") == "DMA_AXI_AW" and
                   event.get("master") == "1"), None)
        return bool(aw and reset.get("mem_pending") == "1" and
                    not any(event.get("kind") == "DMA_AXI_B" and event.get("master") == "1" and
                            int(event["cycle"]) >= int(aw["cycle"]) for event in before) and
                    0 <= int(reset["cycle"]) - int(aw["cycle"]) <= 2)
    if phase == "mem_rsp":
        return reset.get("mem_response_valid") == "1" and reset.get("mem_pending") == "1"
    if phase == "completion":
        return reset.get("completion_pending") == "1" and int(reset.get("completion_occupancy", "0")) > 0
    if phase == "mdiv_result":
        return reset.get("muldiv_result_valid") == "1" and reset.get("muldiv_busy") == "1"
    if phase == "host_w_wait":
        return reset.get("host_aw_pending") == "1" and reset.get("host_w_pending") == "0"
    if phase == "combined_busy":
        before = events[:events.index(reset)]
        chip = next((event for event in reversed(before)
                     if event.get("kind") == "CHIPLET_EVT" and event.get("busy") == "1"), None)
        dma = next((event for event in reversed(before)
                    if event.get("kind") == "DMA_ACTIVE_START"), None)
        return (reset.get("chip_busy") == "1" and reset.get("dma_busy") == "1" and
                chip is not None and dma is not None and
                chip.get("epoch") == dma.get("epoch") and
                int(chip["cycle"]) <= int(reset["cycle"]) and
                int(dma["cycle"]) <= int(reset["cycle"]))
    contract = {"ptw_req": ("XLATE_REQ", "xlate_pending"),
                "mem_req": ("MEM_REQ", "mem_pending"),
                "apb_wait": ("APB_WAIT", "apb_active"),
                "mdiv_busy": ("MDIV_BUSY", "muldiv_busy")}
    if phase not in contract:
        return False
    kind, owner = contract[phase]
    candidates = [event for event in events[:events.index(reset)] if event.get("kind") == kind]
    return bool(candidates and reset.get(owner) == "1" and
                0 <= int(reset["cycle"]) - int(candidates[-1]["cycle"]) <= 2)
