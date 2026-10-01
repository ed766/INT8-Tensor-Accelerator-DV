"""Qualify CPU scenario intent using architectural dependencies, not labels."""
from __future__ import annotations


def instruction(event):
    return int(event.get("insn", "0"), 16)


def is_m(event):
    insn = instruction(event)
    return insn & 0x7f == 0x33 and insn >> 25 == 1


def cycle(event):
    return int(event["cycle"])


def refs(events):
    return ";".join(event["eid"] for event in events)


def qualify(name, events):
    case = int(name.rsplit("_", 1)[1])
    intent = {1: "m_result_to_address", 2: "m_result_to_descriptor",
              3: "load_m_store_dependency", 4: "m_result_to_branch",
              5: "device_irq_during_div", 6: "reset_unconsumed_m_result"}[case]
    retires = [e for e in events if e.get("kind") == "RETIRE" and
               e.get("trap") == "0" and e.get("intr") == "0"]
    # Only the engine busy interval qualifies as active DMA. Submission may sit
    # queued, and completion consumption may happen long after publication.
    overlap = []
    for busy in (e for e in events if e.get("kind") == "DMA_ACTIVE_START"):
        end = next((e for e in events if e.get("kind") == "DMA_ACTIVE_END" and
                    e.get("epoch") == busy.get("epoch") and e.get("tag") == busy.get("tag") and
                    cycle(e) > cycle(busy)), None)
        active_m = next((r for r in retires if is_m(r) and r.get("epoch") == busy.get("epoch") and
                         cycle(busy) < cycle(r) < cycle(end)), None) if end else None
        if active_m and end:
            overlap = [busy, active_m, end]
            break
    witnesses = []
    if case in (1, 2, 4):
        for first, second in zip(retires, retires[1:]):
            if not is_m(first) or first.get("rd_addr") == "0" or first.get("epoch") != second.get("epoch"):
                continue
            rd = first.get("rd_addr")
            opcode = instruction(second) & 0x7f
            if case == 1 and opcode == 3 and second.get("rs1_addr") == rd and \
                    second.get("mem_addr") == first.get("rd_data"):
                witnesses = [first, second]
            elif case == 2 and opcode == 0x23 and second.get("rs2_addr") == rd and \
                    second.get("mem_addr") == "4000000c" and second.get("mem_wdata") == first.get("rd_data"):
                submit = next((e for e in events if e.get("kind") == "SUBMIT" and
                               e.get("epoch") == second.get("epoch") and cycle(e) > cycle(second)), None)
                if submit:
                    value = int(first["rd_data"], 16)
                    command = next((e for e in events if e.get("kind")=="ACCEL_CMD" and
                                    e.get("epoch")==submit.get("epoch") and e.get("tag")==submit.get("tag") and cycle(e)>cycle(submit)), None)
                    completion = next((e for e in events if e.get("kind")=="COMPLETE_PUBLISH" and
                                       e.get("epoch")==submit.get("epoch") and e.get("tag")==submit.get("tag") and cycle(e)>cycle(submit)), None)
                    if command and completion and int(command["k"]) == value & 127 and int(completion["vectors_done"]) == (value >> 7) & 127:
                        witnesses = [first, second, submit, command, completion]
            elif case == 4 and opcode == 0x63 and rd in (second.get("rs1_addr"), second.get("rs2_addr")):
                witnesses = [first, second]
            if witnesses:
                break
    elif case == 3:
        for load, arithmetic, store in zip(retires, retires[1:], retires[2:]):
            if instruction(load) & 127 == 3 and is_m(arithmetic) and instruction(store) & 127 == 0x23 and \
                    load.get("rd_addr") != "0" and load.get("rd_addr") in (arithmetic.get("rs1_addr"), arithmetic.get("rs2_addr")) and \
                    arithmetic.get("rd_addr") != "0" and arithmetic.get("rd_addr") == store.get("rs2_addr") and \
                    arithmetic.get("rd_data") == store.get("mem_wdata") and \
                    load.get("epoch") == arithmetic.get("epoch") == store.get("epoch"):
                witnesses = [load, arithmetic, store]
                break
    elif case == 5:
        for irq in (e for e in events if e.get("kind") == "IRQ_SET" and e.get("ext") == "1" and e.get("muldiv_busy") == "1"):
            next_retire = next((e for e in events if e.get("kind") == "RETIRE" and e.get("epoch") == irq.get("epoch") and cycle(e) >= cycle(irq)), None)
            if next_retire and is_m(next_retire) and (instruction(next_retire) >> 12) & 7 == 4:
                entry = next((e for e in events if e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                              e.get("epoch") == irq.get("epoch") and cycle(e) > cycle(next_retire)), None)
                if entry and entry.get("mepc") == next_retire.get("next_pc"):
                    witnesses = [irq, next_retire, entry]
                    break
    elif case == 6:
        reset = next((e for e in events if e.get("kind") == "RESET_ASSERT" and e.get("muldiv_result_valid") == "1"), None)
        if reset:
            reboot = next((e for e in retires if e.get("epoch") == reset.get("epoch") and e.get("pc") == "00000000"), None)
            if reboot:
                witnesses = [reset, reboot]
    success = bool(witnesses and overlap)
    return {"scenario_intent": intent, "scenario_intent_status": "PASS" if success else "STIMULUS_NOT_REACHED",
            "scenario_intent_event_ids": refs(witnesses), "scenario_active_dma_event_ids": refs(overlap)}
