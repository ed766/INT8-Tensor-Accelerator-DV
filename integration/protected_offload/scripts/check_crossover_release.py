#!/usr/bin/env python3
"""Fail-closed validation for the protected-offload crossover evidence.

This gate intentionally does not convert incomplete coverage into PASS.  It
checks the generated artifacts and requires every claimed model replay row to
be present, passing, and trace-backed.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path
import sys
csv.field_size_limit(20_000_000)

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
sys.path.insert(0, str(ROOT / "integration/protected_offload/scripts"))
from check_crossover_trace import check as replay_trace, events as load_trace_events  # noqa: E402
from check_crossover_mutations import REQUIRED as AUDIT_MUTATIONS  # noqa: E402
from coverage_provenance import validate_manifest  # noqa: E402
from ownership_ranges import descriptor_physical_ranges, physical_access_owned  # noqa: E402

MANIFEST = ROOT / "integration/protected_offload/coverage/compute_crossover_manifest.json"
COVERAGE_GENERATOR = ROOT / "integration/protected_offload/scripts/generate_compute_crossover_coverage.py"
# The core is authoritative in the sibling chiplet repository.  Its report is
# deliberately required here: a local ISS replay is not an external oracle.
CHIPLET_ROOT = Path(os.environ.get("CHIPLET_ROOT", ROOT.parent / "ucie_chiplet_soc"))
CHIPLET_EXTERNAL_REPORT = (CHIPLET_ROOT / "chiplet_extension" /
                           "reports" / "rv32_external_iss_summary.csv")
CHIPLET_ACT_M_REPORT = (CHIPLET_ROOT / "chiplet_extension" /
                        "reports" / "rv32_act_m_summary.csv")


def read(name: str) -> list[dict[str, str]]:
    path = REPORTS / name
    if not path.exists():
        raise SystemExit(f"missing required report: {path}")
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def require_all(name: str, rows: list[dict[str, str]], status="PASS") -> None:
    if not rows:
        raise SystemExit(f"empty required report: {name}")
    bad = [row.get("scenario", row.get("trace", row.get("property", row.get("mutation", "?")))) for row in rows
           if row.get("status") != status]
    if bad:
        raise SystemExit(f"{name}: {len(bad)} rows are not {status}: {bad[:4]}")


def event_int(event: dict[str, str], field: str, default: int = 0) -> int:
    value = event.get(field, "")
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        try:
            return int(value, 16)
        except (TypeError, ValueError):
            return default


def event_hex(event: dict[str, str], field: str, default: int = 0) -> int:
    """Parse observer architectural values, whose schema encodes them as hex."""
    value = event.get(field, "")
    try:
        return int(value, 16)
    except (TypeError, ValueError):
        return default


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & sign else value


def validate_cross_witness(row: dict[str, str], witness: list[dict[str, str]],
                           all_events: list[dict[str, str]] | None = None) -> None:
    family, bin_name = row.get("cross_family", ""), row.get("bin", "")
    kinds = [event.get("kind", "") for event in witness]
    if not witness or any(not event.get("run") or not event.get("eid") for event in witness):
        raise SystemExit(f"cross witness has incomplete event records: {family}:{bin_name}")
    if len({event.get("run") for event in witness}) != 1:
        raise SystemExit(f"cross witness mixes runs: {family}:{bin_name}")
    numeric_cycles = [int(event.get("cycle", "0")) for event in witness]
    if numeric_cycles != sorted(numeric_cycles):
        raise SystemExit(f"cross witness events are not in event order: {family}:{bin_name}")
    if family == "m_opcode_x_dma_lifecycle":
        if (bin_name.endswith(":active") and kinds != ["DMA_ACTIVE_START", "RETIRE", "DMA_ACTIVE_END"]) or \
                (bin_name.endswith(":outside") and kinds != ["RETIRE"]):
            raise SystemExit(f"M lifecycle witness has invalid transaction event sequence: {bin_name}")
        try:
            retire = witness[1] if bin_name.endswith(":active") else witness[0]
            insn = int(retire.get("insn", "0"), 16)
        except ValueError:
            insn = 0
        if (insn & 0x7f) != 0x33 or ((insn >> 25) & 0x7f) != 1:
            raise SystemExit(f"M lifecycle witness retirement is not an M opcode: {bin_name}")
        if bin_name.endswith(":active"):
            if witness[0].get("tag") != witness[-1].get("tag") or \
                    witness[0].get("epoch") != witness[-1].get("epoch") or \
                    not (int(witness[0].get("cycle", "0")) <= int(retire.get("cycle", "0")) < int(witness[2].get("cycle", "0"))):
                raise SystemExit(f"active M lifecycle lacks matching engine-busy interval: {bin_name}")
    elif family == "translation_access_x_tlb_x_permission":
        if kinds != ["XLATE_REQ", "XLATE_RSP"]:
            raise SystemExit(f"translation witness must contain matched request/response: {bin_name}")
        left, right = witness
        if any(left.get(field) != right.get(field) for field in ("epoch", "txn", "tag", "vector")):
            raise SystemExit(f"translation witness identity mismatch: {bin_name}")
        direction = "write" if int(left.get("write", "0")) else "read"
        hit = "hit" if int(right.get("tlb_hit", "0")) else "miss"
        outcome = "fault" if int(right.get("fault", "0")) else "ok"
        if bin_name != f"{direction}:{hit}:{outcome}":
            raise SystemExit(f"translation witness does not match its bin label: {bin_name}")
    elif family == "output_commit_x_completion_visibility":
        if kinds != ["MEM_RSP", "COMPLETE_PUBLISH"]:
            raise SystemExit(f"completion witness lacks commit response and publication: {bin_name}")
        write, publish = witness
        if (write.get("epoch") != publish.get("epoch") or write.get("tag") != publish.get("tag") or
                int(write.get("write", "0")) != 1 or int(write.get("committed", "0")) != 1 or
                int(write.get("error", "0")) != 0 or int(publish.get("status", "0")) != 0 or
                int(write.get("cycle", "0")) >= int(publish.get("cycle", "0"))):
            raise SystemExit(f"completion witness violates commit-before-publication: {bin_name}")
    elif family == "descriptor_phase_x_tag_lifetime":
        if kinds != ["SUBMIT", "SUBMIT_REJECT"]:
            raise SystemExit(f"tag lifetime witness lacks submit and explicit rejection: {bin_name}")
        first, rejected = witness
        if any(first.get(field) != rejected.get(field) for field in ("epoch", "tag", "asid")) or \
                int(first.get("cycle", "0")) >= int(rejected.get("cycle", "0")):
            raise SystemExit(f"tag lifetime witness is not the same live identity: {bin_name}")
    elif family == "cache_ownership_x_cpu_access":
        submits = [event for event in witness if event.get("kind") == "SUBMIT"]
        owners = [event for event in witness if event.get("kind") == "OWNERSHIP"]
        accesses = [event for event in witness if event.get("kind") == "OWNED_CPU_ACCESS"]
        if len(submits) != 1 or len(owners) != 1 or len(accesses) != 1:
            raise SystemExit(f"ownership witness lacks exactly one submit, owner sample, and CPU access: {bin_name}")
        submit, owner, access = submits[0], owners[0], accesses[0]
        if (submit.get("epoch") != owner.get("epoch") or owner.get("epoch") != access.get("epoch") or
                submit.get("tag") != access.get("active_tag") or
                submit.get("tag") != owner.get("active_tag") or int(owner.get("count", "0")) <= 0 or
                int(owner.get("cycle", "0")) > int(access.get("cycle", "-1"))):
            raise SystemExit(f"ownership witness has mismatched owner identity: {bin_name}")
        if all_events is None:
            raise SystemExit("ownership validation requires the complete source trace")
        ranges, mapping_events = descriptor_physical_ranges(submit, all_events)
        if ranges is None:
            raise SystemExit(f"ownership trace lacks successful IOVA-to-PA mappings for the live descriptor: {bin_name}")
        witness_ids = {event.get("eid") for event in witness}
        if any(event.get("eid") not in witness_ids for event in mapping_events):
            raise SystemExit(f"ownership witness omits translation events used to derive PA ranges: {bin_name}")
        address = event_hex(access, "addr")
        if physical_access_owned(address, ranges):
            raise SystemExit(f"unrelated-CPU-access bin points inside a translated line-rounded physical owned span: {bin_name}")
    elif family == "reset_phase_x_outstanding_owner":
        if kinds[0:2] != ["RESET_ASSERT", "RESET_RELEASE"] or kinds[-1] not in ("COMPLETE", "FIRMWARE_DONE"):
            raise SystemExit(f"reset recovery witness lacks assert/release/post-reset progress: {bin_name}")
        reset, release, recovered = witness[0], witness[1], witness[-1]
        if int(reset.get("cycle", "0")) >= int(release.get("cycle", "0")) or \
                reset.get("epoch") != release.get("epoch") or release.get("epoch") != recovered.get("epoch"):
            raise SystemExit(f"reset recovery witness does not remain within the epoch opened by reset assertion: {bin_name}")
        if not any(int(reset.get(field, "0")) for field in
                   ("xlate_pending", "mem_pending", "ptw_pending", "host_aw_pending", "host_w_pending", "host_ar_pending", "apb_active", "chip_busy", "maint_active", "completion_pending")):
            raise SystemExit(f"reset recovery witness had no owned work at reset: {bin_name}")
    elif family == "maintenance_start_x_completion":
        if kinds != ["MAINT_START", "MAINT_DONE"] or witness[0].get("epoch") != witness[1].get("epoch"):
            raise SystemExit(f"maintenance witness is not a same-epoch start/done pair: {bin_name}")
    elif family == "device_event_x_interrupt_retirement":
        if kinds != ["IRQ_SET", "RETIRE"] or witness[0].get("epoch") != witness[1].get("epoch") or \
                int(witness[1].get("intr", "0")) == 0:
            raise SystemExit(f"IRQ witness lacks a same-epoch architectural interrupt retirement: {bin_name}")
    elif family == "chiplet_busy_x_accelerator_activity":
        if len(witness) != 3 or kinds[0] != "CHIPLET_EVT" or not int(witness[0].get("busy", "0")) or \
                kinds[1] not in ("ACCEL_CMD", "ACCEL_IN", "ACCEL_OUT") or kinds[2] != "CHIPLET_EVT" or \
                int(witness[2].get("busy", "1")) or len({event.get("epoch") for event in witness}) != 1 or \
                not (int(witness[0].get("cycle", "0")) <= int(witness[1].get("cycle", "0")) <= int(witness[2].get("cycle", "0"))):
            raise SystemExit(f"combined-service witness lacks measured service overlap: {bin_name}")
    elif family == "apb_direction_x_realized_wait_x_response":
        if len(witness) != 1 or kinds != ["APB"]:
            raise SystemExit(f"APB cross must cite one completed APB transfer: {bin_name}")
        event = witness[0]
        wait = int(event.get("wait_cycles", "0"))
        wait_bin = "0" if wait == 0 else "1" if wait == 1 else "2_3" if wait <= 3 else "4_plus"
        expected = f"{'write' if int(event.get('write', '0')) else 'read'}:{wait_bin}:{'error' if int(event.get('error', '0')) else 'ok'}"
        if expected != bin_name:
            raise SystemExit(f"APB event does not match realized direction/wait/response bin: {bin_name}")
    elif family == "interrupt_source_x_arrival_phase":
        if len(witness) != 1 or kinds != ["IRQ_SET"]:
            raise SystemExit(f"interrupt cross must cite one IRQ arrival event: {bin_name}")
        event = witness[0]
        source = "device" if int(event.get("raw", "0")) else "timer" if int(event.get("timer", "0")) else "unknown"
        phase = "mdiv" if int(event.get("muldiv_busy", "0")) else "apb_wait" if int(event.get("apb_active", "0")) else "idle_or_boundary"
        if bin_name != f"{source}:{phase}":
            raise SystemExit(f"IRQ event does not match source/arrival-phase bin: {bin_name}")
    elif family == "m_result_x_consumer_dependency":
        if not all(kind == "RETIRE" for kind in kinds) or len(witness) not in (2, 3):
            raise SystemExit(f"M dependency witness must be an ordered retirement window: {bin_name}")
        if len({event.get("epoch") for event in witness}) != 1:
            raise SystemExit(f"M dependency witness crosses reset epochs: {bin_name}")
        retires = witness
        m_index = next((i for i, event in enumerate(retires)
                        if ((event_hex(event, "insn") >> 25) & 0x7f) == 1 and
                        (event_hex(event, "insn") & 0x7f) == 0x33), -1)
        if m_index < 0:
            raise SystemExit(f"M dependency witness has no retired M instruction: {bin_name}")
        mretire = retires[m_index]
        rd = event_int(mretire, "rd_addr")
        result = event_hex(mretire, "rd_data")
        if rd == 0:
            raise SystemExit(f"M dependency witness writes x0 and cannot establish a dependency: {bin_name}")
        if bin_name == "m_result_to_load_address":
            if len(retires) != 2:
                raise SystemExit(f"M-to-load dependency requires two adjacent retirements: {bin_name}")
            load = retires[1]
            insn = event_hex(load, "insn")
            if ((insn & 0x7f) != 0x03 or event_int(load, "rs1_addr") != rd or
                    event_hex(load, "mem_addr") != (result + _sign_extend((insn >> 20) & 0xfff, 12)) & 0xffffffff):
                raise SystemExit(f"M result is not the following load effective-address base: {bin_name}")
        elif bin_name == "m_result_to_store_data":
            if len(retires) != 2:
                raise SystemExit(f"M-to-store dependency requires two adjacent retirements: {bin_name}")
            store = retires[1]
            insn = event_hex(store, "insn")
            imm = ((insn >> 25) << 5) | ((insn >> 7) & 0x1f)
            if ((insn & 0x7f) != 0x23 or event_int(store, "rs2_addr") != rd or
                    event_hex(store, "mem_wdata") != result or
                    event_hex(store, "mem_addr") != (event_hex(store, "rs1_data") + _sign_extend(imm, 12)) & 0xffffffff):
                raise SystemExit(f"M result is not the following store data operand: {bin_name}")
        elif bin_name == "m_result_to_branch":
            if len(retires) != 2 or (event_hex(retires[1], "insn") & 0x7f) != 0x63 or \
                    rd not in (event_int(retires[1], "rs1_addr"), event_int(retires[1], "rs2_addr")):
                raise SystemExit(f"M result is not consumed by the following branch: {bin_name}")
        elif bin_name == "load_m_store_dependency":
            if len(retires) != 3:
                raise SystemExit(f"load/M/store dependency requires three adjacent retirements: {bin_name}")
            load, arithmetic, store = retires
            load_rd = event_int(load, "rd_addr")
            store_insn = event_hex(store, "insn")
            if ((event_hex(load, "insn") & 0x7f) != 0x03 or
                    load_rd not in (event_int(arithmetic, "rs1_addr"), event_int(arithmetic, "rs2_addr")) or
                    (event_hex(arithmetic, "insn") & 0x7f) != 0x33 or
                    ((event_hex(arithmetic, "insn") >> 25) & 0x7f) != 1 or
                    (store_insn & 0x7f) != 0x23 or
                    event_int(store, "rs2_addr") != event_int(arithmetic, "rd_addr") or
                    event_hex(store, "mem_wdata") != event_hex(arithmetic, "rd_data")):
                raise SystemExit(f"retirement window does not prove load-to-M-to-store dependency: {bin_name}")
        else:
            raise SystemExit(f"unknown M dependency bin: {bin_name}")
    elif family == "reset_phase_x_owner_type":
        if len(witness) != 1 or kinds != ["RESET_ASSERT"]:
            raise SystemExit(f"reset-owner bin must cite one reset snapshot: {bin_name}")
        fields = {
            "ptw_request_pending": "ptw_pending",
            "payload_request_pending": "mem_pending",
            "payload_response_pending": "mem_response_valid",
            "apb_wait_pending": "apb_active",
            "completion_pending": "completion_pending",
            "host_aw_waiting_w": "host_aw_pending",
            "muldiv_result_pending": "muldiv_result_valid",
        }
        field = fields.get(bin_name)
        if not field or not event_int(witness[0], field):
            raise SystemExit(f"reset snapshot does not contain the owner named by bin {bin_name}")
    elif family == "error_stage_x_committed_prefix_x_recovery":
        if bin_name == "input_translation:0:contained":
            if kinds != ["COMPLETE"] or event_int(witness[0], "status") != 2 or \
                    event_int(witness[0], "fault_stage") != 1 or event_int(witness[0], "vectors_done") != 0:
                raise SystemExit(f"input-translation containment witness has wrong completion metadata: {bin_name}")
        elif bin_name in ("output_page:0:contained", "output_permission:0:contained"):
            if kinds != ["XLATE_RSP", "COMPLETE"]:
                raise SystemExit(f"translation-error witness lacks response/completion: {bin_name}")
            response, completion = witness
            expected_fault = 1 if bin_name.startswith("output_page") else 2
            if (not event_int(response, "write") or event_int(response, "fault") != expected_fault or
                    response.get("epoch") != completion.get("epoch") or response.get("tag") != completion.get("tag") or
                    event_int(completion, "status") != 3 or event_int(completion, "fault_stage") != 3 or
                    event_int(completion, "vectors_done") != 0):
                raise SystemExit(f"output translation fault does not match zero-prefix completion: {bin_name}")
        elif bin_name == "input_memory:0:contained":
            if kinds != ["MEM_RSP", "COMPLETE"]:
                raise SystemExit(f"input memory error witness lacks response/completion: {bin_name}")
            response, completion = witness
            if (event_int(response, "write") or not event_int(response, "error") or
                    response.get("epoch") != completion.get("epoch") or response.get("tag") != completion.get("tag") or
                    event_int(completion, "status") != 4 or event_int(completion, "fault_stage") != 2 or
                    event_int(completion, "vectors_done") != 0):
                raise SystemExit(f"input memory error does not match zero-prefix completion: {bin_name}")
        elif bin_name == "partial_output:1:retry_success":
            if kinds != ["COMPLETE", "COMPLETE"]:
                raise SystemExit(f"partial-output recovery witness requires failure and retry completions: {bin_name}")
            failed, success = witness
            if (failed.get("epoch") != success.get("epoch") or failed.get("tag") != success.get("tag") or
                    event_int(failed, "status") != 5 or event_int(failed, "fault_stage") != 4 or
                    event_int(failed, "vectors_done") != 1 or event_int(success, "status") != 0 or
                    event_int(success, "vectors_done") < 2 or event_int(failed, "cycle") >= event_int(success, "cycle")):
                raise SystemExit(f"partial-output prefix/retry metadata is inconsistent: {bin_name}")
        else:
            raise SystemExit(f"unknown error-prefix bin: {bin_name}")
    elif family == "completion_fifo_occupancy_x_publish_pop":
        if kinds != ["COMPLETE_PUBLISH", "COMPLETE"] or len({(event.get("epoch"), event.get("cycle")) for event in witness}) != 1:
            raise SystemExit(f"completion FIFO cross requires same-edge publish and pop: {bin_name}")
    elif family == "maintenance_command_x_observed_result":
        if kinds != ["MAINT_START", "MAINT_DONE"] or witness[0].get("cmd") != bin_name.split(":", 1)[0]:
            raise SystemExit(f"maintenance command/result cross does not match its observed command: {bin_name}")
    else:
        raise SystemExit(f"cross witness has no validation rule: {family}")


def main() -> int:
    selftest = read("compute_crossover_checker_selftest.csv")
    expected_checker_hash = hashlib.sha256(
        (ROOT / "integration/protected_offload/scripts/check_crossover_trace.py").read_bytes()
    ).hexdigest()
    expected_selftest_hash = hashlib.sha256(
        (ROOT / "integration/protected_offload/scripts/check_crossover_trace_selftest.py").read_bytes()
    ).hexdigest()
    if len(selftest) != 36 or any(row.get("status") != "PASS" for row in selftest):
        raise SystemExit("checker qualification must contain 29 negative and 7 positive passing controls")
    negative_selftests = [row for row in selftest if row.get("expected") == "FAIL"]
    if len(negative_selftests) != 29 or any(
            row.get("observed") != "FAIL" or not row.get("expected_category") or
            row.get("category_observed") != "true" for row in negative_selftests):
        raise SystemExit("every checker negative must fail in its specifically expected category")
    if any(row.get("checker_sha256") != expected_checker_hash or
           row.get("selftest_sha256") != expected_selftest_hash for row in selftest):
        raise SystemExit("checker self-test report is stale for the current checker or qualification suite")
    controls = {row.get("case") for row in selftest if row.get("expected") == "PASS"}
    if controls != {"valid_control", "valid_maintenance_control", "valid_reset_control",
                    "valid_two_beat_host_write", "valid_two_beat_host_read",
                    "valid_apb_setup_after_reset", "strict_lineage_valid"}:
        raise SystemExit(f"checker qualification valid controls are incomplete: {sorted(controls)}")
    directed = read("compute_crossover_directed.csv")
    replay = read("compute_crossover_model.csv")
    random_replay = read("compute_crossover_random_model.csv")
    require_all("compute_crossover_directed.csv", directed)
    require_all("compute_crossover_model.csv", replay)
    require_all("compute_crossover_random_model.csv", random_replay)
    combined_directed = [row for row in directed
                         if row.get("family") == "combined_services"]
    if len(combined_directed) != 6 or any(
            int(row.get("realized_service_overlap_events", "0")) <= 0
            for row in combined_directed):
        raise SystemExit("all six directed combined-service rows must observe actual AES/INT8 overlap")
    if any(not row.get("observer_build_id") for row in replay + random_replay):
        raise SystemExit("strict trace replay lacks per-event source build identity; regenerate schema-3 traces")
    if len(replay) != 48 or len({row.get("trace") for row in replay}) != 48:
        raise SystemExit(f"directed replay must contain 48 unique RTL traces, found {len(replay)}")
    scenario_ids = {int(row["scenario_program_id"]) for row in directed
                    if row.get("scenario_program_id", "").isdigit()}
    scenario_images = {row.get("elf_sha256", "") for row in directed}
    scenario_sources = {row.get("scenario_program_source_sha256", "") for row in directed}
    scenario_code_paths = {row.get("scenario_program_trace_sha256", "") for row in directed}
    if (scenario_ids != set(range(1, 49)) or len(scenario_images) != 48 or
            len(scenario_sources) != 48 or "" in scenario_sources or
            len(scenario_code_paths) != 48 or "" in scenario_code_paths or
            any(not row.get("scenario_activation_event_id") or
                not row.get("scenario_activation_count", "").isdigit() or
                int(row.get("scenario_activation_count", "0")) < 1 or
                (row.get("requested_reset_phase") == "none" and
                 int(row.get("scenario_activation_count", "0")) != 1) or
                (row.get("requested_reset_phase") != "none" and
                 row.get("scenario_activation_post_reset") != "true") or
                not re.fullmatch(r"[0-9a-fA-F]{8}", row.get("scenario_activation_address", "")) or
                row.get("scenario_activation_value") !=
                    f"{0x43520000 | int(row['scenario_program_id']):08x}"
                for row in directed)):
        raise SystemExit("directed firmware rows lack 48 distinct scenario sources, retired instruction streams, and activation signatures")
    directed_events: dict[str, list[dict[str, str]]] = {}
    for row in directed:
        trace_path = ROOT / row["trace"]
        trace_events = load_trace_events(trace_path)
        directed_events[row["scenario"]] = trace_events
        if row.get("combined_host") == "1":
            from check_compute_host_evidence import check_host_trace
            host_result = check_host_trace(trace_path, row["scenario"])
            if host_result["status"] != "PASS":
                raise SystemExit(f"{row['scenario']}: independent AES/return/destination checker failed: {host_result['first_failure']}")
        matches = [event for event in trace_events if event.get("kind") == "RETIRE" and
                   event.get("mem_addr") == row["scenario_activation_address"] and
                   event.get("mem_wdata") == row["scenario_activation_value"] and
                   event_int(event, "mem_wmask") != 0 and
                   (event.get("eid") == row["scenario_activation_event_id"] or
                    event.get("retire_order") == row["scenario_activation_event_id"])]
        if len(matches) < 1 or row["scenario_activation_event_id"] not in {
                event.get("eid", "") for event in matches} | {
                event.get("retire_order", "") for event in matches}:
            raise SystemExit(f"directed scenario activation does not resolve to its trace retirement: {row.get('scenario')}")
        scenario_id = int(row["scenario_program_id"])
        start_pc = event_hex(row, "scenario_program_start_pc")
        end_pc = event_hex(row, "scenario_program_end_pc")
        marker = next(event for event in matches if
                      event.get("eid") == row["scenario_activation_event_id"] or
                      event.get("retire_order") == row["scenario_activation_event_id"])
        program = [event for event in trace_events if event.get("kind") == "RETIRE" and
                   event.get("epoch") == marker.get("epoch") and
                   start_pc <= event_hex(event, "pc") < end_pc and
                   int(event.get("cycle", "0")) < int(marker.get("cycle", "0"))]
        if (len(program) != int(row.get("scenario_program_retirements", "0")) or len(program) < 12 or
                hashlib.sha256("\n".join(event.get("insn", "") for event in program).encode()).hexdigest() !=
                row.get("scenario_program_trace_sha256")):
            raise SystemExit(f"directed scenario program did not execute its uniquely compiled instruction stream: {row.get('scenario')}")
        family_index = (scenario_id - 1) // 6
        case_index = (scenario_id - 1) % 6 + 1
        scratch = 0x1000 + scenario_id * 8
        token = 0x53000000 | scenario_id
        op_value = {
            1: (token + case_index) & 0xffffffff,
            2: token ^ (scenario_id & 0x7ff),
            3: (token << case_index) & 0xffffffff,
            4: token >> case_index,
            5: token | (scenario_id & 0x7ff),
            6: token & 0x7ff,
        }[case_index]
        expected_store = op_value ^ token
        memory_events = [event for event in program if event_int(event, "mem_rmask") or
                         event_int(event, "mem_wmask")]
        if (len(memory_events) != 3 or
                [event_hex(event, "mem_addr") for event in memory_events] != [scratch, scratch, scratch + 4] or
                [event_hex(event, "mem_wmask") for event in memory_events] != [0xf, 0, 0xf] or
                [event_hex(event, "mem_rmask") for event in memory_events] != [0, 0xf, 0] or
                event_hex(memory_events[0], "mem_wdata") != token or
                event_hex(memory_events[1], "mem_rdata") != token or
                event_hex(memory_events[1], "rd_data") != token or
                event_hex(memory_events[2], "mem_wdata") != expected_store or
                row.get("scenario_program_source_sha256") == ""):
            raise SystemExit(f"directed scenario program lacks its qualified unique SRAM transaction/signature: {row.get('scenario')}")
        witness_ids = [event.get("eid", "") for event in memory_events]
        if (";".join(witness_ids) != row.get("scenario_program_witness_event_ids") or
                int(row.get("scenario_program_rw_event_count", "0")) != 3 or
                int(row.get("scenario_program_start_pc", "0"), 16) >=
                int(row.get("scenario_program_end_pc", "0"), 16)):
            raise SystemExit(f"directed scenario transaction witness metadata is incomplete: {row.get('scenario')}")
    # A unique ELF and activation store identify the row, but do not by
    # themselves establish the scenario's intended behavior. Enforce a
    # compact family-specific event predicate for the 48 directed cases.
    for row in directed:
        name = row["scenario"]
        events = directed_events[name]
        kinds = [event.get("kind", "") for event in events]
        family = row.get("family", "")
        case = name.rsplit("_", 1)[-1]
        if family == "cpu_rv32m":
            submit = next((event for event in events if event.get("kind") == "SUBMIT"), None)
            complete = next((event for event in events if event.get("kind") == "COMPLETE"), None)
            m_retired_during_dma = any(
                event.get("kind") == "RETIRE" and
                (int(event.get("insn", "0"), 16) & 0x7f) == 0x33 and
                ((int(event.get("insn", "0"), 16) >> 25) & 0x7f) == 1 and submit and complete and
                int(submit["cycle"]) < int(event["cycle"]) < int(complete["cycle"])
                for event in events)
            if not m_retired_during_dma:
                raise SystemExit(f"{name}: no actual RV32M retirement occurred during an accepted DMA lifetime")
        elif family == "apb_axi":
            required = ("APB", "AXI_AR", "AXI_R", "AXI_AW", "AXI_W", "AXI_B")
            if any(kind not in kinds for kind in required):
                raise SystemExit(f"{name}: directed APB/AXI transaction scenario did not reach all required channel events")
            if case == "1":
                # This row deliberately advertises PREADY during APB setup.
                # The transfer must still occur only in ACCESS, with one
                # matching APB completion for each setup sequence.
                setups = [event for event in events if event.get("kind") == "APB_SETUP"]
                accesses = [event for event in events if event.get("kind") == "APB"]
                setup_ops = {event.get("op") for event in setups if event.get("pready") == "1" and
                             event.get("penable") == "0"}
                access_ops = {event.get("op") for event in accesses}
                if not setup_ops or not setup_ops.issubset(access_ops) or len(accesses) != len(set(access_ops)):
                    raise SystemExit(f"{name}: setup-PREADY stress lacked one-to-one ACCESS completion evidence")
            elif case == "2":
                waited_reads = [event for event in events if event.get("kind") == "APB" and
                                event.get("write") == "0" and int(event.get("wait_cycles", "0")) > 0]
                waited_writes = [event for event in events if event.get("kind") == "APB" and
                                 event.get("write") == "1" and int(event.get("wait_cycles", "0")) > 0]
                if not waited_reads or not waited_writes:
                    raise SystemExit(f"{name}: waited APB read and write were not both observed")
        elif family == "queues_configuration":
            from check_crossover_scenario_intents import qualify
            if qualify(name,row,events).get("scenario_intent_status")!="PASS":
                raise SystemExit(f"{name}: exact queue/configuration contract did not reproduce")
        elif family == "translation_recovery":
            from check_crossover_scenario_intents import qualify
            if qualify(name,row,events).get("scenario_intent_status")!="PASS":
                raise SystemExit(f"{name}: exact translation/recovery contract did not reproduce")
        elif family == "interrupts":
            from check_crossover_scenario_intents import qualify
            if qualify(name,row,events).get("scenario_intent_status")!="PASS":
                raise SystemExit(f"{name}: exact interrupt timing/acknowledgement contract did not reproduce")
        elif family == "cache_ownership":
            if row.get("cache") != "1" or "MAINT_START" not in kinds or "MAINT_DONE" not in kinds:
                raise SystemExit(f"{name}: cached ownership handoff lacks real cache maintenance events")
        elif family == "reset_transport":
            resets = [event for event in events if event.get("kind") == "RESET_ASSERT"]
            releases = [event for event in events if event.get("kind") == "RESET_RELEASE"]
            if (not row.get("requested_reset_phase") or
                    row.get("reset_phase") != "event:" + row.get("requested_reset_phase", "") or
                    len(resets) != 1 or not releases or resets[0].get("epoch") != releases[-1].get("epoch") or
                    not any(int(resets[0].get(field, "0")) for field in
                            ("xlate_pending", "mem_pending", "ptw_pending", "host_aw_pending",
                             "host_w_pending", "host_ar_pending", "apb_active", "chip_busy", "maint_active",
                             "completion_pending"))):
                raise SystemExit(f"{name}: event-triggered reset did not cancel owned in-flight work and recover in the new epoch")
    # This row adds explicit response latency in the verification SRAM, which
    # is distinct from AW/W/AR request backpressure. Require the actual RTL
    # trace to show delayed B and R responses, not merely requested plusargs.
    response_wait_trace = next((row["trace"] for row in directed
                                if row.get("scenario") == "apb_axi__case_4"), "")
    if not response_wait_trace:
        raise SystemExit("missing directed response-wait scenario")
    response_events = load_trace_events(ROOT / response_wait_trace)
    read_waits: list[int] = []
    for ar in (event for event in response_events if event.get("kind") == "AXI_AR"):
        match = next((event for event in response_events if event.get("kind") == "AXI_R" and
                      event.get("epoch") == ar.get("epoch") and event.get("master") == ar.get("master") and
                      event.get("id") == ar.get("id") and event.get("addr") == ar.get("addr") and
                      int(event.get("cycle", "0")) >= int(ar.get("cycle", "0"))), None)
        if match and match.get("resp")=="0":
            read_waits.append(int(match["cycle"]) - int(ar["cycle"]))
    write_waits: list[int] = []
    # AXI4 W has no ID: associate it with accepted AW order on that master.
    pending_writes: dict[tuple[str, str], list[dict]] = {}
    for event in response_events:
        key = (event.get("epoch", ""), event.get("master", ""))
        queue = pending_writes.setdefault(key, [])
        if event.get("kind") == "AXI_AW":
            queue.append({"id": event["id"], "last_cycle": None})
        elif event.get("kind") == "AXI_W" and event.get("last") == "1":
            owner = next((item for item in queue if item["last_cycle"] is None), None)
            if owner is None:
                raise SystemExit("response-wait trace contains W without AW ownership")
            owner["last_cycle"] = int(event["cycle"])
        elif event.get("kind") == "AXI_B":
            owner = next((item for item in queue if item["id"] == event["id"]), None)
            if owner is None or owner["last_cycle"] is None:
                raise SystemExit("response-wait trace contains B before matching final W")
            if event.get("resp")=="0":
                write_waits.append(int(event["cycle"]) - owner["last_cycle"])
            queue.remove(owner)
    if any(pending_writes.values()):
        raise SystemExit("response-wait trace ended with outstanding writes")
    if not read_waits or min(read_waits) < 4 or not write_waits or min(write_waits) < 4:
        raise SystemExit(f"response-wait RTL scenario failed to realize delayed B/R: B={write_waits[:4]}, R={read_waits[:4]}")
    if len(random_replay) != 100 or len({row.get("trace") for row in random_replay}) != 100:
        raise SystemExit(f"seeded replay must contain 100 unique RTL traces, found {len(random_replay)}")
    random_seeds = {int(row["seed"]) for row in random_replay if row.get("seed", "").isdigit()}
    if len(random_seeds) != 100:
        raise SystemExit("seeded replay does not contain 100 distinct recorded seeds")
    required_schedule_columns = {
        "schedule_class", "requested_fault_mode", "requested_reset_phase", "combined_host",
        "realized_error_responses", "realized_completion_events", "realized_service_overlap_events",
        "requested_completion_pop_wait_cycles", "realized_completion_pop_wait_cycles",
    }
    missing_schedule_fields = required_schedule_columns - set(random_replay[0])
    if missing_schedule_fields:
        raise SystemExit(f"seeded replay is a configuration-only report; missing runtime schedule fields: {sorted(missing_schedule_fields)}")
    schedule_classes = {row.get("schedule_class") for row in random_replay}
    if not {"fault_recovery", "reset_injection", "combined_service", "cache_ownership", "backpressure_irq_mixed"}.issubset(schedule_classes):
        raise SystemExit(f"runtime schedule family lacks required schedule classes: {sorted(schedule_classes)}")
    stall_levels = {int(row["requested_axi_stall_percent"]) for row in random_replay
                    if row.get("requested_axi_stall_percent", "").isdigit()}
    if stall_levels != {0, 25, 50, 75}:
        raise SystemExit(f"seeded replay did not apply all requested AXI stall levels: {sorted(stall_levels)}")
    for row in random_replay:
        if int(row.get("requested_axi_stall_percent", "0")) and int(row.get("realized_axi_wait_events", "0")) == 0:
            raise SystemExit(f"seed {row.get('seed')} requested stalls but realized none")
        if row.get("isa") == "rv32im_zicsr" and int(row.get("realized_m_retires", "0")) == 0:
            raise SystemExit(f"seed {row.get('seed')} enabled RV32M but retired no M instruction")
        if row.get("completion_mode") == "irq" and (
                int(row.get("realized_irq_events", "0")) == 0 or
                int(row.get("realized_interrupt_retires", "0")) == 0):
            raise SystemExit(f"seed {row.get('seed')} requested IRQ mode without observed IRQ delivery")
        if row.get("requested_fault_mode") not in ("", "none") and int(row.get("realized_error_responses", "0")) == 0:
            raise SystemExit(f"seed {row.get('seed')} requested a fault but no error response was observed")
        if row.get("requested_reset_phase") not in ("", "none"):
            if not row.get("reset_phase", "").startswith("event:") or int(row.get("realized_reset_epochs", "0")) < 2:
                raise SystemExit(f"seed {row.get('seed')} requested reset at {row.get('requested_reset_phase')} but did not reach and recover from it")
        if row.get("combined_host") == "1" and int(row.get("realized_service_overlap_events", "0")) == 0:
            raise SystemExit(f"seed {row.get('seed')} enabled the combined host but observed no measured service overlap")
        if not row.get("scenario") or not row.get("requested_axi_stall_percent") or not row.get("realized_axi_wait_events"):
            raise SystemExit(f"seeded replay {row.get('trace')} lacks joined stimulus provenance")
    publish_pop_seed = next((row for row in random_replay if row.get("scenario") == "seed_099"), None)
    if not publish_pop_seed or publish_pop_seed.get("status") != "PASS" or \
            publish_pop_seed.get("requested_completion_pop_wait_cycles") != "5" or \
            publish_pop_seed.get("realized_completion_pop_wait_cycles") != "5":
        raise SystemExit("seeded publish/pop schedule lacks its requested and realized APB wait-state provenance")
    seed99_trace = trace_candidates = [
        ROOT / publish_pop_seed.get("trace", ""),
        ROOT / "build/protected_offload/shared_firmware" / publish_pop_seed.get("trace", ""),
    ]
    seed99_path = next((path for path in trace_candidates if path.is_file()), None)
    if seed99_path is None:
        raise SystemExit("seeded publish/pop trace is missing")
    seed99_events = load_trace_events(seed99_path)
    pop_cycles = {event.get("cycle") for event in seed99_events if event.get("kind") == "COMPLETE"}
    publish_cycles = {event.get("cycle") for event in seed99_events if event.get("kind") == "COMPLETE_PUBLISH"}
    pop_waits = [event for event in seed99_events if event.get("kind") == "APB" and
                 event.get("addr") == "4000002c" and event.get("write") == "1"]
    if not pop_cycles.intersection(publish_cycles) or not any(event_int(event, "wait_cycles") == 5 for event in pop_waits):
        raise SystemExit("seeded publish/pop trace does not show same-edge publish/pop and the five-cycle APB wait")
    if not CHIPLET_EXTERNAL_REPORT.exists():
        raise SystemExit(f"missing required external RV32IM oracle report: {CHIPLET_EXTERNAL_REPORT}")
    with CHIPLET_EXTERNAL_REPORT.open(newline="") as handle:
        external_rows = list(csv.DictReader(handle))
    if not external_rows:
        raise SystemExit("external RV32IM oracle report is empty")
    external_states = {row.get("status") for row in external_rows}
    if external_states != {"PASS"}:
        skipped = sum(row.get("status") == "SKIP" for row in external_rows)
        failed = sum(row.get("status") == "FAIL" for row in external_rows)
        raise SystemExit(f"external RV32IM oracle is not closed: PASS=0, SKIP={skipped}, FAIL={failed}; "
                         "missing Spike or skipped rows cannot satisfy release validation")
    if "rtl_m_instructions" not in external_rows[0]:
        raise SystemExit("external ISS report is stale or does not record executed RV32M instructions")
    external_im = [row for row in external_rows
                   if int(row.get("rtl_m_instructions", "0") or "0") > 0]
    if not external_im:
        raise SystemExit("external ISS report contains no executed RV32M instructions")
    external_bad = [row for row in external_im if row.get("status") != "PASS" or
                    row.get("rtl_status") != "PASS" or not row.get("matched_retires", "0").isdigit() or
                    int(row.get("matched_retires", "0")) == 0]
    if external_bad:
        states = sorted({row.get("status", "?") for row in external_bad})
        raise SystemExit(f"external RV32IM oracle has non-passing M-instruction rows: {states}; "
                         "SKIP cannot satisfy crossover release closure")
    if not CHIPLET_ACT_M_REPORT.exists():
        raise SystemExit(f"missing required ACT4 RV32IM RTL execution report: {CHIPLET_ACT_M_REPORT}")
    with CHIPLET_ACT_M_REPORT.open(newline="") as handle:
        act_m_rows = list(csv.DictReader(handle))
    if not act_m_rows or any(row.get("status") != "PASS" for row in act_m_rows):
        raise SystemExit("ACT4 RV32IM must have non-empty, all-PASS per-ELF RTL results")
    act_m_instruction_count = 0
    for row in act_m_rows:
        if not row.get("trace"):
            raise SystemExit(f"ACT4 RV32IM row has no retirement trace: {row.get('suite')}")
        trace = CHIPLET_ROOT / row["trace"]
        if not trace.is_file():
            raise SystemExit(f"ACT4 RV32IM retirement trace is missing: {trace}")
        with trace.open(newline="") as handle:
            for retire in csv.DictReader(handle):
                insn = int(retire.get("insn", "0"), 16)
                if (insn & 0x7f) == 0x33 and ((insn >> 25) & 0x7f) == 1:
                    act_m_instruction_count += 1
    if act_m_instruction_count == 0:
        raise SystemExit("ACT4/Sail report passed but no RV32M instruction retired in its RTL traces")
    # The 100 shared-workload rows do not substitute for the distinct CPU
    # instruction-stream random family required by the audit.
    instruction_streams = read("rv32m_instruction_stream_random.csv")
    require_all("rv32m_instruction_stream_random.csv", instruction_streams)
    if len(instruction_streams) != 100 or len({row.get("seed") for row in instruction_streams}) != 100:
        raise SystemExit("RV32M instruction-stream lane requires 100 unique seeds")
    opcode_fields = ("mul_retirements", "mulh_retirements", "mulhsu_retirements", "mulhu_retirements",
                     "div_retirements", "divu_retirements", "rem_retirements", "remu_retirements")
    for row in instruction_streams:
        if row.get("iss_status") != "PASS" or int(row.get("retirements", "0")) == 0:
            raise SystemExit(f"RV32M stream {row.get('scenario')} lacks architectural replay/retirement")
        if row.get("isa") != "rv32im_zicsr" or not row.get("cpu_stream_source_sha256"):
            raise SystemExit(f"RV32M stream {row.get('scenario')} lacks generated-source provenance")
        if int(row.get("realized_cpu_stream_retirements", "0")) < 200:
            raise SystemExit(f"RV32M stream {row.get('scenario')} executed fewer than 200 generated instructions")
        if int(row.get("realized_m_dma_overlap_events", "0")) == 0:
            raise SystemExit(f"RV32M stream {row.get('scenario')} did not overlap M execution with an active DMA")
        if any(not row.get(field, "").isdigit() or int(row[field]) == 0 for field in opcode_fields):
            raise SystemExit(f"RV32M stream {row.get('scenario')} did not execute all eight M opcodes")
    expected_names = {
        f"{family}__case_{index}" for family in (
            "cpu_rv32m", "apb_axi", "queues_configuration", "interrupts",
            "cache_ownership", "combined_services", "reset_transport")
        for index in range(1, 7)
    }
    expected_names.update({f"translation_recovery__fault_{index}" for index in range(1, 5)})
    expected_names.update({"translation_recovery__input_bus_error", "translation_recovery__case_6"})
    directed_names = {row.get("scenario") for row in directed}
    if directed_names != expected_names:
        raise SystemExit("directed matrix names do not match the versioned 48-scenario manifest")
    # The CPU family has scenario-specific architectural intent beyond the
    # common RV32M-during-DMA condition.  Require the intent checker to run on
    # each canonical trace, then resolve every cited event ID in that exact
    # trace.  A separate focused run is useful for debugging but cannot stand
    # in for release-matrix evidence.
    cpu_intents = {
        "m_result_to_address", "m_result_to_descriptor", "load_m_store_dependency",
        "m_result_to_branch", "device_irq_during_div", "reset_unconsumed_m_result",
    }
    cpu_rows = [row for row in directed if row.get("family") == "cpu_rv32m"]
    if len(cpu_rows) != 6 or {row.get("scenario_intent") for row in cpu_rows} != cpu_intents:
        raise SystemExit("canonical directed traces do not cover all six distinct CPU/RV32M intent programs")
    for row in cpu_rows:
        if row.get("scenario_intent_status") != "PASS" or not row.get("scenario_intent_event_ids") or \
                not row.get("scenario_active_dma_event_ids"):
            raise SystemExit(f"{row.get('scenario')}: architectural intent or active-DMA witness is missing")
        events = directed_events[row["scenario"]]
        by_id = {event.get("eid"): event for event in events}
        intent_ids = row["scenario_intent_event_ids"].split(";")
        overlap_ids = row["scenario_active_dma_event_ids"].split(";")
        if any(event_id not in by_id for event_id in intent_ids + overlap_ids):
            raise SystemExit(f"{row.get('scenario')}: intent report cites an event absent from its canonical trace")
        # Re-run the independent intent recognizer against the current trace;
        # this catches stale PASS fields even when a trace filename is reused.
        from check_cpu_crossover_intents import qualify as qualify_cpu_intent
        qualified = qualify_cpu_intent(row["scenario"], events)
        if qualified.get("scenario_intent_status") != "PASS" or \
                qualified.get("scenario_intent") != row.get("scenario_intent") or \
                qualified.get("scenario_intent_event_ids") != row.get("scenario_intent_event_ids") or \
                qualified.get("scenario_active_dma_event_ids") != row.get("scenario_active_dma_event_ids"):
            raise SystemExit(f"{row.get('scenario')}: canonical trace does not reproduce its reported CPU intent")
    # Every one of the 48 rows must prove its named behavior using the
    # executable observer trace. A unique ELF activation proves which program
    # ran; this separate contract proves what that program actually exercised.
    from check_crossover_scenario_intents import qualify as qualify_scenario_intent
    intent_names: dict[str, set[str]] = {}
    for row in directed:
        name = row["scenario"]
        events = directed_events[name]
        if row.get("scenario_intent_status") != "PASS" or not row.get("scenario_intent") or \
                not row.get("scenario_intent_event_ids") or not row.get("scenario_active_dma_event_ids"):
            raise SystemExit(f"{name}: scenario intent was not qualified from trace events")
        by_id = {event.get("eid"): event for event in events}
        cited = row["scenario_intent_event_ids"].split(";") + row["scenario_active_dma_event_ids"].split(";")
        if any(not event_id or event_id not in by_id for event_id in cited):
            raise SystemExit(f"{name}: intent cites an event identifier absent from its trace")
        if row.get("family") == "cpu_rv32m":
            qualified = qualify_cpu_intent(name, events)
            if qualified.get("scenario_intent") != row["scenario_intent"] or \
                    qualified.get("scenario_intent_status") != "PASS" or \
                    qualified.get("scenario_intent_event_ids") != row["scenario_intent_event_ids"] or \
                    qualified.get("scenario_active_dma_event_ids") != row["scenario_active_dma_event_ids"]:
                raise SystemExit(f"{name}: CPU architectural intent report does not reproduce from the trace")
        else:
            qualified = qualify_scenario_intent(name, row, events)
            if qualified.get("scenario_intent") != row["scenario_intent"] or \
                    qualified.get("scenario_intent_status") != "PASS" or \
                    qualified.get("scenario_intent_event_ids") != row["scenario_intent_event_ids"]:
                raise SystemExit(f"{name}: subsystem intent report does not reproduce from the trace")
        intent_names.setdefault(row.get("family", ""), set()).add(row["scenario_intent"])
    if set(intent_names) != {"cpu_rv32m", "apb_axi", "queues_configuration", "translation_recovery",
                            "interrupts", "cache_ownership", "combined_services", "reset_transport"}:
        raise SystemExit("scenario-intent report does not cover all eight integration families")
    required_intent_counts = json.loads(MANIFEST.read_text()).get("required_scenario_intent_counts", {})
    required_scenario_intents = json.loads(MANIFEST.read_text()).get("required_scenario_intents", {})
    if len(required_scenario_intents) != 48 or len(set(required_scenario_intents.values())) != 48:
        raise SystemExit("scenario-intent manifest must enumerate all 48 distinct original crossover contracts")
    by_scenario = {row["scenario"]: row for row in directed}
    for scenario, expected_intent in required_scenario_intents.items():
        if scenario not in by_scenario or by_scenario[scenario].get("scenario_intent") != expected_intent:
            observed = by_scenario.get(scenario, {}).get("scenario_intent", "MISSING")
            raise SystemExit(f"{scenario}: expected {expected_intent}, observed {observed}; required behavior lacks an exact trace witness")
    if set(required_intent_counts) != set(intent_names):
        raise SystemExit("scenario-intent manifest must declare a unique-intent denominator for every family")
    aliased = {family: (len(intents), required_intent_counts[family])
               for family, intents in intent_names.items()
               if len(intents) != required_intent_counts[family]}
    if aliased:
        raise SystemExit("scenario families alias named behaviors instead of qualifying each case distinctly: " +
                         ", ".join(f"{family}={actual}/{required}" for family, (actual, required) in aliased.items()))
    for name, rows in (("compute_crossover_model.csv", replay),
                       ("compute_crossover_random_model.csv", random_replay)):
        incomplete = [row.get("trace", "?") for row in rows
                      if row.get("iss_status") != "PASS"
                      or row.get("iss_instructions") != row.get("retirements")
                      or row.get("accelerator_outputs_checked") != row.get("accelerator_commands")]
        if incomplete:
            raise SystemExit(f"{name}: ISS or independent accelerator numerical replay missing/incomplete: {incomplete[:4]}")
    if len(directed) != 48:
        raise SystemExit(f"directed crossover requires 48 rows, found {len(directed)}")
    formal = read("protected_offload_formal.csv")
    require_all("protected_offload_formal.csv", formal)
    required_formal = {"tag_lifetime", "configuration_reference_lifetime", "completion_after_write_drain",
                       "invalidation_submission_arbitration", "irq_set_dominates_ack", "reset_cancels_owned_work"}
    formal_by_name = {row.get("property"): row for row in formal}
    if not required_formal.issubset(formal_by_name):
        raise SystemExit("protected-offload formal evidence lacks a required crossover property")
    formal_source_digest = hashlib.sha256()
    formal_root = ROOT / "integration/protected_offload/formal"
    for source in sorted(list(formal_root.glob("*.sv")) + list(formal_root.glob("*.sby")) +
                         list((ROOT / "integration/protected_offload/rtl").glob("*.sv"))):
        formal_source_digest.update(str(source.relative_to(ROOT)).encode())
        formal_source_digest.update(source.read_bytes())
    for name in required_formal:
        row = formal_by_name[name]
        if row.get("status") != "PASS" or row.get("cover") != "REACHABLE" or \
                "solver" not in row.get("mode", "") or int(row.get("depth", "0")) <= 0 or \
                int(row.get("cover_depth", "0")) <= 0:
            raise SystemExit(f"protected-offload formal property lacks solver safety and solver cover evidence: {name}")
        if row.get("source_harness_sha256") != formal_source_digest.hexdigest():
            raise SystemExit(f"protected-offload formal property uses stale RTL/harness sources: {name}")
    mutation = read("protected_offload_integration_mutations.csv")
    mutation_names = {row.get("mutation") for row in mutation}
    if mutation_names != AUDIT_MUTATIONS or len(mutation) != len(AUDIT_MUTATIONS):
        raise SystemExit(f"audit mutation matrix mismatch; missing={sorted(AUDIT_MUTATIONS-mutation_names)}; extra={sorted(mutation_names-AUDIT_MUTATIONS)}")
    if any(row.get("status") != "DETECTED" for row in mutation):
        raise SystemExit("one or more crossover mutations were not detected")
    if any(row.get("activated") != "true" or row.get("detection") in ("", "none", "generic") or
           row.get("detection") != row.get("expected_failure") for row in mutation):
        raise SystemExit("mutation matrix includes an inactive mutation or a failure outside its designated bucket")
    if any(row.get("compile_status") != "PASS" or row.get("nominal_control") != "PASS" for row in mutation):
        raise SystemExit("mutation row lacks successful mutant compilation and a passing nominal control")
    host = read("compute_host_evidence.csv")
    if {row.get("scenario") for row in host} != {"combined_k4_b1", "combined_k16_b4"}:
        raise SystemExit("combined-host evidence must contain K4/B1 and K16/B4")
    require_all("compute_host_evidence.csv", host)
    if not any(int(row.get("overlap_events", "0")) > 0 for row in host):
        raise SystemExit("combined-host traces do not demonstrate measured accelerator/chiplet overlap")
    if not any(row.get("scenario") == "combined_k16_b4" and int(row.get("overlap_events", "0")) > 0 for row in host):
        raise SystemExit("K16/B4 combined workload did not demonstrate measured overlap")
    error_context = read("protected_error_context.csv")
    reset_context = read("protected_reset_context.csv")
    required_reset_phases = {"ptw_req", "mem_req", "mem_rsp", "apb_wait", "completion", "host_w_wait"}
    observed_reset_phases = {row.get("reset_phase", "") for row in reset_context}
    if len(error_context) != 4 or len(reset_context) != len(required_reset_phases) or observed_reset_phases != required_reset_phases:
        raise SystemExit(
            "context reports require four fault rows and one reset row for each phase "
            f"{sorted(required_reset_phases)}; got {len(error_context)} fault rows and "
            f"reset phases {sorted(observed_reset_phases)}"
        )
    require_all("protected_error_context.csv", error_context)
    require_all("protected_reset_context.csv", reset_context)
    if any(row.get("phase_reached") != "true" or int(row.get("epochs", "0")) < 2 for row in reset_context):
        raise SystemExit("a reset-context row lacks event-triggered phase/epoch evidence")
    if not any(row.get("scenario") == "partial_output_repair_retry" and row.get("pre_retry_snapshot") == "0000000010101010" and row.get("vectors_done") == "1;2" for row in error_context):
        raise SystemExit("partial-output recovery lacks the committed-prefix/pre-retry memory evidence")
    coverage = read("compute_crossover_coverage.csv")
    required = [row for row in coverage if row.get("point_type") == "required_predicate"]
    required_events = [row for row in coverage if row.get("point_type") == "event"]
    coverage_manifest = json.loads(MANIFEST.read_text())
    expected_predicates = set(coverage_manifest.get("required_predicates", []))
    actual_predicates = [row.get("point", "") for row in required]
    expected_events = set(coverage_manifest.get("required_events", []))
    actual_events = [row.get("point", "") for row in required_events]
    if (not expected_predicates or set(actual_predicates) != expected_predicates or
            len(actual_predicates) != len(expected_predicates)):
        raise SystemExit(f"required predicate report differs from manifest: missing={sorted(expected_predicates-set(actual_predicates))}; extra={sorted(set(actual_predicates)-expected_predicates)}")
    if (set(actual_events) != expected_events or len(actual_events) != len(expected_events)):
        raise SystemExit(f"required observer event report differs from manifest: missing={sorted(expected_events-set(actual_events))}; extra={sorted(set(actual_events)-expected_events)}")
    if any(row.get("status") != "PASS" for row in required + required_events):
        raise SystemExit("a manifest-required crossover predicate or event is not reached in executable RTL evidence")
    crosses = read("compute_crossover_cross_coverage.csv")
    cross_manifest = json.loads(MANIFEST.read_text())
    required_cross_families = set(cross_manifest["required_cross_families"])
    required_cross_bins = {(family, bin_name) for family, bins in cross_manifest["required_cross_bins"].items()
                           for bin_name in bins}
    observed_cross_bins = {(row.get("cross_family", ""), row.get("bin", "")) for row in crosses}
    if observed_cross_bins != required_cross_bins:
        raise SystemExit(f"transaction cross denominator differs from the reviewed manifest: missing={sorted(required_cross_bins-observed_cross_bins)}; extra={sorted(observed_cross_bins-required_cross_bins)}")
    observed_cross_families = {row.get("cross_family") for row in crosses if row.get("status") == "PASS"}
    if not required_cross_families.issubset(observed_cross_families):
        raise SystemExit(f"transaction cross coverage missing required families: {sorted(required_cross_families-observed_cross_families)}")
    if not crosses or any(row.get("point_type") != "cross_bin" or row.get("status") != "PASS" or
                          not row.get("witness_event_ids") or not row.get("contributing_tests") for row in crosses):
        raise SystemExit("transaction-correlated crossover cross-bin evidence is missing or incomplete")
    if any(int(row.get("independent_test_count", "0")) < 2 for row in crosses
           if row.get("risk") in {"retirement", "ownership", "permission", "recovery"}):
        raise SystemExit("a high-risk crossover bin lacks two independent contributing tests")
    expected_manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    cross_generator = ROOT / "integration/protected_offload/scripts/generate_crossover_cross_coverage.py"
    from stimulus_provenance import cross_generator_hash
    expected_cross_generator_hash = cross_generator_hash()
    trace_event_cache: dict[Path, dict[str, dict[str, str]]] = {}
    stream_replay = read("rv32m_instruction_stream_random_model.csv")
    if (len(stream_replay) != 100 or len({row.get("seed") for row in stream_replay}) != 100 or
            any(row.get("status") != "PASS" or row.get("iss_status") != "PASS" or
                row.get("stimulus_origin") != "generated_cpu_instruction_stream" or
                not row.get("stimulus_generator_sha256") or not row.get("stimulus_instance_sha256") or
                row.get("stimulus_abi_status") != "PASS" or
                int(row.get("realized_m_nonzero_operand_ops", "0")) < 20 or
                int(row.get("realized_branch_taken", "0")) == 0 or
                int(row.get("realized_branch_not_taken", "0")) == 0 or
                int(row.get("realized_shift_0", "0")) == 0 or
                int(row.get("realized_shift_1", "0")) == 0 or
                int(row.get("realized_shift_31", "0")) == 0
                for row in stream_replay)):
        raise SystemExit("RV32M streams must be 100/100 ISS-checked with ABI preservation, nonzero operands, both branch outcomes, and realized shifts 0/1/31")
    independent_runs = read("compute_crossover_independent.csv")
    independent_replay = read("compute_crossover_independent_model.csv")
    require_all("compute_crossover_independent.csv", independent_runs)
    require_all("compute_crossover_independent_model.csv", independent_replay)
    if (len(independent_runs) != 19 or len(independent_replay) != 19 or
            {row.get("scenario") for row in independent_runs} !=
            {row.get("scenario") for row in independent_replay}):
        raise SystemExit("independent firmware requires 19 matching execution/replay rows")
    independent_source = ROOT / "integration/protected_offload/firmware/independent_offload.c"
    independent_hash = hashlib.sha256(independent_source.read_bytes()).hexdigest()
    for row in independent_replay:
        if (row.get("stimulus_origin") != "independent_firmware_driver" or
                row.get("stimulus_generator_sha256") != independent_hash or
                row.get("iss_status") != "PASS" or
                row.get("iss_instructions") != row.get("retirements") or
                row.get("accelerator_outputs_checked") != row.get("accelerator_commands")):
            raise SystemExit(f"independent firmware replay/provenance incomplete: {row.get('scenario')}")
        trace = ROOT / row["trace"]
        if not trace.is_file():
            trace = ROOT / "build/protected_offload/shared_firmware" / row["trace"]
        if not trace.is_file() or hashlib.sha256(trace.read_bytes()).hexdigest() != row.get("trace_sha256"):
            raise SystemExit(f"independent firmware trace missing/stale: {row.get('scenario')}")
        result = replay_trace(trace, strict_schema=True)
        if result.get("status") != "PASS":
            raise SystemExit(f"independent firmware strict replay failed: {row.get('scenario')}")
    trace_hashes = {row.get("trace", ""): row.get("trace_sha256", "")
                    for row in replay + random_replay + stream_replay + independent_replay}
    for row in crosses:
        if (row.get("manifest_sha256") != expected_manifest_hash or
                row.get("generator_sha256") != expected_cross_generator_hash):
            raise SystemExit(f"stale cross-coverage provenance for {row.get('cross_family')}:{row.get('bin')}")
        trace_name = row.get("first_trace", "")
        trace_candidates = [ROOT / trace_name, ROOT / "build/protected_offload/shared_firmware" / trace_name]
        first_trace_path = next((path for path in trace_candidates if path.is_file()), None)
        if first_trace_path is None:
            raise SystemExit(f"cross witness trace is missing for {row.get('cross_family')}:{row.get('bin')}")
        trace_digest = hashlib.sha256(first_trace_path.read_bytes()).hexdigest()
        if trace_digest != row.get("first_trace_sha256"):
            raise SystemExit(f"cross witness trace hash is stale for {row.get('cross_family')}:{row.get('bin')}")
        witness_refs = row.get("witness_event_ids", "").split(";")
        if not witness_refs or any("#" not in ref for ref in witness_refs):
            raise SystemExit(f"cross witness lacks trace-qualified event IDs for {row.get('cross_family')}:{row.get('bin')}")
        current_witness: list[dict[str, str]] = []
        for ref in witness_refs:
            trace_name, event_id = ref.rsplit("#", 1)
            trace_candidates = [ROOT / trace_name, ROOT / "build/protected_offload/shared_firmware" / trace_name]
            trace_path = next((path for path in trace_candidates if path.is_file()), None)
            if not event_id.isdigit() or trace_path is None:
                raise SystemExit(f"invalid cross witness reference: {ref}")
            expected_trace_hash = trace_hashes.get(trace_name)
            if not expected_trace_hash or hashlib.sha256(trace_path.read_bytes()).hexdigest() != expected_trace_hash:
                raise SystemExit(f"cross witness does not match a current strict-replay trace: {ref}")
            events = trace_event_cache.get(trace_path)
            if events is None:
                parsed: dict[str, dict[str, str]] = {}
                for event in load_trace_events(trace_path):
                    eid = event.get("eid", "")
                    if eid in parsed:
                        raise SystemExit(f"duplicate observer event ID {eid} in {trace_path}")
                    parsed[eid] = event
                events = trace_event_cache[trace_path] = parsed
            event = events.get(event_id)
            if event is None:
                raise SystemExit(f"cross witness event does not exist: {ref}")
            if event.get("kind", "") == "" or event.get("run", "") == "":
                raise SystemExit(f"cross witness points at an unnormalized event: {ref}")
            current_witness.append(event)
        first_refs = row.get("first_witness_event_ids", "").split(";")
        if not first_refs or any(ref not in witness_refs for ref in first_refs):
            raise SystemExit(f"cross bin lacks a dedicated first-hit witness: {row.get('cross_family')}:{row.get('bin')}")
        first_events = []
        for ref in first_refs:
            trace_name, event_id = ref.rsplit("#", 1)
            trace_path = ROOT / trace_name
            if not trace_path.is_file():
                trace_path = ROOT / "build/protected_offload/shared_firmware" / trace_name
            first_events.append(trace_event_cache[trace_path][event_id])
        validate_cross_witness(row, first_events, list(trace_event_cache[trace_path].values()))
        if row.get("first_event_ids") != witness_refs[0]:
            raise SystemExit(f"first witness event does not match cross hit provenance for {row.get('cross_family')}:{row.get('bin')}")
    tag_mutation = read("protected_offload_tag_lifetime_mutation.csv")
    if len(tag_mutation) != 2 or tag_mutation[0].get("status") != "PASS" or tag_mutation[1].get("status") != "DETECTED" or tag_mutation[1].get("detection") != "tag_lifetime_checker":
        raise SystemExit("active descriptor tag-lifetime mutation/control evidence is absent or stale")
    code_cov = read("compute_crossover_code_coverage.csv")
    coverage_runs = read("compute_crossover_code_coverage_runs.csv")
    if len(coverage_runs) != 257 or len({row.get("scenario") for row in coverage_runs}) != 257:
        raise SystemExit("coverage requires 257 unique execution-bound run manifests")
    coverage_versions = set()
    for row in coverage_runs:
        case = (ROOT / row["trace"]).parent
        manifest_path = case / "coverage_provenance.json"
        if not manifest_path.is_file():
            raise SystemExit(f"coverage provenance missing for {row.get('scenario')}")
        version = json.loads(manifest_path.read_text()).get("simulator_version", "")
        if "5.049" not in version:
            raise SystemExit(f"coverage database was not generated by pinned Verilator: {row.get('scenario')}")
        coverage_versions.add(version)
        try:
            validate_manifest(ROOT, case, row, version)
        except (OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
    if len(coverage_versions) != 1:
        raise SystemExit("coverage aggregates different simulator builds")
    integrated = next((row for row in code_cov if row.get("scope") == "integrated_protected_offload_and_rv32"), None)
    control = next((row for row in code_cov if row.get("scope") == "new_protected_offload_control_rtl"), None)
    if not integrated or not control:
        raise SystemExit("raw integrated and scoped protected-control code coverage reports are both required")
    if integrated.get("branch_percent") == "NA" or control.get("branch_percent") == "NA":
        raise SystemExit("required native branch coverage is unavailable; release closure cannot claim the 90% target")
    if float(control.get("line_percent", "0")) < 95 or float(control.get("branch_percent", "0")) < 90:
        raise SystemExit("new protected-control RTL is below 95% raw line / 90% raw branch coverage")
    if int(control.get("reviewed_branch_exclusions", "-1")) < 0 or \
            not (ROOT / "reports/compute_crossover_code_coverage_exclusions.csv").is_file():
        raise SystemExit("reviewed coverage exclusions are missing or malformed")
    current_hashes = {
        "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "directed_report_sha256": hashlib.sha256((REPORTS / "compute_crossover_directed.csv").read_bytes()).hexdigest(),
        "generator_sha256": hashlib.sha256(COVERAGE_GENERATOR.read_bytes()).hexdigest(),
    }
    for row in coverage:
        for field, expected in current_hashes.items():
            if row.get(field) != expected:
                raise SystemExit(f"stale {field} in coverage point {row.get('point')}")
    for row in replay + random_replay:
        trace = row.get("trace", "")
        candidates = [ROOT / trace, ROOT / "build/protected_offload/shared_firmware" / trace]
        source = next((path for path in candidates if path.exists()), None)
        if not trace or source is None:
            raise SystemExit(f"replay row has no trace-backed evidence: {trace}")
        current = replay_trace(source, strict_schema=True)
        if current.get("status") != "PASS":
            raise SystemExit(f"current trace replay failed for {trace}: {current.get('errors')}")
        for field in ("trace_sha256", "firmware_sha256", "data_sha256", "manifest_sha256",
                      "checker_sha256", "source_sha256", "iss_instructions",
                      "accelerator_outputs_checked", "retirements", "accelerator_commands"):
            if str(row.get(field, "")) != str(current.get(field, "")):
                raise SystemExit(f"stale {field} in replay row for {trace}")
    print(f"PROTECTED_CROSSOVER_RELEASE|status=PASS|directed={len(directed)}|"
          f"replay={len(replay)}|random={len(random_replay)}|mutations={len(mutation)}|"
          f"host={len(host)}|fault_context={len(error_context)}|reset_context={len(reset_context)}|"
          f"predicates={len(required)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
