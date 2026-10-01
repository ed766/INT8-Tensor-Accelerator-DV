#!/usr/bin/env python3
"""Qualification tests for the crossover replay checker.

The suite includes valid controls and intentionally malformed traces.  It is
kept independent of Verilator so a checker regression cannot be hidden by a
passing DUT simulation.
"""
from __future__ import annotations

import importlib.util
import csv
import hashlib
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = Path(__file__).with_name("check_crossover_trace.py")
spec = importlib.util.spec_from_file_location("crossover_checker", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(checker)


def event(kind: str, eid: int, epoch: str = "0", **fields: str) -> dict[str, str]:
    result = {"schema": "3", "eid": str(eid), "run": "checker-selftest", "build": "selftest-build",
              "epoch": epoch,
              "cycle": str(eid), "kind": kind}
    if kind == "RETIRE":
        result.update({
            "pc": "00000000", "next_pc": "00000004", "insn": "00000013",
            "retire_order": "0", "trap": "0", "intr": "0",
            "rs1_addr": "0", "rs1_data": "00000000", "rs2_addr": "0", "rs2_data": "00000000",
            "rd_addr": "0", "rd_data": "00000000", "mem_addr": "00000000",
            "mem_rmask": "0", "mem_wmask": "0", "mem_rdata": "00000000",
            "mem_wdata": "00000000", "mstatus": "00000000", "mie": "00000000",
            "mtvec": "00000000", "mscratch": "00000000", "mepc": "00000000",
            "mcause": "00000000", "mtval": "00000000",
        })
    if kind == "SUBMIT":
        result.update({"input_iova": "10000000", "output_iova": "10000004",
                       "input_stride": "4", "output_stride": "4", "k": "4",
                       "batch": "1", "bank": "0", "generation": "0"})
    if kind == "ACCEL_CMD": result.update({"bank": "0", "k": "4"})
    if kind in ("ACCEL_IN", "ACCEL_OUT"): result["vector"] = "0"
    if kind in ("APB_SETUP", "APB"): result["wdata"] = "00000000"
    result.update(fields)
    return result


def run(trace: list[dict[str, str]], strict_schema: bool = False) -> dict[str, str]:
    original = checker.events
    checker.events = lambda _path: trace
    try:
        return checker.check(ROOT / "build" / "checker-selftest" / "trace.log",
                             strict_schema=strict_schema)
    finally:
        checker.events = original


def test_iss_register_sensitivity() -> list[str]:
    """Prove actual RVFI destination values are independently predicted."""
    with tempfile.TemporaryDirectory(prefix="crossover_iss_selftest_") as tmp:
        case = Path(tmp)
        (case / "firmware.hex").write_text("00100093\n00108113\n")
        (case / "data.hex").write_text("")
        base = {
            "epoch": "0", "trap": "0", "intr": "0", "rs2_addr": "0",
            "rs2_data": "00000000", "mem_addr": "00000000",
            "mem_rmask": "0", "mem_wmask": "0", "mem_rdata": "00000000",
            "mem_wdata": "00000000", "mstatus": "00001800", "mie": "00000000",
            "mtvec": "00000300", "mscratch": "00000000", "mepc": "00000000",
            "mcause": "00000000", "mtval": "00000000", "irq_level": "0",
            "irq_timer_level": "0", "m_ext": "0",
        }
        rows = [
            dict(base, retire_order="0", pc="00000000", next_pc="00000004",
                 insn="00100093", rs1_addr="0", rs1_rdata="00000000",
                 rd_addr="1", rd_data="00000001"),
            dict(base, retire_order="1", pc="00000004", next_pc="00000008",
                 insn="00108113", rs1_addr="1", rs1_data="00000001",
                 rd_addr="2", rd_data="00000002"),
        ]
        good = checker.check_architecture(
            [{"kind": "RETIRE", **row} for row in rows], case / "crossover.trace")
        bad_rows = [dict(row) for row in rows]
        bad_rows[1]["rd_data"] = "00000003"
        bad = checker.check_architecture(
            [{"kind": "RETIRE", **row} for row in bad_rows], case / "crossover.trace")
        failures = []
        if good:
            failures.append("valid CPU retirement control rejected: " + "; ".join(good))
        if not any("rd value" in error for error in bad):
            failures.append("corrupt destination-register result was not detected")
        return failures


def main() -> int:
    valid = [
        event("RESET_RELEASE", 0),
        event("RETIRE", 1, pc="00000000", insn="00000013", retire_order="0"),
        event("MEM_REQ", 2, txn="0", write="1", tag="7", addr="10000000",
              wdata="11223344", wstrb="f", vector="0"),
        event("MEM_RSP", 3, txn="0", write="1", tag="7", addr="10000000",
              wdata="11223344", wstrb="f", vector="0", error="0", committed="1"),
        event("SUBMIT", 4, tag="7", seq="0", asid="1"),
        event("ACCEL_CMD", 5, tag="7", bank="0", k="4"),
        event("ACCEL_IN", 6, tag="7", data="00000000"),
        event("ACCEL_OUT", 7, tag="7", data="00000000"),
        event("COMPLETE_PUBLISH", 8, tag="7", asid="1", status="0", vectors_done="1"),
        event("COMPLETE", 9, tag="7", asid="1", status="0", vectors_done="1"),
        event("APB_SETUP", 10, op="0", write="1", addr="40000010"),
        event("APB", 11, op="0", write="1", addr="40000010", error="0", wait_cycles="0"),
        event("FIRMWARE_DONE", 12),
    ]
    cases = {
        "valid_control": (valid, False),
        "mailbox_without_work": ([event("FIRMWARE_DONE", 0)], True),
        "duplicate_completion": (valid[:4] + [event("COMPLETE", 4, tag="7"), event("COMPLETE", 5, tag="7"), event("FIRMWARE_DONE", 6)], True),
        "completion_after_reset": ([event("SUBMIT", 0, tag="7", seq="0", asid="1"),
                                     event("MEM_REQ", 1, txn="8", write="0", tag="7", addr="10000000",
                                           wdata="00000000", wstrb="0", vector="0"),
                                     event("RESET_ASSERT", 2, mem_pending="1", xlate_pending="0",
                                           ptw_pending="0", host_aw_pending="0", host_w_pending="0",
                                           host_ar_pending="0", apb_active="0", maint_active="0",
                                           completion_pending="0"),
                                     event("RESET_RELEASE", 3, epoch="1"),
                                     event("COMPLETE", 4, epoch="1", tag="7"),
                                     event("FIRMWARE_DONE", 5, epoch="1")], True),
        "missing_completion": ([event("SUBMIT", 0, tag="7", seq="0"), event("FIRMWARE_DONE", 1)], True),
        "output_before_command": ([event("SUBMIT", 0, tag="7", seq="0"),
                                    event("ACCEL_OUT", 1, tag="7", data="00000000"),
                                    event("FIRMWARE_DONE", 2)], True),
        "wrong_asid": ([event("RESET_RELEASE", 0), event("SUBMIT", 1, tag="7", seq="0", asid="1"),
                        event("ACCEL_CMD", 2, tag="7", bank="0", k="4"),
                        event("ACCEL_IN", 3, tag="7", data="00000000"),
                        event("ACCEL_OUT", 4, tag="7", data="00000000"),
                        event("COMPLETE_PUBLISH", 5, tag="7", asid="2", status="0", vectors_done="1"),
                        event("COMPLETE", 6, tag="7", asid="2", status="0", vectors_done="1"),
                        event("FIRMWARE_DONE", 7)], True),
        "completion_before_write_drain": ([event("SUBMIT", 0, tag="7", seq="0"),
                                             event("ACCEL_CMD", 1, tag="7", bank="0", k="4"),
                                             event("ACCEL_IN", 2, tag="7", data="00000000"),
                                             event("ACCEL_OUT", 3, tag="7", data="00000000"),
                                             event("MEM_REQ", 4, txn="9", write="1", tag="7", addr="10000000",
                                                   wdata="00000000", wstrb="f", vector="0"),
                                             event("COMPLETE_PUBLISH", 5, tag="7", asid="1", status="0",
                                                   vectors_done="1"),
                                             event("FIRMWARE_DONE", 6)], True),
        "post_done_activity": (valid + [event("RETIRE", 13, insn="00000013")], True),
        "unknown_transport_response": ([event("MEM_RSP", 0, txn="99", write="1", error="0"),
                                         event("FIRMWARE_DONE", 1)], True),
        "transport_id_mismatch": ([event("MEM_REQ", 0, txn="4", write="1", tag="7", addr="10000000",
                                          wdata="11223344", wstrb="f", vector="0"),
                                    event("MEM_RSP", 1, txn="5", write="1", tag="7", addr="10000000",
                                          wdata="11223344", wstrb="f", vector="0", error="0", committed="1"),
                                    event("FIRMWARE_DONE", 2)], True),
        "duplicate_retirement": ([event("RETIRE", 0, pc="00000000", insn="00000013", retire_order="0"),
                                   event("RETIRE", 1, pc="00000000", insn="00000013", retire_order="0"),
                                   event("SUBMIT", 2, tag="7", seq="0"),
                                   event("COMPLETE", 3, tag="7"), event("FIRMWARE_DONE", 4)], True),
        "completion_before_write_response": ([event("SUBMIT", 0, tag="7", seq="0", asid="1"),
                                                event("MEM_REQ", 1, txn="0", tag="7", asid="1", write="1",
                                                      addr="10000000", wdata="11223344", wstrb="f", vector="0"),
                                                event("COMPLETE_PUBLISH", 2, tag="7", asid="1", status="0", vectors_done="1"),
                                                event("FIRMWARE_DONE", 3)], True),
        "wrong_numerical_output": ([event("SUBMIT", 0, tag="7", seq="0"),
                                     event("ACCEL_CMD", 1, tag="7", bank="0", k="4"),
                                     event("ACCEL_IN", 2, tag="7", data="00000000"),
                                     event("ACCEL_OUT", 3, tag="7", data="00000001"),
                                     event("COMPLETE", 4, tag="7"), event("FIRMWARE_DONE", 5)], True),
        "missing_schema": ([{"eid": "0", "epoch": "0", "kind": "FIRMWARE_DONE"}], True),
    }
    bad_addr = [dict(item) for item in valid]
    bad_addr[2]["addr"] = "10000004"
    cases["memory_response_address_mismatch"] = (bad_addr, True)
    bad_payload = [dict(item) for item in valid]
    bad_payload[3]["wdata"] = "11223345"
    cases["memory_response_payload_mismatch"] = (bad_payload, True)
    cases["maintenance_missing_done"] = (valid[:-1] + [event("MAINT_START", 12), event("FIRMWARE_DONE", 13)], True)
    cases["maintenance_done_without_start"] = (valid[:-1] + [event("MAINT_DONE", 12), event("FIRMWARE_DONE", 13)], True)
    cases["valid_maintenance_control"] = (valid[:-1] + [event("MAINT_START", 12),
                                                           event("MAINT_DONE", 13),
                                                           event("FIRMWARE_DONE", 14)], False)
    cases["apb_access_without_setup"] = ([event("APB", 0, op="0", write="0", addr="40000000",
                                                error="0", wait_cycles="0"),
                                           event("SUBMIT", 1, tag="7", seq="0"),
                                           event("COMPLETE", 2, tag="7"),
                                           event("FIRMWARE_DONE", 3)], True)
    cases["valid_reset_control"] = ([event("RESET_ASSERT", 0, xlate_pending="0", mem_pending="0",
                                            ptw_pending="0", host_aw_pending="0", host_w_pending="0",
                                            host_ar_pending="0",
                                            apb_active="0", maint_active="0"),
                                     event("RESET_RELEASE", 1, epoch="1"),
                                     event("SUBMIT", 2, epoch="1", tag="8", seq="0", asid="3"),
                                     event("COMPLETE_PUBLISH", 3, epoch="1", tag="8", asid="3", status="0", vectors_done="1"),
                                     event("COMPLETE", 4, epoch="1", tag="8", asid="3", status="0", vectors_done="1"),
                                     event("FIRMWARE_DONE", 5, epoch="1")], False)
    cases["apb_orphan_after_reset"] = ([event("APB_SETUP", 0, op="0", write="1", addr="40000010"),
                                         event("RESET_ASSERT", 1, xlate_pending="0", mem_pending="0", ptw_pending="0",
                                               host_aw_pending="0", host_w_pending="0", host_ar_pending="0", apb_active="1",
                                               chip_busy="0", maint_active="0"),
                                         event("RESET_RELEASE", 2, epoch="1"),
                                         event("APB", 3, epoch="1", op="0", write="1", addr="40000010", error="0", wait_cycles="0"),
                                         event("SUBMIT", 4, tag="10", seq="0", asid="1"),
                                         event("COMPLETE_PUBLISH", 5, tag="10", asid="1", status="0", vectors_done="1"),
                                         event("COMPLETE", 6, tag="10", asid="1", status="0", vectors_done="1"),
                                         event("FIRMWARE_DONE", 7)], True)
    cases["valid_apb_setup_after_reset"] = ([event("APB_SETUP", 0, op="0", write="1", addr="40000010"),
                                              event("RESET_ASSERT", 1, xlate_pending="0", mem_pending="0", ptw_pending="0",
                                                    host_aw_pending="0", host_w_pending="0", host_ar_pending="0", apb_active="1",
                                                    chip_busy="0", maint_active="0"),
                                              event("RESET_RELEASE", 2, epoch="1"),
                                              event("APB_SETUP", 3, epoch="1", op="0", write="1", addr="40000010"),
                                              event("APB", 4, epoch="1", op="0", write="1", addr="40000010", error="0", wait_cycles="0"),
                                              event("SUBMIT", 5, epoch="1", tag="10", seq="0", asid="1"),
                                              event("COMPLETE_PUBLISH", 6, epoch="1", tag="10", asid="1", status="0", vectors_done="1"),
                                              event("COMPLETE", 7, epoch="1", tag="10", asid="1", status="0", vectors_done="1"),
                                              event("FIRMWARE_DONE", 8, epoch="1")], False)
    cases["host_read_wrong_id"] = ([event("RESET_RELEASE", 0),
                                     event("AXI_AR", 1, master="0", id="1", addr="10000000", len="0", size="2", burst="1"),
                                     event("AXI_R", 2, master="0", id="2", addr="10000000", beat="0", size="2",
                                           data="0000000000000000", resp="0", last="1"),
                                     event("SUBMIT", 3, tag="9", seq="0", asid="1"),
                                     event("COMPLETE_PUBLISH", 4, tag="9", asid="1", status="0", vectors_done="1"),
                                     event("COMPLETE", 5, tag="9", asid="1", status="0", vectors_done="1"),
                                     event("FIRMWARE_DONE", 6)], True)
    cases["host_read_missing_final_beat"] = ([event("RESET_RELEASE", 0),
                                               event("AXI_AR", 1, master="0", id="1", addr="10000000", len="1", size="2", burst="1"),
                                               event("SUBMIT", 2, tag="9", seq="0", asid="1"),
                                               event("COMPLETE_PUBLISH", 3, tag="9", asid="1", status="0", vectors_done="1"),
                                               event("COMPLETE", 4, tag="9", asid="1", status="0", vectors_done="1"),
                                               event("FIRMWARE_DONE", 5)], True)
    cases["dma_read_corrupt_from_independent_memory"] = ([
        event("RESET_RELEASE", 0),
        event("AXI_AW", 1, id="0", addr="10000000", len="0", size="2"),
        event("AXI_W", 2, data="0000000011223344", strb="0f"),
        event("AXI_B", 3, id="0", resp="0"),
        event("AXI_WRITE", 4, addr="10000000", len="0", size="2", data="0000000011223344", strb="0f"),
        event("MEM_REQ", 5, txn="0", write="0", addr="10000000", wdata="00000000", wstrb="0", tag="9", vector="0"),
        event("MEM_RSP", 6, txn="0", write="0", error="0", addr="10000000", wdata="00000000", wstrb="0", rdata="11223345", committed="0", tag="9", vector="0"),
        event("SUBMIT", 7, tag="9", seq="0", asid="1"),
        event("COMPLETE_PUBLISH", 8, tag="9", asid="1", status="0", vectors_done="1"),
        event("COMPLETE", 9, tag="9", asid="1", status="0", vectors_done="1"),
        event("FIRMWARE_DONE", 10)], True)
    burst_control = [
        event("RESET_RELEASE", 0),
        event("AXI_AW", 1, master="0", id="1", addr="10000000", len="1", size="3", burst="1"),
        event("AXI_W", 2, master="0", beat="0", data="0706050403020100", strb="ff", last="0"),
        event("AXI_W", 3, master="0", beat="1", data="0f0e0d0c0b0a0908", strb="ff", last="1"),
        event("AXI_B", 4, master="0", id="1", resp="0"),
        event("AXI_WRITE", 5, master="0", addr="10000000", beat="0", len="1", size="3", data="0706050403020100", strb="ff"),
        event("AXI_WRITE", 6, master="0", addr="10000008", beat="1", len="1", size="3", data="0f0e0d0c0b0a0908", strb="ff"),
        event("SUBMIT", 7, tag="10", seq="0", asid="1"),
        event("COMPLETE_PUBLISH", 8, tag="10", asid="1", status="0", vectors_done="1"),
        event("COMPLETE", 9, tag="10", asid="1", status="0", vectors_done="1"),
        event("FIRMWARE_DONE", 10),
    ]
    cases["valid_two_beat_host_write"] = (burst_control, False)
    read_burst = [
        event("RESET_RELEASE", 0),
        event("AXI_AR", 1, master="0", id="1", addr="10000000", len="1", size="3", burst="1"),
        event("AXI_R", 2, master="0", id="1", addr="10000000", beat="0", size="3",
              data="0000000000000000", resp="0", last="0"),
        event("AXI_R", 3, master="0", id="1", addr="10000008", beat="1", size="3",
              data="0000000000000000", resp="0", last="1"),
        event("SUBMIT", 4, tag="11", seq="0", asid="1"),
        event("COMPLETE_PUBLISH", 5, tag="11", asid="1", status="0", vectors_done="1"),
        event("COMPLETE", 6, tag="11", asid="1", status="0", vectors_done="1"),
        event("FIRMWARE_DONE", 7),
    ]
    cases["valid_two_beat_host_read"] = (read_burst, False)
    bad_read_progression = [dict(item) for item in read_burst]
    bad_read_progression[3]["addr"] = "10000004"
    cases["host_read_bad_address_progression"] = (bad_read_progression, True)
    early_last = [dict(item) for item in burst_control]
    early_last[2]["last"] = "1"
    cases["host_write_early_wlast"] = (early_last, True)
    failures = test_iss_register_sensitivity()
    result_rows = []
    specific_failures = {
        "mailbox_without_work": "no descriptor was accepted",
        "duplicate_completion": "completion tag 7 has no live accepted descriptor",
        "completion_after_reset": "completion tag 7 has no live accepted descriptor",
        "missing_completion": "firmware completed with live descriptors",
        "output_before_command": "accelerator output tag 7 has no accepted command",
        "wrong_asid": "completion tag 7 ASID mismatch",
        "completion_before_write_drain": "completion published with 1 outstanding output writes",
        "post_done_activity": "event RETIRE appears after firmware completion",
        "unknown_transport_response": "MEM_RSP without accepted request",
        "transport_id_mismatch": "MEM_RSP transaction 5 mismatches request 4",
        "completion_before_write_response": "outstanding output writes",
        "duplicate_retirement": "duplicate retirement order",
        "wrong_numerical_output": "accelerator output mismatch",
        "missing_schema": "missing schema",
        "memory_response_address_mismatch": "MEM_RSP addr=10000000 mismatches accepted request 10000004",
        "memory_response_payload_mismatch": "MEM_RSP wdata=11223345 mismatches accepted request 11223344",
        "maintenance_missing_done": "firmware completed with maintenance still active",
        "maintenance_done_without_start": "maintenance completed without an accepted start",
        "apb_access_without_setup": "APB access completion without setup phase",
        "apb_orphan_after_reset": "APB access completion without setup phase",
        "host_read_wrong_id": "host R ID mismatch",
        "host_read_bad_address_progression": "host R beat/address mismatch",
        "host_read_missing_final_beat": "trace ended with incomplete host AXI read transaction",
        "dma_read_corrupt_from_independent_memory": "DMA read data mismatch",
        "host_write_early_wlast": "host WLAST mismatch",
    }
    for name, (trace, expected_failure) in cases.items():
        strict_names = {"missing_schema", "mailbox_without_work", "duplicate_retirement"}
        result = run([dict(item, eid=str(i)) for i, item in enumerate(trace)],
                     strict_schema=(name in strict_names))
        failed = result["status"] == "FAIL"
        expected_category=specific_failures.get(name, "")
        category_ok = (not expected_failure and not expected_category) or (
            bool(expected_category) and expected_category in result.get("errors", ""))
        result_rows.append({"case": name, "expected": "FAIL" if expected_failure else "PASS",
                            "observed": "FAIL" if failed else "PASS",
                            "expected_category": expected_category,
                            "category_observed": "true" if category_ok else "false",
                            "checker_errors": result.get("errors", ""),
                            "checker_sha256": hashlib.sha256(CHECKER_PATH.read_bytes()).hexdigest(),
                            "selftest_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        if failed != expected_failure:
            failures.append(f"{name}: expected_failure={expected_failure} result={result}")
        if not category_ok:
            failures.append(f"{name}: missing or mismatched expected failure category {expected_category!r}: {result.get('errors')}")

    # Exercise strict lineage rules against a real successful integration trace.
    # These mutations reproduce false passes found during the audit.
    fixture = ROOT / "build/protected_offload/shared_firmware/schema3_observer_smoke/crossover.trace"
    if not fixture.is_file():
        failures.append("strict lineage fixture is missing; run compute-crossover-schema3-smoke first")
    else:
        original_events = checker.events
        base = original_events(fixture)
        strict_cases = {"strict_lineage_valid": (base, False, "")}
        bad_inputs = [dict(item) for item in base]
        for item in bad_inputs:
            if item.get("kind") == "ACCEL_IN": item["data"] = "00000000"
        strict_cases["descriptor_memory_to_accelerator_payload"] = (bad_inputs, True,
            "accelerator input payload differs from independently checked DMA read")
        bad_count = [dict(item) for item in base]
        for item in bad_count:
            if item.get("kind") in ("COMPLETE_PUBLISH", "COMPLETE"):
                item["vectors_done"] = "7"
        strict_cases["completion_count_matches_committed_outputs"] = (bad_count, True,
            "completion vector count 7 disagrees with committed output count")
        bad_cfg = [dict(item) for item in base]
        for item in bad_cfg:
            if item.get("kind") == "ACCEL_CFG": item["data"] = "00000000"
        strict_cases["apb_configuration_matches_accelerator_commit"] = (bad_cfg, True,
            "APB configuration commit data mismatch")
        bad_iova = [dict(item) for item in base]
        for item in bad_iova:
            if item.get("kind") == "SUBMIT": item["input_iova"] = "00000000"
        strict_cases["descriptor_controls_translation_addresses"] = (bad_iova, True,
            "descriptor 53 IOVA mismatch")
        for name, (trace, expected_failure, category) in strict_cases.items():
            result = run(trace, strict_schema=True)
            failed = result["status"] == "FAIL"
            category_ok = (not expected_failure and not category) or category in result.get("errors", "")
            result_rows.append({"case": name, "expected": "FAIL" if expected_failure else "PASS",
                "observed": "FAIL" if failed else "PASS", "expected_category": category,
                "category_observed": str(category_ok).lower(), "checker_errors": result.get("errors", ""),
                "checker_sha256": hashlib.sha256(CHECKER_PATH.read_bytes()).hexdigest(),
                "selftest_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
            if failed != expected_failure or not category_ok:
                failures.append(f"{name}: strict trace qualification mismatch: {result}")
    missing_categories = sorted(name for name, (_, expected_failure) in cases.items()
                                if expected_failure and not specific_failures.get(name))
    if missing_categories:
        failures.append("negative self-tests lack specific expected failure categories: " + ", ".join(missing_categories))
    report = ROOT / "reports/compute_crossover_checker_selftest.csv"
    with report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*result_rows[0], "status"], lineterminator="\n")
        writer.writeheader()
        for row in result_rows:
            row["status"] = "PASS" if row["expected"] == row["observed"] and row["category_observed"] == "true" else "FAIL"
            writer.writerow(row)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    positive_count = sum(row["expected"] == "PASS" for row in result_rows)
    print(f"Crossover checker self-test: {len(result_rows) - positive_count} negative cases detected; {positive_count} valid controls passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
