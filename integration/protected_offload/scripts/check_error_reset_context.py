#!/usr/bin/env python3
"""Audit precise fault containment, partial-output recovery, and reset epochs."""
from __future__ import annotations

import csv
from pathlib import Path

from check_crossover_trace import check, events
from reset_evidence import phase_reached

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
EXPECTED_FAULTS = {
    "input_pte_fault": {"status": "2", "fault_iova": "80001000", "fault_stage": "1", "xlate_fault": "1"},
    "output_pte_fault": {"status": "3", "fault_iova": "80004000", "fault_stage": "3", "xlate_fault": "1"},
    "output_permission_fault": {"status": "3", "fault_iova": "80004000", "fault_stage": "3", "xlate_fault": "2"},
}


def trace_from(row: dict[str, str]) -> Path:
    path = ROOT / row["trace"]
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def audit_fault(row: dict[str, str]) -> dict[str, str]:
    trace = trace_from(row)
    evs = events(trace)
    scenario = row["scenario"]
    errors: list[str] = []
    completions = [e for e in evs if e.get("kind") == "COMPLETE"]
    writes = [e for e in evs if e.get("kind") == "MEM_RSP" and e.get("write") == "1" and e.get("committed") == "1"]
    xlate_faults = [e for e in evs if e.get("kind") == "XLATE_RSP" and e.get("fault") not in ("0", "")]
    write_errors = [e for e in evs if e.get("kind") == "MEM_RSP" and e.get("write") == "1" and e.get("error") != "0"]
    snapshots = [e for e in evs if e.get("kind") == "MEM_SNAPSHOT"]
    replay = check(trace, strict_schema=True)
    if replay["status"] != "PASS":
        errors.append("strict transaction replay: " + replay["errors"])
    if scenario == "partial_output_repair_retry":
        if len(completions) != 2:
            errors.append(f"expected fault plus retry completions, observed {len(completions)}")
        else:
            first, retry = completions
            if first.get("status") == "0" or first.get("vectors_done") != "1":
                errors.append("first completion did not report a one-vector committed prefix")
            if retry.get("status") != "0" or retry.get("vectors_done") != "2":
                errors.append("retry completion did not report full successful output")
            if first.get("tag") != retry.get("tag") or first.get("asid") != retry.get("asid"):
                errors.append("recovery did not reuse the consumed tag/ASID identity")
            if first.get("fault_iova") != "80005000" or first.get("fault_stage") != "4":
                errors.append("first completion did not preserve output-write fault IOVA/stage")
        if len(snapshots) != 1:
            errors.append(f"expected exactly one pre-retry SRAM snapshot, observed {len(snapshots)}")
        else:
            snap = snapshots[0]
            if snap.get("addr") != "10004000" or snap.get("data") != "0000000010101010":
                errors.append("pre-retry SRAM snapshot did not contain only the committed vector-0 word")
        if len(writes) < 3:
            errors.append(f"expected committed prefix plus two retried writes, observed {len(writes)}")
        if len(write_errors) != 1 or write_errors[0].get("addr") != "20000000":
            errors.append("expected exactly one rejected output write to the configured error target")
        if len(completions) == 2:
            first_i, retry_i = evs.index(completions[0]), evs.index(completions[1])
            prior = [e for e in writes if evs.index(e) < first_i]
            if not any(e.get("addr") == "10004000" for e in prior):
                errors.append("no successful prefix output write preceded the failed completion")
            if not any(e.get("addr") == "10008000" for e in writes):
                errors.append("recovery did not commit the repaired output mapping")
    else:
        if len(completions) != 1 or completions[0].get("status") == "0":
            errors.append("fault scenario did not retire exactly one failed completion")
        if not xlate_faults:
            errors.append("no failed translation response was observed")
        expected = EXPECTED_FAULTS.get(scenario)
        if expected and len(completions) == 1:
            completion = completions[0]
            for field in ("status", "fault_iova", "fault_stage"):
                if completion.get(field) != expected[field]:
                    errors.append(f"unexpected {field}: expected {expected[field]}, observed {completion.get(field)}")
        if expected and xlate_faults and xlate_faults[-1].get("fault") != expected["xlate_fault"]:
            errors.append(f"unexpected translation fault code: expected {expected['xlate_fault']}, observed {xlate_faults[-1].get('fault')}")
        if scenario == "input_pte_fault" and any(e.get("kind") == "ACCEL_CMD" for e in evs):
            errors.append("input translation failure reached the accelerator command interface")
        if writes:
            errors.append(f"fault scenario committed {len(writes)} output writes unexpectedly")
    return {
        "scenario": scenario,
        "status": "PASS" if not errors else "FAIL",
        "completion_statuses": ";".join(e.get("status", "?") for e in completions),
        "vectors_done": ";".join(e.get("vectors_done", "?") for e in completions),
        "translation_faults": str(len(xlate_faults)),
        "write_errors": str(len(write_errors)),
        "committed_writes": str(len(writes)),
        "pre_retry_snapshot": snapshots[0].get("data", "") if snapshots else "NA",
        "trace": str(trace.relative_to(ROOT)),
        "failure": "; ".join(errors) or "none",
    }


def audit_reset(row: dict[str, str]) -> dict[str, str]:
    trace = trace_from(row)
    evs = events(trace)
    errors: list[str] = []
    replay = check(trace, strict_schema=True)
    if replay["status"] != "PASS":
        errors.append("strict transaction replay: " + replay["errors"])
    resets = [e for e in evs if e.get("kind") == "RESET_ASSERT"]
    phase = row.get("reset_phase", "")
    phase_name = phase.removeprefix("event:")
    phase_kind = {"ptw_req": "XLATE_REQ", "mem_req": "MEM_REQ", "mem_rsp": "MEM_RSP",
                  "apb_wait": "APB_WAIT", "completion": "COMPLETE",
                  "host_w_wait": "AXI_AW"}.get(phase_name)
    reached = False
    pending_at_reset = "NA"
    if len(resets) != 1:
        errors.append(f"expected one in-run reset assertion, observed {len(resets)}")
    elif phase_kind:
        reset = resets[0]
        reached = phase_reached(evs, phase_name)
        pending_at_reset = f"xlate={reset.get('xlate_pending', '?')},mem={reset.get('mem_pending', '?')},completion={reset.get('completion_pending', '?')}"
        if not reached:
            errors.append(f"reset did not trigger immediately after requested phase {phase_name}")
        if reset.get("xlate_pending") not in ("0", "1") or reset.get("mem_pending") not in ("0", "1"):
            errors.append("reset event omitted accepted-transaction pending state")
    else:
        errors.append("report does not identify an event-triggered reset phase")
    releases = [e for e in evs if e.get("kind") == "RESET_RELEASE"]
    if len(releases) < 2:
        errors.append("firmware did not release reset and reboot into a new epoch")
    if len({e.get("epoch") for e in evs}) < 2:
        errors.append("reset trace does not contain distinct epochs")
    return {
        "scenario": row["scenario"], "status": "PASS" if not errors else "FAIL",
        "reset_phase": phase_name, "phase_reached": str(reached).lower(),
        "pending_at_reset": pending_at_reset, "epochs": str(len({e.get('epoch') for e in evs})),
        "canceled_transactions": str(replay.get("reset_canceled_transactions", 0)),
        "trace": str(trace.relative_to(ROOT)), "failure": "; ".join(errors) or "none",
    }


def read(name: str) -> list[dict[str, str]]:
    with (REPORTS / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, rows: list[dict[str, str]]) -> None:
    with (REPORTS / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    faults = read("protected_error_summary.csv")
    resets = read("protected_error_reset_summary.csv")
    if not faults or not resets:
        raise SystemExit("fault/reset simulation reports must be generated first")
    fault_rows = [audit_fault(row) for row in faults]
    reset_rows = [audit_reset(row) for row in resets]
    write("protected_error_context.csv", fault_rows)
    write("protected_reset_context.csv", reset_rows)
    failed = sum(row["status"] != "PASS" for row in fault_rows + reset_rows)
    print(f"PROTECTED_ERROR_RESET_CONTEXT|status={'PASS' if not failed else 'FAIL'}|faults={len(fault_rows)-sum(r['status']!='PASS' for r in fault_rows)}/{len(fault_rows)}|resets={len(reset_rows)-sum(r['status']!='PASS' for r in reset_rows)}/{len(reset_rows)}")
    return int(failed != 0)


if __name__ == "__main__":
    raise SystemExit(main())
