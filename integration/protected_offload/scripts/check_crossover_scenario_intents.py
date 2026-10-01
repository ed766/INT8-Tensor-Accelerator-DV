#!/usr/bin/env python3
"""Qualify named directed crossover intent from the actual observer trace.

This module intentionally describes only behavior visible in the current RTL
traces. It does not infer a test result from the requested plusargs or its
scenario name. Every successful qualification cites one or more event IDs.
"""
from __future__ import annotations

from collections.abc import Callable
from ownership_ranges import descriptor_physical_ranges, physical_access_owned

Event = dict[str, str]


def _cycle(e: Event) -> int:
    return int(e.get("cycle", "0"))


def _num(e: Event, key: str, default: int = 0) -> int:
    try:
        return int(e.get(key, str(default)), 0)
    except ValueError:
        return default


def _eid(events: list[Event], predicate: Callable[[Event], bool]) -> Event | None:
    return next((event for event in events if predicate(event)), None)


def _pair(events: list[Event], left_kind: str, right_kind: str,
          predicate: Callable[[Event, Event], bool]) -> tuple[Event, Event] | None:
    left = [event for event in events if event.get("kind") == left_kind]
    right = [event for event in events if event.get("kind") == right_kind]
    for a in left:
        for b in right:
            if a.get("epoch") == b.get("epoch") and predicate(a, b):
                return a, b
    return None


def _ok(label: str, *events: Event) -> dict[str, str]:
    ids = [event.get("eid", "") for event in events]
    if not ids or any(not event_id for event_id in ids):
        return {"scenario_intent": label, "scenario_intent_status": "FAIL",
                "scenario_intent_event_ids": "", "scenario_intent_reason": "missing_event_id"}
    return {"scenario_intent": label, "scenario_intent_status": "PASS",
            "scenario_intent_event_ids": ";".join(ids), "scenario_intent_reason": "observed"}


def _fail(label: str, reason: str) -> dict[str, str]:
    return {"scenario_intent": label, "scenario_intent_status": "FAIL",
            "scenario_intent_event_ids": "", "scenario_intent_reason": reason}


def _successful_job(events: list[Event]) -> tuple[Event, Event] | None:
    return _pair(events, "SUBMIT", "COMPLETE", lambda a, b:
                 a.get("tag") == b.get("tag") and a.get("asid") == b.get("asid") and
                 _cycle(a) < _cycle(b) and b.get("status") == "0")


def qualify(name: str, row: dict[str, str], events: list[Event]) -> dict[str, str]:
    """Return the trace-backed intent/status and exact event identifiers."""
    family, _, suffix = name.partition("__")
    case = suffix.rsplit("_", 1)[-1]
    kinds = [event.get("kind", "") for event in events]

    if family == "cpu_rv32m":
        return _fail("use_architectural_cpu_intent_checker", "delegated_to_cpu_intent_checker")

    if family == "apb_axi":
        if case == "1":
            setup = _eid(events, lambda e: e.get("kind") == "APB_SETUP" and
                         e.get("penable") == "0" and e.get("pready") == "1")
            access = next((e for e in events if setup and e.get("kind") == "APB" and
                           e.get("op") == setup.get("op") and _cycle(e) > _cycle(setup)), None)
            return _ok("setup_pready_waits_for_access", setup, access) if setup and access else \
                _fail("setup_pready_waits_for_access", "no_matching_access_after_setup_pready")
        if case == "2":
            rd = _eid(events, lambda e: e.get("kind") == "APB" and e.get("write") == "0" and _num(e, "wait_cycles") > 0)
            wr = _eid(events, lambda e: e.get("kind") == "APB" and e.get("write") == "1" and _num(e, "wait_cycles") > 0)
            return _ok("waited_read_and_write_retire", rd, wr) if rd and wr else \
                _fail("waited_read_and_write_retire", "missing_waited_direction")
        if case == "3":
            lo = _eid(events, lambda e: e.get("kind") == "AXI_W" and e.get("strb") == "0f")
            hi = _eid(events, lambda e: e.get("kind") == "AXI_W" and e.get("strb") == "f0")
            return _ok("lower_upper_axi_word_lanes", lo, hi) if lo and hi else \
                _fail("lower_upper_axi_word_lanes", "both_axi_strobe_lanes_not_observed")
        if case == "4":
            label = "region_edges_and_decode_holes"
            witnesses = []
            for addr in ("10000000", "1000fffc", "30000000", "3000fffc"):
                value = 0x619ac357 ^ int(addr, 16)
                write = _eid(events, lambda e: e.get("kind") == "RETIRE" and
                             e.get("mem_addr") == addr and e.get("mem_wmask") == "f" and
                             e.get("trap") == "0" and int(e.get("mem_wdata", "0"), 16) == value)
                read = next((e for e in events if write and e.get("kind") == "RETIRE" and
                             e.get("epoch") == write.get("epoch") and _cycle(e) > _cycle(write) and
                             e.get("mem_addr") == addr and e.get("mem_rmask") == "f" and
                             e.get("trap") == "0" and int(e.get("mem_rdata", "0"), 16) == value), None)
                if not write or not read:
                    return _fail(label, f"boundary_readback_missing_{addr}")
                witnesses.extend((write, read))
            expected = [("10010000", 5), ("10010000", 7),
                        ("20010000", 5), ("20010000", 7),
                        ("20000000", 5), ("2000fffc", 5)]
            faults = [e for e in events if e.get("kind") == "RETIRE" and e.get("trap") == "1"]
            if [(e.get("mem_addr"), int(e.get("mcause", "0"), 16)) for e in faults] != expected:
                return _fail(label, "boundary_decode_error_traps_missing")
            if any(e.get("rd_addr") != "0" for e in faults):
                return _fail(label, "fault_changed_destination_register")
            return _ok(label, *witnesses, *faults)
        if case == "5":
            label = "unsupported_width_and_alignment_traps"
            faults = [e for e in events if e.get("kind") == "RETIRE" and e.get("trap") == "1"]
            if [int(e.get("mcause", "0"), 16) for e in faults] != [5, 7, 4, 6]:
                return _fail(label, "missing_exact_width_and_alignment_trap_sequence")
            for fault in faults:
                if e_rd := int(fault.get("rd_addr", "0")):
                    return _fail(label, f"trapping_load_wrote_register_{e_rd}")
                if any(int(fault.get(field, "0"), 16) for field in ("mem_rmask", "mem_wmask")):
                    return _fail(label, "trapping_access_has_memory_side_effect")
                if any(e.get("epoch") == fault.get("epoch") and _cycle(e) == _cycle(fault)
                       and e.get("kind") in ("APB", "AXI_AW", "AXI_AR", "AXI_W") for e in events):
                    return _fail(label, "trapping_access_issued_bus_operation")
            return _ok(label, *faults)
        if case == "6":
            reset = _eid(events, lambda e: e.get("kind") == "RESET_ASSERT" and
                         _num(e, "host_aw_pending") == 1 and _num(e, "host_w_pending") == 0)
            release = next((e for e in events if reset and e.get("kind") == "RESET_RELEASE" and
                            e.get("epoch") == reset.get("epoch") and _cycle(e) > _cycle(reset)), None)
            return _ok("reset_after_aw_before_w", reset, release) if reset and release else \
                _fail("reset_after_aw_before_w", "split_channel_reset_not_observed")

    if family == "queues_configuration":
        if case == "1":
            label = "submit_fifo_pressure"
            submitted = [e for e in events if e.get("kind")=="SUBMIT"]
            rejected = [e for e in events if e.get("kind")=="SUBMIT_REJECT"]
            popped = [e for e in events if e.get("kind")=="COMPLETE"]
            identity = lambda records: [(e.get("epoch"),e.get("tag"),e.get("asid")) for e in records]
            if len(submitted)!=5 or len(popped)!=5 or len(rejected)!=1 or identity(submitted)!=identity(popped):
                return _fail(label, "five_ordered_jobs_and_one_overflow_rejection_required")
            overflow = rejected[0]
            if overflow.get("occupancy")!="4" or overflow.get("tag") in {e.get("tag") for e in submitted}:
                return _fail(label, "rejection_is_not_full_queue_distinct_tag")
            full = _eid(events, lambda e: e.get("kind")=="RETIRE" and e.get("mem_addr")=="4000001c" and
                        e.get("mem_rmask")=="f" and ((int(e.get("mem_rdata","0"),16)>>4)&7)==4 and
                        (int(e.get("mem_rdata","0"),16)&1)==0 and _cycle(e)<_cycle(overflow))
            if not full or any(e.get("status")!="0" or e.get("vectors_done")!="1" for e in popped):
                return _fail(label, "full_queue_readback_or_successful_drain_missing")
            return _ok(label, *submitted, full, overflow, *popped)
        if case == "4":
            label = "duplicate_unread_completion_tag_rejected"
            for rejected in (e for e in events if e.get("kind") == "SUBMIT_REJECT"):
                identity = (rejected.get("epoch"), rejected.get("tag"), rejected.get("asid"))
                matching = [e for e in events if
                            (e.get("epoch"), e.get("tag"), e.get("asid")) == identity]
                published = next((e for e in matching if e.get("kind") == "COMPLETE_PUBLISH" and
                                  _cycle(e) < _cycle(rejected)), None)
                consumed = next((e for e in matching if e.get("kind") == "COMPLETE" and
                                 _cycle(e) > _cycle(rejected) and e.get("status") == "0"), None)
                premature_pop = any(e.get("kind") == "COMPLETE" and published and
                                    _cycle(published) <= _cycle(e) <= _cycle(rejected) for e in matching)
                repeated_accept = any(e.get("kind") == "SUBMIT" and published and
                                      _cycle(published) < _cycle(e) <= _cycle(consumed or rejected)
                                      for e in matching)
                if published and consumed and not premature_pop and not repeated_accept:
                    return _ok(label, published, rejected, consumed)
            return _fail(label, "unread_tag_rejection_and_original_completion_not_observed")
        if case == "2":
            label = "completion_fifo_pressure"
            submitted = [e for e in events if e.get("kind") == "SUBMIT"]
            published = [e for e in events if e.get("kind") == "COMPLETE_PUBLISH"]
            popped = [e for e in events if e.get("kind") == "COMPLETE"]
            if len(submitted)!=5 or len(published)!=5 or len(popped)!=5:
                return _fail(label, "five_accepted_published_and_drained_jobs_required")
            identities = lambda records: [(e.get("epoch"),e.get("tag"),e.get("asid")) for e in records]
            if len(set(identities(submitted)))!=5 or identities(submitted)!=identities(published) or identities(submitted)!=identities(popped):
                return _fail(label, "completion_identity_or_order_mismatch")
            first_pop = popped[0]
            if _cycle(published[3])>=_cycle(first_pop) or _cycle(published[4])<=_cycle(first_pop):
                return _fail(label, "fifth_publication_not_stalled_until_drain")
            window = [e for e in events if e.get("epoch")==first_pop.get("epoch") and
                      _cycle(published[3])<_cycle(e)<_cycle(first_pop)]
            full = [e for e in window if e.get("kind")=="RETIRE" and e.get("mem_addr")=="4000001c" and
                    e.get("mem_rmask")=="f" and ((int(e.get("mem_rdata","0"),16)>>7)&7)==4 and
                    (int(e.get("mem_rdata","0"),16)&2)]
            front = [e for e in window if e.get("kind")=="RETIRE" and e.get("mem_addr")=="40000020" and
                     e.get("mem_rmask")=="f"]
            if len(full)<8 or len(front)<8 or len({e.get("mem_rdata") for e in front})!=1:
                return _fail(label, "full_fifo_busy_and_stable_front_not_observed")
            final_write = _eid(window, lambda e: e.get("kind")=="MEM_RSP" and e.get("write")=="1" and
                               e.get("committed")=="1" and e.get("error")=="0" and
                               e.get("tag")==submitted[-1].get("tag") and _cycle(e)<_cycle(full[-8]))
            if not final_write:
                return _fail(label, "fifth_job_output_not_committed_before_stable_retirement_stall")
            return _ok(label, *submitted, *published, *popped, final_write, full[0], full[-1], front[0], front[-1])
        if case == "3":
            # COMPLETE is the software-visible pop/read event. When a new
            # result is published on the same edge, the popped head is the
            # *previous* tag; requiring equal tags would reject legal FIFO
            # simultaneous push/pop behavior.
            pop = _pair(events, "COMPLETE_PUBLISH", "COMPLETE", lambda a, b:
                        a.get("tag") != b.get("tag") and a.get("cycle") == b.get("cycle"))
            return _ok("publish_pop_same_cycle", *pop) if pop else \
                _fail("publish_pop_same_cycle", "collision_not_observed")
        if case == "6":
            label = "inactive_bank_update_and_generation_rollover"
            submit = _eid(events, lambda e: e.get("kind") == "SUBMIT" and e.get("bank") == "0" and
                          e.get("generation") == "7")
            done = next((e for e in events if submit and e.get("kind") == "COMPLETE_PUBLISH" and
                         e.get("epoch") == submit.get("epoch") and e.get("tag") == submit.get("tag") and
                         _cycle(e) > _cycle(submit)), None)
            live = [e for e in events if submit and done and e.get("epoch") == submit.get("epoch") and
                    _cycle(submit) < _cycle(e) < _cycle(done)]
            wrap = _eid(live, lambda e: e.get("kind") == "APB" and e.get("write") == "1" and
                        e.get("addr") == "40001010" and e.get("wdata") == "0000ff07" and e.get("error") == "0")
            update = _eid(live, lambda e: wrap and _cycle(e)>_cycle(wrap) and
                          e.get("kind") == "ACCEL_CFG" and e.get("bank") == "1" and e.get("data") == "0000005a")
            zero = _eid(live, lambda e: update and _cycle(e)>_cycle(update) and
                        e.get("kind") == "APB" and e.get("write") == "1" and e.get("addr") == "40001010" and
                        e.get("wdata") == "00000007" and e.get("error") == "0")
            reads = []
            for write, value in ((wrap, "0000ff07"), (zero, "00000007")):
                reads.append(_eid(live, lambda e: write and _cycle(e)>_cycle(write) and
                                  e.get("kind") == "RETIRE" and e.get("mem_addr") == "40001010" and
                                  e.get("mem_rmask") == "f" and e.get("mem_rdata") == value))
            witnesses = (submit, wrap, reads[0], update, zero, reads[1], done)
            return _ok(label, *witnesses) if all(witnesses) else _fail(label, "live_free_bank_update_and_wrap_not_observed")
        if case == "5":
            submit = _eid(events, lambda e: e.get("kind") == "SUBMIT")
            cfg = _eid(events, lambda e: e.get("kind") == "APB" and e.get("addr") == "40001010" and e.get("write") == "1" and e.get("error") == "1")
            return _ok("referenced_bank_rewrite_rejected", submit, cfg) if submit and cfg else \
                _fail("referenced_bank_rewrite_rejected", "no_live_reference_write_error")

    if family == "translation_recovery":
        faults = [e for e in events if e.get("kind") == "XLATE_RSP" and _num(e, "fault")]
        comps = [e for e in events if e.get("kind") == "COMPLETE"]
        if name.endswith("fault_1"):
            label = "read_permission_denial"
            hit = next((e for e in faults if e.get("write") == "0" and e.get("fault") == "2"), None)
            comp = next((e for e in comps if hit and e.get("epoch")==hit.get("epoch") and e.get("tag")==hit.get("tag") and
                         e.get("status") == "2" and e.get("fault_stage")=="1" and e.get("vectors_done") == "0"), None)
            no_payload = not any(e.get("kind")=="MEM_REQ" for e in events)
            return _ok(label, hit, comp) if hit and comp and no_payload else _fail(label, "permission_fault_or_no_payload_containment_missing")
        if name.endswith("fault_2"):
            label = "write_permission_denial"
            hit = next((e for e in faults if e.get("write") == "1" and e.get("fault") == "2"), None)
            comp = next((e for e in comps if hit and e.get("epoch")==hit.get("epoch") and e.get("tag")==hit.get("tag") and
                         e.get("status") == "3" and e.get("fault_stage") == "3" and e.get("vectors_done")=="0"), None)
            no_output = not any(e.get("kind")=="MEM_REQ" and e.get("write")=="1" for e in events)
            return _ok(label, hit, comp) if hit and comp and no_output else _fail(label, "write_permission_fault_or_output_containment_missing")
        if name.endswith("fault_3"):
            label="cached_permission_downgrade_upgrade"
            expected=[("53","0","1"),("54","0","1"),("55","0","1"),
                      ("56","3","0"),("57","3","0"),("58","0","1")]
            if [(e.get("tag"),e.get("status"),e.get("vectors_done")) for e in comps]!=expected:
                return _fail(label,"six_permission_transition_completions_missing")
            witnesses=list(comps)
            for tag,write,iova,hit,fault in (("54","1","80004000","1","0"),
                                            ("55","0","80004000","0","0"),
                                            ("56","1","80004000","1","2"),
                                            ("57","1","80004000","1","2"),
                                            ("58","1","80004000","0","0")):
                response=_eid(events,lambda e:e.get("kind")=="XLATE_RSP" and e.get("epoch")==comps[0].get("epoch") and
                              e.get("tag")==tag and e.get("write")==write and e.get("iova")==iova and
                              e.get("tlb_hit")==hit and e.get("fault")==fault)
                if not response:return _fail(label,f"missing_permission_response_tag_{tag}")
                witnesses.append(response)
            for previous,next_tag in ((comps[1],"55"),(comps[4],"58")):
                submit=_eid(events,lambda e:e.get("kind")=="SUBMIT" and e.get("tag")==next_tag and
                            e.get("epoch")==previous.get("epoch") and _cycle(e)>_cycle(previous))
                invalidate=_eid(events,lambda e:submit and e.get("kind")=="TLB_INVALIDATE" and
                                e.get("epoch")==previous.get("epoch") and e.get("asid")==previous.get("asid") and
                                _cycle(previous)<_cycle(e)<_cycle(submit))
                if not invalidate:return _fail(label,"permission_transition_invalidation_missing")
                witnesses.extend((invalidate,submit))
            for previous,next_done,value in ((comps[0],comps[1],"040010c3"),(comps[3],comps[4],"040010cf")):
                pte=_eid(events,lambda e:e.get("kind")=="PTE_WRITE" and e.get("addr")=="30001010" and
                         e.get("epoch")==previous.get("epoch") and e.get("data","")[-8:]==value and
                         _cycle(previous)<_cycle(e)<_cycle(next_done))
                if not pte:return _fail(label,"permission_pte_update_missing")
                if any(e.get("kind")=="TLB_INVALIDATE" and e.get("epoch")==pte.get("epoch") and
                       _cycle(pte)<_cycle(e)<_cycle(next_done) for e in events):
                    return _fail(label,"stale_permission_phase_invalidated_prematurely")
                witnesses.append(pte)
            return _ok(label,*witnesses)
        if name.endswith("fault_4"):
            label="same_iova_asid_isolation"
            if [(e.get("tag"),e.get("asid"),e.get("status"),e.get("vectors_done")) for e in comps]!=[
                    ("53","1","0","1"),("54","2","0","1"),("55","1","0","1")]:
                return _fail(label,"three_context_specific_completions_missing")
            witnesses=list(comps)
            for tag,asid,pa,hit in (("53","1","10001000","0"),("54","2","10002000","0"),("55","1","10001000","1")):
                response=_eid(events,lambda e:e.get("kind")=="XLATE_RSP" and e.get("tag")==tag and
                              e.get("asid")==asid and e.get("iova")=="80001000" and e.get("write")=="0" and
                              e.get("paddr")==pa and e.get("tlb_hit")==hit and e.get("fault")=="0" and
                              e.get("epoch")==comps[0].get("epoch"))
                if not response:return _fail(label,f"missing_isolated_mapping_tag_{tag}")
                witnesses.append(response)
            repair=_eid(events,lambda e:e.get("kind")=="PTE_WRITE" and e.get("addr")=="30001004" and
                        e.get("data")=="040008cf00000000" and e.get("epoch")==comps[0].get("epoch") and
                        _cycle(comps[0])<_cycle(e)<_cycle(comps[1]))
            if not repair or any(e.get("kind")=="TLB_INVALIDATE" for e in events):
                return _fail(label,"noninvalidated_context_remap_missing")
            witnesses.append(repair)
            return _ok(label,*witnesses)
        if name.endswith("case_6"):
            failed = next((e for e in comps if e.get("status") == "5" and e.get("vectors_done") == "1"), None)
            same = lambda e: failed and e.get("epoch")==failed.get("epoch") and e.get("tag")==failed.get("tag") and e.get("asid")==failed.get("asid")
            retried = next((e for e in comps if same(e) and e.get("status") == "0" and e.get("vectors_done") == "2" and _cycle(e) > _cycle(failed)), None)
            repair = _eid(events, lambda e: failed and retried and e.get("kind")=="PTE_WRITE" and
                          e.get("epoch")==failed.get("epoch") and e.get("addr")=="30001014" and
                          e.get("data")=="040020cf00000000" and _cycle(failed)<_cycle(e)<_cycle(retried))
            invalidate = _eid(events, lambda e: repair and e.get("kind")=="TLB_INVALIDATE" and
                              e.get("epoch")==failed.get("epoch") and e.get("asid")==failed.get("asid") and
                              _cycle(repair)<_cycle(e)<_cycle(retried))
            submit = _eid(events, lambda e: invalidate and e.get("kind")=="SUBMIT" and same(e) and
                          _cycle(invalidate)<_cycle(e)<_cycle(retried))
            ack = _eid(events, lambda e: invalidate and submit and e.get("kind")=="RETIRE" and
                       e.get("epoch")==failed.get("epoch") and e.get("mem_addr")=="40002204" and
                       e.get("mem_rmask")=="f" and (int(e.get("mem_rdata","0"),16)&1)==0 and
                       _cycle(invalidate)<_cycle(e)<_cycle(submit))
            witnesses=(failed,repair,invalidate,ack,submit,retried)
            return _ok("partial_output_remap_retry", *witnesses) if all(witnesses) else _fail("partial_output_remap_retry", "correlated_prefix_repair_invalidation_ack_retry_missing")
        if name.endswith("input_bus_error"):
            label="targeted_and_global_remap_invalidation"
            if [(e.get("tag"),e.get("status"),e.get("vectors_done")) for e in comps]!=[
                    (str(tag),"0","1") for tag in range(53,58)]:
                return _fail(label,"five_successful_mapping_phases_missing")
            epoch=comps[0].get("epoch")
            if any(e.get("epoch")!=epoch or e.get("asid")!="1" for e in comps):
                return _fail(label,"remap_context_or_epoch_changed")
            witnesses=list(comps)
            for tag,pa,hit in ((53,"10001000","0"),(54,"10001000","1"),
                               (55,"10002000","0"),(56,"10002000","1"),(57,"10001000","0")):
                response=_eid(events,lambda e:e.get("kind")=="XLATE_RSP" and
                              e.get("tag")==str(tag) and e.get("asid")=="1" and
                              e.get("epoch")==epoch and
                              e.get("iova")=="80001000" and e.get("write")=="0" and
                              e.get("paddr")==pa and e.get("tlb_hit")==hit and e.get("fault")=="0")
                if not response:return _fail(label,f"mapping_phase_{tag}_missing")
                witnesses.append(response)
            for before,after,data,all_flag in ((1,2,"040008cf00000000","0"),
                                               (3,4,"040004cf00000000","1")):
                repair=_eid(events,lambda e:e.get("kind")=="PTE_WRITE" and
                            e.get("epoch")==epoch and
                            e.get("addr")=="30001004" and e.get("data")==data and
                            _cycle(comps[before-1])<_cycle(e)<_cycle(comps[before]))
                inv=_eid(events,lambda e:e.get("kind")=="TLB_INVALIDATE" and
                         e.get("epoch")==epoch and
                         e.get("all")==all_flag and (all_flag=="1" or e.get("asid")=="1") and
                         _cycle(comps[before])<_cycle(e)<_cycle(comps[after]))
                ack=_eid(events,lambda e:inv and e.get("kind")=="RETIRE" and
                         e.get("epoch")==epoch and
                         e.get("mem_addr")=="40002204" and e.get("mem_rmask")=="f" and
                         (int(e.get("mem_rdata","0"),16)&1)==0 and
                         _cycle(inv)<_cycle(e)<_cycle(comps[after]))
                if not all((repair,inv,ack)):return _fail(label,"repair_invalidate_ack_sequence_missing")
                witnesses.extend((repair,inv,ack))
            return _ok(label,*witnesses)

    if family == "interrupts":
        if case == "3":
            both = _eid(events, lambda e: e.get("kind") == "RETIRE" and e.get("mem_addr") == "40002000" and
                        e.get("mem_rmask") == "f" and (int(e.get("mem_rdata","0"),16)&3)==3)
            enabled = next((e for e in events if both and e.get("kind") == "APB" and e.get("addr") == "40002008" and
                            e.get("write") == "1" and e.get("wdata") == "00000003" and _cycle(e)>_cycle(both)),None)
            take = next((e for e in events if enabled and e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                         e.get("mcause") == "8000000b" and _cycle(e)>_cycle(enabled)),None)
            ack = next((e for e in events if take and e.get("kind") == "IRQ_ACK" and e.get("mask") == "3" and
                        _cycle(e)>_cycle(take)),None)
            return _ok("both_device_sources_pending",both,enabled,take,ack) if all((both,enabled,take,ack)) else \
                _fail("both_device_sources_pending","two_pending_device_sources_and_handler_ack_missing")
        if case == "4":
            external = _eid(events, lambda e: e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                            e.get("mcause") == "8000000b" and e.get("irq_timer_level") == "1")
            timer = next((e for e in events if external and e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                          e.get("mcause") == "80000007" and e.get("epoch") == external.get("epoch") and
                          _cycle(e)>_cycle(external)), None)
            between = [e for e in events if external and timer and e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                       _cycle(external)<_cycle(e)<_cycle(timer)]
            return _ok("external_before_timer_priority", external, timer) if external and timer and not between else \
                _fail("external_before_timer_priority", "simultaneous_pending_sources_or_priority_order_missing")
        if case == "6":
            pending = _eid(events, lambda e: e.get("kind") == "IRQ_SET" and e.get("muldiv_busy") == "1")
            divide = next((e for e in events if pending and e.get("kind") == "RETIRE" and
                           (int(e.get("insn","0"),16)&0xfe00707f)==0x02004033 and
                           e.get("epoch") == pending.get("epoch") and _cycle(e)>_cycle(pending)), None)
            take = next((e for e in events if divide and e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                         e.get("epoch") == divide.get("epoch") and _cycle(e)>_cycle(divide) and
                         e.get("mepc") == divide.get("next_pc")), None)
            premature = any(e.get("kind") == "RETIRE" and e.get("intr") == "1" and pending and divide and
                            _cycle(pending)<=_cycle(e)<=_cycle(divide) for e in events)
            return _ok("interrupt_delayed_by_apb_or_m_retirement", pending, divide, take) if all((pending,divide,take)) and not premature else \
                _fail("interrupt_delayed_by_apb_or_m_retirement", "irq_during_div_then_precise_post_retirement_entry_missing")
        if case == "2":
            ack = _eid(events, lambda e: e.get("kind") == "IRQ_ACK" and
                       e.get("completion_published") == "1" and (_num(e,"mask") & 2) != 0)
            publish = next((e for e in events if ack and e.get("kind") == "COMPLETE_PUBLISH" and
                            e.get("epoch") == ack.get("epoch") and e.get("cycle") == ack.get("cycle")), None)
            retained = next((e for e in events if ack and e.get("kind") == "RETIRE" and
                            e.get("mem_addr") == "40002000" and e.get("mem_rmask") == "f" and
                            (int(e.get("mem_rdata","0"),16)&2) != 0 and _cycle(e)>_cycle(ack)), None)
            return _ok("simultaneous_irq_event_and_w1c", publish, ack, retained) if all((publish,ack,retained)) else \
                _fail("simultaneous_irq_event_and_w1c", "publication_ack_coincidence_or_retained_pending_missing")
        if case == "1":
            raw = _eid(events, lambda e: e.get("kind") == "RETIRE" and
                       e.get("mem_addr") == "40002000" and e.get("mem_rmask") == "f" and
                       (int(e.get("mem_rdata", "0"), 16) & 2) != 0 and e.get("irq_level") == "0")
            masked = next((e for e in events if raw and e.get("kind") == "RETIRE" and
                           e.get("mem_addr") == "40002004" and e.get("mem_rmask") == "f" and
                           int(e.get("mem_rdata", "0"), 16) == 0 and _cycle(e) >= _cycle(raw)), None)
            enable = next((e for e in events if masked and e.get("kind") == "APB" and
                           e.get("addr") == "40002008" and e.get("write") == "1" and
                           int(e.get("wdata", "0"), 16) == 2 and _cycle(e) > _cycle(masked)), None)
            take = next((e for e in events if enable and e.get("kind") == "RETIRE" and
                         e.get("intr") == "1" and e.get("epoch") == enable.get("epoch") and
                         _cycle(e) > _cycle(enable)), None)
            ack = next((e for e in events if take and e.get("kind") == "APB" and
                        e.get("addr") == "4000200c" and e.get("write") == "1" and
                        _cycle(e) > _cycle(take)), None)
            return _ok("masked_completion_then_enable_and_ack", raw, masked, enable, take, ack) if all((raw, masked, enable, take, ack)) else \
                _fail("masked_completion_then_enable_and_ack", "masked_pending_enable_take_ack_sequence_missing")
        if case == "5":
            wfi = _eid(events, lambda e: e.get("kind") == "RETIRE" and e.get("insn") == "10500073")
            publish = next((e for e in events if wfi and e.get("kind") == "COMPLETE_PUBLISH" and
                            e.get("epoch") == wfi.get("epoch") and _cycle(e) > _cycle(wfi)), None)
            take = next((e for e in events if publish and e.get("kind") == "RETIRE" and
                         e.get("intr") == "1" and e.get("epoch") == publish.get("epoch") and
                         _cycle(e) >= _cycle(publish)), None)
            return _ok("completion_at_wfi_boundary", wfi, publish, take) if all((wfi, publish, take)) else \
                _fail("completion_at_wfi_boundary", "wfi_completion_interrupt_sequence_missing")
        if row.get("completion_mode") == "irq":
            irq = _eid(events, lambda e: e.get("kind") == "IRQ_SET" and _num(e, "pending") != 0 and _num(e, "enable") != 0)
            take = next((e for e in events if irq and e.get("kind") == "RETIRE" and e.get("intr") == "1" and
                         e.get("epoch") == irq.get("epoch") and _cycle(e) >= _cycle(irq)), None)
            return _ok("enabled_completion_irq_taken", irq, take) if irq and take else _fail("enabled_completion_irq_taken", "irq_not_taken")
        publish = _eid(events, lambda e: e.get("kind") == "COMPLETE_PUBLISH")
        read = next((e for e in events if publish and e.get("kind") == "AXI_AR" and
                     e.get("epoch") == publish.get("epoch") and _cycle(e) > _cycle(publish)), None)
        no_take = not any(e.get("kind") == "RETIRE" and e.get("intr") == "1" for e in events)
        return _ok("poll_completion_without_irq_retirement", publish, read) if publish and read and no_take else _fail("poll_completion_without_irq_retirement", "polling_or_masking_not_observed")

    if family == "cache_ownership":
        if case == "4":
            submit = _eid(events,lambda e:e.get("kind")=="SUBMIT" and e.get("input_iova")=="8000101c" and
                          e.get("output_iova")=="8000401c")
            reads = [e for e in events if submit and e.get("kind")=="MEM_REQ" and e.get("write")=="0" and
                     e.get("epoch")==submit.get("epoch") and e.get("tag")==submit.get("tag")]
            writes = [e for e in events if submit and e.get("kind")=="MEM_RSP" and e.get("write")=="1" and
                      e.get("committed")=="1" and e.get("tag")==submit.get("tag")]
            pad_in = _eid(events,lambda e:e.get("kind")=="RETIRE" and e.get("mem_addr")=="10001018" and
                          e.get("mem_rmask")=="f" and e.get("mem_rdata")=="62f19a37" and submit and _cycle(e)>_cycle(submit))
            pad_out = _eid(events,lambda e:e.get("kind")=="RETIRE" and e.get("mem_addr")=="10004018" and
                           e.get("mem_rmask")=="f" and e.get("mem_rdata")=="85c3d2e1" and submit and _cycle(e)>_cycle(submit))
            read_lines = {int(e.get("addr","0"),16)>>5 for e in reads}
            write_lines = {int(e.get("addr","0"),16)>>5 for e in writes}
            return _ok("line_boundary_and_shared_line_ownership",submit,reads[0] if reads else None,writes[-1] if writes else None,pad_in,pad_out) if submit and len(read_lines)>=2 and len(write_lines)>=2 and pad_in and pad_out else \
                _fail("line_boundary_and_shared_line_ownership","cross_line_dma_and_preserved_shared_line_padding_missing")
        if case == "5":
            failed = _eid(events, lambda e: e.get("kind") == "MAINT_DONE" and e.get("error") == "1")
            bus_error = _eid(events, lambda e: e.get("kind") == "AXI_B" and e.get("resp") == "2" and
                             failed and _cycle(e)<_cycle(failed))
            trap = next((e for e in events if failed and e.get("kind") == "RETIRE" and e.get("trap") == "1" and
                         e.get("mcause") == "00000007" and e.get("mem_addr") == "40002104" and
                         _cycle(e)>=_cycle(failed)),None)
            retry = next((e for e in events if trap and e.get("kind") == "MAINT_START" and _cycle(e)>_cycle(trap)),None)
            recovered = next((e for e in events if retry and e.get("kind") == "MAINT_DONE" and e.get("error") == "0" and
                              _cycle(e)>_cycle(retry)),None)
            submit = next((e for e in events if recovered and e.get("kind") == "SUBMIT" and _cycle(e)>_cycle(recovered)),None)
            premature = any(e.get("kind") == "SUBMIT" and recovered and _cycle(e)<_cycle(recovered) for e in events)
            return _ok("maintenance_error_recovery",bus_error,failed,trap,retry,recovered,submit) if all((bus_error,failed,trap,retry,recovered,submit)) and not premature else \
                _fail("maintenance_error_recovery","failed_writeback_precise_trap_retry_and_handoff_missing")
        start = _eid(events, lambda e: e.get("kind") == "MAINT_START")
        done = next((e for e in events if start and e.get("kind") == "MAINT_DONE" and
                     e.get("epoch") == start.get("epoch") and e.get("cmd") == start.get("cmd") and _cycle(e) > _cycle(start)), None)
        if not (start and done and str(row.get("cache")) == "1"):
            return _fail("cached_maintenance_handoff", "maintenance_lifecycle_or_cache_mode_missing")
        if case == "1":
            cpu_write = _eid(events, lambda e: e.get("kind") == "APB" and e.get("addr") == "10001000" and e.get("write") == "1" and _cycle(e) < _cycle(start))
            flush = next((e for e in events if e.get("kind") == "AXI_WRITE" and e.get("master") == "0" and
                          e.get("addr") == "10001000" and start and done and
                          _cycle(start) < _cycle(e) < _cycle(done)), None)
            submit = next((e for e in events if e.get("kind") == "SUBMIT" and done and _cycle(e) > _cycle(done)), None)
            return _ok("dirty_input_flush_before_submit", cpu_write, start, flush, done, submit) if all((cpu_write, flush, submit)) else \
                _fail("dirty_input_flush_before_submit", "dirty_input_writeback_or_handoff_order_missing")
        if case == "2":
            output_init = _eid(events, lambda e: e.get("kind") == "APB" and e.get("addr") == "10004000" and e.get("write") == "1" and _cycle(e) < _cycle(start))
            publish = _eid(events, lambda e: e.get("kind") == "COMPLETE_PUBLISH" and e.get("status") == "0")
            invalidate = next((e for e in events if publish and e.get("kind") == "MAINT_START" and e.get("cmd") == "1" and _cycle(e) > _cycle(publish)), None)
            invalidate_done = next((e for e in events if invalidate and e.get("kind") == "MAINT_DONE" and e.get("cmd") == "1" and e.get("error") == "0" and _cycle(e) > _cycle(invalidate)), None)
            cpu_read = next((e for e in events if invalidate_done and e.get("kind") == "APB" and e.get("addr") == "10004000" and e.get("write") == "0" and _cycle(e) > _cycle(invalidate_done)), None)
            return _ok("stale_output_invalidated_after_completion", output_init, publish, invalidate, invalidate_done, cpu_read) if all((output_init, publish, invalidate, invalidate_done, cpu_read)) else \
                _fail("stale_output_invalidated_after_completion", "output_invalidate_then_read_chain_missing")
        if case == "3":
            dest_write = _eid(events, lambda e: e.get("kind") == "APB" and e.get("addr") == "10004000" and e.get("write") == "1" and _cycle(e) < _cycle(start))
            clean = next((e for e in events if e.get("kind") == "AXI_WRITE" and e.get("master") == "0" and
                          e.get("addr") == "10004000" and start and done and
                          _cycle(start) < _cycle(e) < _cycle(done)), None)
            submit = next((e for e in events if e.get("kind") == "SUBMIT" and done and _cycle(e) > _cycle(done)), None)
            committed = next((e for e in events if submit and e.get("kind") == "MEM_RSP" and e.get("write") == "1" and
                              e.get("committed") == "1" and e.get("addr") == "10004000" and _cycle(e) > _cycle(submit)), None)
            unsafe = any(e.get("kind") == "AXI_WRITE" and e.get("master") == "0" and e.get("addr") == "10004000" and
                         submit and committed and _cycle(submit) < _cycle(e) < _cycle(committed) for e in events)
            return _ok("dirty_destination_protected", dest_write, start, clean, done, submit, committed) if all((dest_write, clean, submit, committed)) and not unsafe else \
                _fail("dirty_destination_protected", "destination_not_cleaned_or_cpu_writeback_overlapped_device")
        if case == "6":
            for access in (e for e in events if e.get("kind") == "OWNED_CPU_ACCESS"):
                submit = next((e for e in reversed(events) if e.get("kind") == "SUBMIT" and
                               e.get("epoch") == access.get("epoch") and e.get("tag") == access.get("active_tag") and
                               _cycle(e)<_cycle(access)),None)
                if submit is None:
                    continue
                ranges,mappings = descriptor_physical_ranges(submit,events)
                if ranges is None or physical_access_owned(int(access.get("addr","0"),16),ranges):
                    continue
                completed = any(e.get("kind") == "COMPLETE_PUBLISH" and e.get("epoch") == submit.get("epoch") and
                                e.get("tag") == submit.get("tag") and _cycle(submit)<_cycle(e)<=_cycle(access) for e in events)
                if not completed:
                    return _ok("unrelated_cpu_buffer_access_permitted",start,submit,*mappings,access,done)
            return _fail("unrelated_cpu_buffer_access_permitted","cpu_access_outside_translated_live_owned_lines_missing")
        if case in ("2", "5"):
            intr = _eid(events, lambda e: e.get("kind") == "RETIRE" and e.get("intr") == "1")
            return _ok("cached_handoff_with_completion_irq", start, intr, done) if intr else _fail("cached_handoff_with_completion_irq", "no_interrupt_retirement")
        return _ok("cached_maintenance_handoff", start, done)

    if family == "combined_services":
        if case == "3":
            inject = _eid(events, lambda e: e.get("kind") == "APB" and
                          e.get("addr") == "50000080" and e.get("write") == "1" and
                          int(e.get("wdata", "0"), 16) == 5)
            chip_error = next((e for e in events if inject and e.get("kind") == "CHIPLET_EVT" and
                               e.get("error") == "1" and _cycle(e) > _cycle(inject)), None)
            chip_status = next((e for e in events if chip_error and e.get("kind") == "RETIRE" and
                                e.get("mem_addr") == "5000003c" and e.get("mem_rmask") == "f" and
                                (int(e.get("mem_rdata", "0"), 16) & 15) == 6 and
                                _cycle(e) > _cycle(chip_error)), None)
            accel_done = next((e for e in events if chip_error and e.get("kind") == "COMPLETE_PUBLISH" and
                               e.get("status") == "0"), None)
            return _ok("chiplet_failure_int8_success", inject, chip_error, chip_status, accel_done) if all((inject, chip_error, chip_status, accel_done)) else \
                _fail("chiplet_failure_int8_success", "chiplet_parity_error_or_independent_int8_success_missing")
        if case == "4":
            fault = _eid(events, lambda e: e.get("kind") == "XLATE_RSP" and
                         e.get("write") == "1" and _num(e, "fault") != 0)
            failed = next((e for e in events if fault and e.get("kind") == "COMPLETE_PUBLISH" and
                           e.get("epoch") == fault.get("epoch") and e.get("status") == "3" and
                           e.get("vectors_done") == "0" and _cycle(e) > _cycle(fault)), None)
            chip = next((e for e in events if failed and e.get("kind") == "CHIPLET_EVT" and
                         e.get("epoch") == failed.get("epoch") and e.get("done") == "1" and
                         e.get("error") == "0"), None)
            cmd = _eid(events, lambda e: e.get("kind") == "ACCEL_CMD" and fault and
                       e.get("epoch") == fault.get("epoch") and _cycle(e) < _cycle(fault))
            if fault and failed and chip and cmd:
                return _ok("int8_failure_chiplet_success", cmd, fault, failed, chip)
            return _fail("int8_failure_chiplet_success", "precise_int8_fault_or_independent_chiplet_success_missing")
        if case == "6":
            reset = _eid(events, lambda e: e.get("kind") == "RESET_ASSERT" and
                         _num(e, "chip_busy") == 1 and _num(e, "dma_busy") == 1)
            release = next((e for e in events if reset and e.get("kind") == "RESET_RELEASE" and
                            e.get("epoch") == reset.get("epoch") and _cycle(e) > _cycle(reset)), None)
            complete = next((e for e in events if release and e.get("kind") == "COMPLETE_PUBLISH" and
                             e.get("epoch") == release.get("epoch") and e.get("status") == "0" and
                             _cycle(e) > _cycle(release)), None)
            chip = next((e for e in events if release and e.get("kind") == "CHIPLET_EVT" and
                         e.get("epoch") == release.get("epoch") and e.get("done") == "1" and
                         _cycle(e) > _cycle(release)), None)
            done = next((e for e in events if complete and chip and e.get("kind") == "FIRMWARE_DONE" and
                         e.get("epoch") == release.get("epoch") and _cycle(e) > max(_cycle(complete), _cycle(chip))), None)
            return _ok("coordinated_reset_with_both_services_active", reset, release, complete, chip, done) if all((reset, release, complete, chip, done)) else \
                _fail("coordinated_reset_with_both_services_active", "both_busy_reset_and_clean_reboot_missing")
        start = _eid(events, lambda e: e.get("kind") == "CHIPLET_EVT" and e.get("busy") == "1")
        accel = next((e for e in events if start and e.get("kind") in ("ACCEL_CMD", "ACCEL_IN", "ACCEL_OUT") and
                      e.get("epoch") == start.get("epoch") and _cycle(e) >= _cycle(start)), None)
        finish = next((e for e in events if start and e.get("kind") == "CHIPLET_EVT" and
                       e.get("busy") == "0" and e.get("done") == "1" and e.get("epoch") == start.get("epoch") and
                       _cycle(e) >= _cycle(accel or start)), None)
        if not (start and accel and finish):
            return _fail("measured_aes_int8_overlap", "no_same_epoch_service_overlap_and_completion")
        if case == "2":
            accel_done = next((e for e in events if e.get("kind") == "COMPLETE_PUBLISH" and
                               e.get("epoch") == finish.get("epoch") and e.get("status") == "0" and
                               _cycle(e) > _cycle(finish)), None)
            chip_pop = next((e for e in events if accel_done and e.get("kind") == "APB" and
                             e.get("addr") == "50000044" and e.get("write") == "1" and
                             _cycle(e) > _cycle(accel_done)), None)
            return _ok("independent_service_completion_order", start, accel, finish, accel_done, chip_pop) if accel_done and chip_pop else \
                _fail("independent_service_completion_order", "chiplet_first_completion_and_independent_pop_missing")
        if case == "5":
            writes = [e for e in events if e.get("kind") == "APB" and e.get("write") == "1" and e.get("addr") == "500000f0"]
            sleep_write = writes[0] if len(writes) >= 2 else None
            resume_write = writes[1] if len(writes) >= 2 and _cycle(writes[1]) > _cycle(writes[0]) else None
            if not (sleep_write and resume_write):
                return _fail("chiplet_sleep_resume_during_overlap", "sleep_or_resume_mmio_not_observed")
            return _ok("chiplet_sleep_resume_during_overlap", start, accel, sleep_write, resume_write, finish)
        return _ok("measured_aes_int8_overlap", start, accel, finish)

    if family == "reset_transport":
        reset = _eid(events, lambda e: e.get("kind") == "RESET_ASSERT")
        release = next((e for e in events if reset and e.get("kind") == "RESET_RELEASE" and
                        e.get("epoch") == reset.get("epoch") and _cycle(e) > _cycle(reset)), None)
        phase = row.get("requested_reset_phase", "")
        phase_witnesses=[]
        if phase in ("accepted_output_write","completion_irq","maintenance_invalidation","prolonged_backpressure"):
            from reset_evidence import phase_reached
            if not phase_reached(events,phase):
                return _fail(f"reset_during_{phase}_recovery","requested_owned_phase_not_present_at_reset")
            witness_kind={"accepted_output_write":"DMA_AXI_AW","completion_irq":"RESET_IRQ_SNAPSHOT",
                          "maintenance_invalidation":"MAINT_START","prolonged_backpressure":"APB_WAIT"}[phase]
            candidates=[e for e in events if e.get("kind")==witness_kind and
                        _cycle(e)<=_cycle(reset)]
            phase_witnesses=candidates[-1:]
        phase_fields = {"ptw_req": ("ptw_pending",), "mem_req": ("mem_pending",),
                        "accepted_output_write": ("mem_pending",),
                        "completion_irq": ("completion_pending",),
                        "maintenance_invalidation": ("maint_active",),
                        "prolonged_backpressure": ("host_aw_pending",),
                        "mem_rsp": ("mem_pending",), "apb_wait": ("apb_active",),
                        "completion": ("completion_pending",), "host_w_wait": ("host_aw_pending",)}
        fields = phase_fields.get(phase, ())
        if not (reset and release and fields and any(_num(reset, field) for field in fields)):
            return _fail("phase_specific_reset_cancels_owned_work", "requested_reset_owner_not_present")
        recovered = next((e for e in events if e.get("kind") == "FIRMWARE_DONE" and
                          e.get("epoch") == release.get("epoch") and _cycle(e) > _cycle(release)), None)
        label="prolonged_backpressure_drain_or_reset" if phase=="prolonged_backpressure" else f"reset_during_{phase}_recovery"
        return _ok(label, *phase_witnesses, reset, release, recovered) if recovered else \
            _fail(f"reset_during_{phase}_recovery", "no_post_reset_firmware_completion")

    return _fail("unknown_intent", "no_qualifier_for_scenario")
