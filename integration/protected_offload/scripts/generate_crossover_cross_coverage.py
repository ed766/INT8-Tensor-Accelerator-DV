#!/usr/bin/env python3
"""Build correlation-keyed crossover coverage from passing RTL traces."""
from __future__ import annotations
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
sys.path.insert(0, str(Path(__file__).parent))
from check_crossover_trace import events as load_events  # noqa: E402
from ownership_ranges import descriptor_physical_ranges, physical_access_owned  # noqa: E402
from stimulus_provenance import witness_implementation, cross_generator_hash  # noqa: E402

OUT = REPORTS / "compute_crossover_cross_coverage.csv"
MANIFEST = ROOT / "integration/protected_offload/coverage/compute_crossover_manifest.json"
GENERATOR = Path(__file__)
MANIFEST_DATA = json.loads(MANIFEST.read_text())
REQUIRED_KEYS = {(family, bin_name)
                 for family, bins in MANIFEST_DATA.get("required_cross_bins", {}).items()
                 for bin_name in bins}


def num(event: dict[str, str], field: str, default: int = 0) -> int:
    # Observer architectural payloads are hexadecimal even when their text
    # contains only digits; counters and indices are decimal.
    if field in {"pc", "insn", "rd_data", "rs1_data", "rs2_data", "mem_addr",
                 "mem_rdata", "mem_wdata", "addr", "paddr", "iova"}:
        try:
            return int(event.get(field, ""), 16)
        except (TypeError, ValueError):
            return default
    try:
        return int(event.get(field, str(default)), 0)
    except (TypeError, ValueError):
        try:
            # Fixed-width observer payloads (PC, instruction, operands, and
            # addresses) are emitted as zero-padded hexadecimal without 0x.
            return int(event.get(field, ""), 16)
        except (TypeError, ValueError):
            return default


def event_key(event: dict[str, str], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(event.get(field, "") for field in ("epoch", *fields))


def m_instruction(event: dict[str, str]) -> str | None:
    try:
        insn = int(event.get("insn", "0"), 16)
    except ValueError:
        return None
    if (insn & 0x7f) != 0x33 or ((insn >> 25) & 0x7f) != 1:
        return None
    funct3 = (insn >> 12) & 7
    return ("MUL", "MULH", "MULHSU", "MULHU", "DIV", "DIVU", "REM", "REMU")[funct3]


def collect_m_dependency_cross(retires: list[dict[str, str]]) -> list[tuple[str, str, list[dict[str, str]], str]]:
    found = []
    for prior, consumer in zip(retires, retires[1:]):
        if not m_instruction(prior) or num(prior, "rd_addr") == 0 or prior.get("epoch") != consumer.get("epoch"):
            continue
        rd = str(num(prior, "rd_addr"))
        insn = num(consumer, "insn")
        opcode = insn & 0x7f
        if opcode == 0x03 and consumer.get("rs1_addr") == rd and \
                num(consumer, "mem_addr") == num(prior, "rd_data"):
            found.append(("m_result_x_consumer_dependency", "m_result_to_load_address",
                          [prior, consumer], "M result is consumed as the following load effective address"))
        elif opcode == 0x23 and consumer.get("rs2_addr") == rd and \
                num(consumer, "mem_wdata") == num(prior, "rd_data"):
            found.append(("m_result_x_consumer_dependency", "m_result_to_store_data",
                          [prior, consumer], "M result is consumed as the following store data"))
        elif opcode == 0x63 and rd in (consumer.get("rs1_addr"), consumer.get("rs2_addr")):
            found.append(("m_result_x_consumer_dependency", "m_result_to_branch",
                          [prior, consumer], "M destination is an operand of the following branch"))
    for load, arithmetic, store in zip(retires, retires[1:], retires[2:]):
        if (num(load, "insn") & 0x7f) == 0x03 and m_instruction(arithmetic) and \
                (num(store, "insn") & 0x7f) == 0x23 and \
                load.get("epoch") == arithmetic.get("epoch") == store.get("epoch") and \
                load.get("rd_addr") not in (None, "0") and \
                load.get("rd_addr") in (arithmetic.get("rs1_addr"), arithmetic.get("rs2_addr")) and \
                arithmetic.get("rd_addr") not in (None, "0") and \
                arithmetic.get("rd_addr") == store.get("rs2_addr") and \
                num(arithmetic, "rd_data") == num(store, "mem_wdata"):
            found.append(("m_result_x_consumer_dependency", "load_m_store_dependency",
                          [load, arithmetic, store], "loaded value feeds M arithmetic and that result is stored"))
    return found


def collect_reset_owner_cross(ev: list[dict[str, str]]) -> list[tuple[str, str, list[dict[str, str]], str]]:
    found = []
    owner_fields = (
        ("ptw_request_pending", "ptw_pending"),
        ("payload_request_pending", "mem_pending"),
        ("payload_response_pending", "mem_response_valid"),
        ("apb_wait_pending", "apb_active"),
        ("completion_pending", "completion_pending"),
        ("host_aw_waiting_w", "host_aw_pending"),
        ("muldiv_result_pending", "muldiv_result_valid"),
    )
    for reset in (e for e in ev if e.get("kind") == "RESET_ASSERT"):
        for label, field in owner_fields:
            if num(reset, field):
                found.append(("reset_phase_x_owner_type", label, [reset],
                              f"RESET_ASSERT observer snapshot records {field}=1"))
    return found


def collect_error_prefix_cross(ev: list[dict[str, str]]) -> list[tuple[str, str, list[dict[str, str]], str]]:
    found = []
    completions = [e for e in ev if e.get("kind") == "COMPLETE"]
    translations = [e for e in ev if e.get("kind") == "XLATE_RSP" and num(e, "fault")]
    for completion in completions:
        status, stage, prefix = num(completion, "status"), num(completion, "fault_stage"), num(completion, "vectors_done")
        if status == 2 and stage == 1 and prefix == 0:
            found.append(("error_stage_x_committed_prefix_x_recovery", "input_translation:0:contained",
                          [completion], "input translation failure reports a zero committed prefix"))
        elif status == 3 and stage == 3 and prefix == 0:
            fault = next((e for e in translations if e.get("epoch") == completion.get("epoch") and
                          e.get("tag") == completion.get("tag") and num(e, "write") and num(e, "fault")), None)
            if fault and num(fault, "fault") == 1:
                found.append(("error_stage_x_committed_prefix_x_recovery", "output_page:0:contained",
                              [fault, completion], "write page fault matched to zero-prefix completion"))
            elif fault and num(fault, "fault") == 2:
                found.append(("error_stage_x_committed_prefix_x_recovery", "output_permission:0:contained",
                              [fault, completion], "write permission fault matched to zero-prefix completion"))
        elif status == 4 and stage == 2 and prefix == 0:
            memory_error = next((e for e in ev if e.get("kind") == "MEM_RSP" and
                                 e.get("epoch") == completion.get("epoch") and
                                 e.get("tag") == completion.get("tag") and
                                 not num(e, "write") and num(e, "error")), None)
            if memory_error:
                found.append(("error_stage_x_committed_prefix_x_recovery", "input_memory:0:contained",
                              [memory_error, completion], "failed input read matched to a zero-prefix completion"))
        elif status == 5 and stage == 4 and prefix == 1:
            retry = next((e for e in completions if e.get("epoch") == completion.get("epoch") and
                          e.get("tag") == completion.get("tag") and num(e, "cycle") > num(completion, "cycle") and
                          num(e, "status") == 0 and num(e, "vectors_done") >= 2), None)
            if retry:
                found.append(("error_stage_x_committed_prefix_x_recovery", "partial_output:1:retry_success",
                              [completion, retry], "one committed output precedes successful retry"))
    return found


def collect(trace_path: Path) -> list[tuple[str, str, list[dict[str, str]], str]]:
    ev = load_events(trace_path)
    found: list[tuple[str, str, list[dict[str, str]], str]] = []
    submits = [e for e in ev if e.get("kind") == "SUBMIT"]
    completes = [e for e in ev if e.get("kind") == "COMPLETE"]
    retires = [e for e in ev if e.get("kind") == "RETIRE"]

    found.extend(collect_m_dependency_cross(retires))
    found.extend(collect_reset_owner_cross(ev))
    found.extend(collect_error_prefix_cross(ev))

    for retire in retires:
        op = m_instruction(retire)
        if op is None:
            continue
        active_start = next((s for s in reversed(ev) if s.get("kind") == "DMA_ACTIVE_START" and
                             s.get("epoch") == retire.get("epoch") and
                             num(s, "cycle") <= num(retire, "cycle") and
                             any(d.get("kind") == "SUBMIT" and d.get("epoch") == s.get("epoch") and
                                 d.get("tag") == s.get("tag") and num(d, "cycle") <= num(s, "cycle")
                                 for d in submits)), None)
        active_end = next((e for e in ev if e.get("kind") == "DMA_ACTIVE_END" and active_start and
                           e.get("epoch") == active_start.get("epoch") and e.get("tag") == active_start.get("tag") and
                           num(e, "cycle") > num(retire, "cycle")), None)
        if active_start and active_end:
            found.append(("m_opcode_x_dma_lifecycle", f"{op}:active", [active_start, retire, active_end], "M retirement occurs between same-tag DMA engine busy edges"))
        else:
            found.append(("m_opcode_x_dma_lifecycle", f"{op}:outside", [retire], "M instruction outside any matching active descriptor interval"))

    # These crosses are constructed from fields sampled on the actual APB
    # completion, not from the scenario name or requested stall percentage.
    for access in (e for e in ev if e.get("kind") == "APB"):
        wait = num(access, "wait_cycles")
        wait_bin = "0" if wait == 0 else "1" if wait == 1 else "2_3" if wait <= 3 else "4_plus"
        direction = "write" if num(access, "write") else "read"
        response = "error" if num(access, "error") else "ok"
        found.append(("apb_direction_x_realized_wait_x_response",
                      f"{direction}:{wait_bin}:{response}", [access],
                      "APB access handshake fields direction/wait_cycles/error from one accepted access"))

    # IRQ source and stalled architectural context must be visible in the
    # same event. Timer-only interrupts can be distinguished from device IRQs.
    for irq in (e for e in ev if e.get("kind") == "IRQ_SET"):
        source = "device" if num(irq, "raw") else "timer" if num(irq, "timer") else "unknown"
        phase = "mdiv" if num(irq, "muldiv_busy") else "apb_wait" if num(irq, "apb_active") else "idle_or_boundary"
        found.append(("interrupt_source_x_arrival_phase", f"{source}:{phase}", [irq],
                      "IRQ source and execution phase sampled at the same RTL cycle"))

    # Completion FIFO occupancy and publish/pop coincidence are recorded at
    # the transaction boundary. Require both observer events on one edge.
    publish_by_edge = {(e.get("epoch"), e.get("cycle")): e for e in ev
                       if e.get("kind") == "COMPLETE_PUBLISH"}
    for pop in (e for e in ev if e.get("kind") == "COMPLETE"):
        publish = publish_by_edge.get((pop.get("epoch"), pop.get("cycle")))
        if publish:
            occupancy = num(pop, "comp_occ")
            found.append(("completion_fifo_occupancy_x_publish_pop",
                          f"{'high' if occupancy >= 2 else 'low'}:simultaneous",
                          [publish, pop], "successor completion published on the same edge as a completion pop"))

    # Correlate maintenance acceptance through completion and retain command,
    # cache configuration, and error outcome as observed RTL values.
    for start in (e for e in ev if e.get("kind") == "MAINT_START"):
        done = next((e for e in ev if e.get("kind") == "MAINT_DONE" and
                     e.get("epoch") == start.get("epoch") and
                     num(e, "cycle") >= num(start, "cycle")), None)
        if done:
            found.append(("maintenance_command_x_observed_result",
                          f"{num(start, 'cmd')}:{'error' if num(done, 'error') else 'ok'}",
                          [start, done], "same-epoch maintenance command start and terminal result"))

    # Translation request/response pairs must agree on epoch, transaction ID,
    # job tag, and vector, and their permission outcome is taken from the RTL
    # response rather than the scenario label.
    responses = [e for e in ev if e.get("kind") == "XLATE_RSP"]
    for req in (e for e in ev if e.get("kind") == "XLATE_REQ"):
        rsp = next((e for e in responses if event_key(e, ("txn", "tag", "vector")) ==
                    event_key(req, ("txn", "tag", "vector")) and num(e, "cycle") >= num(req, "cycle")), None)
        if rsp:
            direction = "write" if num(req, "write") else "read"
            hit = "hit" if num(rsp, "tlb_hit") else "miss"
            outcome = "fault" if num(rsp, "fault") else "ok"
            found.append(("translation_access_x_tlb_x_permission", f"{direction}:{hit}:{outcome}",
                          [req, rsp], "XLATE_REQ/RSP matched by epoch, transaction, tag, and vector"))

    # Successful completion is related to the committed output response by
    # the descriptor identity and final vector index, not merely time order.
    writes = [e for e in ev if e.get("kind") == "MEM_RSP" and num(e, "write") and
              num(e, "committed") and num(e, "error") == 0]
    for pub in (e for e in ev if e.get("kind") == "COMPLETE_PUBLISH" and num(e, "status") == 0):
        write = next((e for e in writes if e.get("epoch") == pub.get("epoch") and
                      e.get("tag") == pub.get("tag") and num(e, "cycle") < num(pub, "cycle") and
                      num(e, "vector") + 1 >= num(pub, "vectors_done")), None)
        if write:
            found.append(("output_commit_x_completion_visibility", "committed_write_before_success_publish",
                          [write, pub], "committed output MEM_RSP with matching epoch/tag precedes success publication"))

    for reject in (e for e in ev if e.get("kind") == "SUBMIT_REJECT"):
        original = next((e for e in ev if e.get("kind") == "SUBMIT" and
                         e.get("epoch") == reject.get("epoch") and e.get("tag") == reject.get("tag") and
                         e.get("asid") == reject.get("asid") and num(e, "cycle") < num(reject, "cycle") and
                         not any(c.get("kind") == "COMPLETE" and c.get("epoch") == e.get("epoch") and
                                 c.get("tag") == e.get("tag") and c.get("asid") == e.get("asid") and
                                 num(e, "cycle") < num(c, "cycle") < num(reject, "cycle") for c in ev)), None)
        if original:
            found.append(("descriptor_phase_x_tag_lifetime", "active_tag_reuse_rejected",
                          [original, reject], "same tag/ASID submit was rejected before any matching completion consumed its live lifetime"))

    for access in (e for e in ev if e.get("kind") == "OWNED_CPU_ACCESS"):
        submitted = next((e for e in ev if e.get("kind") == "SUBMIT" and
                          e.get("epoch") == access.get("epoch") and
                          e.get("tag") == access.get("active_tag") and num(e, "cycle") <= num(access, "cycle") and
                          not any(c.get("kind") == "COMPLETE" and c.get("epoch") == e.get("epoch") and
                                  c.get("tag") == e.get("tag") and num(e, "cycle") < num(c, "cycle") < num(access, "cycle") for c in ev)), None)
        owner = next((e for e in ev if e.get("kind") == "OWNERSHIP" and
                      e.get("epoch") == access.get("epoch") and num(e, "count") > 0 and
                      e.get("active_tag") == access.get("active_tag") and
                      num(e, "cycle") <= num(access, "cycle")), None)
        if owner and submitted:
            try:
                address = int(access.get("addr", ""), 16)
            except ValueError:
                continue
            ranges, mapping_events = descriptor_physical_ranges(submitted, ev)
            if ranges is not None and not physical_access_owned(address, ranges):
                found.append(("cache_ownership_x_cpu_access", "unrelated_cpu_access_permitted",
                          sorted([submitted, owner, *mapping_events, access],
                                 key=lambda event: (num(event, "cycle"), num(event, "eid"))),
                          "same live tag and epoch; successful XLATE request/response pairs reconstruct line-rounded physical owned spans; CPU PA is outside them before completion"))

    # Reset cancellation is credited only when ownership was live at reset and
    # a post-reset completion or firmware termination occurs in the new epoch.
    for reset in (e for e in ev if e.get("kind") == "RESET_ASSERT"):
        pending = any(num(reset, key) for key in ("xlate_pending", "mem_pending", "ptw_pending", "host_aw_pending", "host_w_pending", "host_ar_pending", "apb_active", "chip_busy", "maint_active", "completion_pending"))
        if not pending:
            continue
        release = next((e for e in ev if e.get("kind") == "RESET_RELEASE" and
                        e.get("epoch") == reset.get("epoch") and num(e, "cycle") > num(reset, "cycle")), None)
        recovered = next((e for e in ev if release and e.get("epoch") == release.get("epoch") and
                          e.get("kind") in ("COMPLETE", "FIRMWARE_DONE") and
                          num(e, "cycle") > num(release, "cycle")), None)
        if release and recovered:
            found.append(("reset_phase_x_outstanding_owner", "pending_owner_reset_recovered",
                          [reset, release, recovered], "reset captured pending owner, epoch advanced, firmware progressed after release"))

    # Explicit event-order interactions that can be checked within a single
    # epoch and job, including power-service overlap and maintenance lifecycle.
    for start in (e for e in ev if e.get("kind") == "MAINT_START"):
        done = next((e for e in ev if e.get("kind") == "MAINT_DONE" and e.get("epoch") == start.get("epoch") and
                     num(e, "cycle") >= num(start, "cycle")), None)
        if done:
            found.append(("maintenance_start_x_completion", "start_then_done", [start, done], "same-epoch maintenance lifecycle"))

    for irq in (e for e in ev if e.get("kind") == "IRQ_SET"):
        take = next((e for e in retires if e.get("epoch") == irq.get("epoch") and num(e, "intr") and
                     num(e, "cycle") >= num(irq, "cycle")), None)
        if take:
            found.append(("device_event_x_interrupt_retirement", "irq_set_then_architectural_take",
                          [irq, take], "IRQ event precedes interrupt retirement in the same epoch"))

    chip_busy_start = None
    for event in ev:
        if event.get("kind") != "CHIPLET_EVT":
            continue
        if num(event, "busy") and chip_busy_start is None:
            chip_busy_start = event
        elif not num(event, "busy") and chip_busy_start is not None:
            interval = [e for e in ev if e.get("epoch") == event.get("epoch") and
                        e.get("kind") in ("ACCEL_CMD", "ACCEL_IN", "ACCEL_OUT") and
                        num(chip_busy_start, "cycle") <= num(e, "cycle") <= num(event, "cycle")]
            if interval:
                found.append(("chiplet_busy_x_accelerator_activity", "overlapping_service_activity",
                              [chip_busy_start, interval[0], event],
                              "accelerator transaction lies within a measured chiplet busy interval"))
            chip_busy_start = None
    return found


def main() -> int:
    rows_by_bin: dict[tuple[str, str], dict[str, object]] = {}
    # Seed the denominator from the reviewed manifest before observing traces.
    # Missing evidence remains visible as NOT_REACHED instead of vanishing
    # from an observed-only denominator.
    for family, bins in MANIFEST_DATA.get("required_cross_bins", {}).items():
        for bin_name in bins:
            rows_by_bin[(family, bin_name)] = {
                "cross_family": family, "bin": bin_name, "point_type": "cross_bin",
                "status": "NOT_REACHED", "hit_count": 0, "first_test": "NOT_REACHED",
                "first_trace": "", "first_trace_sha256": "", "first_event_ids": "",
                "first_witness_event_ids": "", "witness_event_ids": "",
                "contributing_tests": set(), "independent_test_count": 0,
                "independent_sources": set(), "construction_paths": set(), "contributing_seeds": set(),
                "firmware_hashes": set(), "risk": (
                    "permission" if "translation" in family else
                    "recovery" if "error_stage" in family else
                    "ownership" if "completion" in family or "maintenance" in family else
                    "recovery" if "reset" in family else
                    "retirement" if "m_opcode" in family or "m_result" in family or "interrupt" in family else
                    "integration"),
                "correlation_rule": "Required tuple in the fixed manifest; awaits an executable correlated witness",
            }
    inputs = []
    for report_name in ("compute_crossover_model.csv", "compute_crossover_random_model.csv",
                        "rv32m_instruction_stream_random_model.csv", "compute_crossover_independent_model.csv"):
        path = REPORTS / report_name
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            inputs.extend(row for row in csv.DictReader(handle) if row.get("status") == "PASS" and row.get("iss_status") == "PASS")
    source_by_scenario = {}
    for summary in inputs:
        trace = summary.get("trace", "")
        path = ROOT / trace
        if not path.exists():
            path = ROOT / "build/protected_offload/shared_firmware" / trace
        if not path.exists():
            continue
        scenario = summary.get("scenario", Path(trace).parent.name)
        required_provenance = ("stimulus_origin", "stimulus_generator_sha256", "stimulus_instance_sha256")
        if any(not summary.get(field) for field in required_provenance):
            raise SystemExit(f"{scenario}: summary lacks recorded stimulus-construction provenance")
        if summary["stimulus_origin"] not in {"generated_cpu_instruction_stream", "directed_scenario_program",
                                               "seeded_firmware_schedule", "fixed_firmware_matrix", "independent_firmware_driver"}:
            raise SystemExit(f"{scenario}: unknown stimulus origin {summary['stimulus_origin']!r}")
        source_by_scenario[scenario] = summary
        for family, bin_name, witness, rationale in collect(path):
            key = (family, bin_name)
            if key not in REQUIRED_KEYS:
                continue
            trace_hash = summary.get("trace_sha256", "")
            row = rows_by_bin.setdefault(key, {"cross_family": family, "bin": bin_name,
                "point_type": "cross_bin", "status": "PASS", "hit_count": 0, "first_test": scenario,
                "first_trace": trace, "first_trace_sha256": trace_hash,
                "first_event_ids": "", "first_witness_event_ids": "", "witness_event_ids": "", "contributing_tests": set(),
                "independent_test_count": 0, "independent_sources": set(), "construction_paths": set(), "contributing_seeds": set(), "firmware_hashes": set(), "risk": (
                    "permission" if "translation" in family else
                    "recovery" if "error_stage" in family else
                    "ownership" if "completion" in family or "maintenance" in family else
                    "recovery" if "reset" in family else
                    "retirement" if "m_opcode" in family or "m_result" in family or "interrupt" in family else
                    "integration"),
                "correlation_rule": rationale})
            if int(row["hit_count"]) == 0:
                row["status"] = "PASS"
                row["first_test"] = scenario
                row["first_trace"] = trace
                row["first_trace_sha256"] = trace_hash
                row["first_witness_event_ids"] = ";".join(f"{trace}#{event.get('eid','')}" for event in witness)
            row["hit_count"] = int(row["hit_count"]) + 1
            row["contributing_tests"].add(scenario)
            summary = source_by_scenario[scenario]
            row["contributing_seeds"].add(summary.get("seed", ""))
            row["firmware_hashes"].add(summary.get("firmware_sha256", summary.get("elf_sha256", "")))
            implementation = witness_implementation(summary,witness)
            row["independent_sources"].add((implementation, summary["stimulus_instance_sha256"]))
            row["construction_paths"].add(implementation)
            row["witness_event_ids"] += (";" if row["witness_event_ids"] else "") + ";".join(
                f"{trace}#{event.get('eid','')}" for event in witness)
    manifest = MANIFEST_DATA
    observed_families = {key[0] for key in rows_by_bin}
    for family in manifest["required_cross_families"]:
        if family not in observed_families:
            rows_by_bin[(family, "NO_OBSERVED_WITNESS")] = {
                "cross_family": family, "bin": "NO_OBSERVED_WITNESS", "point_type": "cross_bin",
                "status": "NOT_REACHED", "hit_count": 0, "first_test": "NOT_REACHED",
                "first_trace": "", "first_trace_sha256": "",
                "first_event_ids": "", "first_witness_event_ids": "", "witness_event_ids": "", "contributing_tests": set(),
                "contributing_seeds": set(), "firmware_hashes": set(), "independent_sources": set(),
                "independent_test_count": 0, "construction_paths": set(),
                "risk": "recovery" if "reset" in family or "error_stage" in family else
                "retirement" if "m_result" in family else "permission" if "permission" in family else "ownership",
                "correlation_rule": "Required family in the versioned manifest; no qualifying correlated trace window observed"}
    rows = []
    for row in sorted(rows_by_bin.values(), key=lambda r: (str(r["cross_family"]), str(r["bin"]))):
        tests = sorted(row["contributing_tests"])
        # A new seed with the same generator is stimulus diversity, not an
        # independent construction. Count distinct, source-hashed generators.
        row["independent_test_count"] = len(row["construction_paths"])
        row["independent_sources"] = ";".join(f"{implementation}:{instance}" for implementation, instance in sorted(row["independent_sources"]))
        row["construction_paths"] = ";".join(sorted(row["construction_paths"]))
        row["contributing_seeds"] = ";".join(sorted(row["contributing_seeds"]))
        row["firmware_hashes"] = ";".join(sorted(row["firmware_hashes"]))
        row["contributing_tests"] = ";".join(tests)
        row["first_event_ids"] = row["witness_event_ids"].split(";")[0] if row["witness_event_ids"] else ""
        row["manifest_sha256"] = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        row["generator_sha256"] = cross_generator_hash()
        rows.append(row)
    fields = ["point_type", "cross_family", "bin", "status", "hit_count", "first_test", "first_trace", "first_trace_sha256", "first_event_ids", "first_witness_event_ids",
              "witness_event_ids", "contributing_tests", "contributing_seeds", "firmware_hashes", "independent_sources", "independent_test_count", "construction_paths", "risk", "correlation_rule", "manifest_sha256", "generator_sha256"]
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    missing = sum(row["status"] != "PASS" for row in rows)
    independence_missing = sum(int(row["independent_test_count"])<2 for row in rows
                               if row["risk"] in {"retirement","ownership","permission","recovery"})
    required_count = sum(len(bins) for bins in manifest.get("required_cross_bins", {}).values())
    closed=bool(rows) and not missing and not independence_missing and len(rows)==required_count
    print(f"CROSSOVER_CROSSES|status={'PASS' if closed else 'PARTIAL'}|closed={len(rows)-missing}/{required_count}|missing={missing}|independence_missing={independence_missing}|tests={len(inputs)}")
    return 0 if closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
