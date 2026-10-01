#!/usr/bin/env python3
"""Run the twelve named firmware-crossover mutations with qualified controls."""
from __future__ import annotations

import csv
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "integration/protected_offload/scripts/run_shared_firmware.py"
IRQ_TB = ROOT / "integration/protected_offload/sim/tb_protected_irq_aggregator.sv"
IRQ_RTL = ROOT / "integration/protected_offload/rtl/protected_irq_aggregator.sv"
OUT = ROOT / "reports/protected_offload_integration_mutations.csv"

# name, scenario, macro, extra runner arguments, designated detection
CASES = [
    ("apb_setup_phase_retirement", "apb_axi__case_1", "RV32_BUG_APB_SETUP_RETIRE", [], "setup_phase_retirement_on_setup_pready"),
    ("duplicate_mmio_side_effect", "apb_axi__case_1", "RV32_BUG_DUP_APB_COMPLETION", [], "duplicate_mmio_blocked_by_a_mmio_retire_requires_access"),
    # Use the dedicated scenario that executes DIV while the device IRQ is
    # enabled. The generic interrupt matrix does not guarantee an M op is in
    # flight when the interrupt arrives.
    ("irq_before_div_retirement", "cpu_rv32m__case_5", "RV32_BUG_IRQ_BEFORE_M_RETIRE", [], "interrupt_retired_while_muldiv_active"),
    ("stale_muldiv_completion_after_reset", "cpu_rv32m__case_1", "RV32_BUG_M_STALE_RESET", ["--reset-phase-override", "mdiv_busy"], "stale_muldiv_state_survived_reset_epoch"),
    ("tag_reuse_before_completion_consumption", "", "", [], "tag_lifetime_checker"),
    ("queued_configuration_overwrite", "queues_configuration__case_5", "PROTECTED_MUT_BANK_REFERENCE_BYPASS", [], "a_referenced_generation_write_rejected"),
    ("completion_before_final_write_response", "translation_recovery__case_6", "PROTECTED_MUT_EARLY_COMPLETION", [], "success_published_before_output_commit"),
    ("lost_simultaneous_irq_event", "", "", [], "set_dominant_irq_unit_checker"),
    ("stale_translation_after_invalidation", "translation_recovery__case_6", "PROTECTED_MUT_STALE_TRANSLATION", [], "stale_tlb_entry_survived_invalidation"),
    ("wrong_partial_completion_count", "translation_recovery__case_6", "PROTECTED_MUT_WRONG_VECTOR_COUNT", [], "completion_vector_count_mismatch"),
    ("false_maintenance_completion", "cache_ownership__case_1", "PROTECTED_MUT_FALSE_MAINTENANCE", [], "maintenance_fast_ack_without_command_and_firmware_detected"),
    ("wrong_owner_response_delivery", "queues_configuration__case_1", "PROTECTED_MUT_WRONG_RESPONSE_TAG", [], "completion_response_owner_mismatch"),
]


def run(args: list[str], *, control: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if control:
        env["PROTECTED_ARTIFACT_PREFIX"] = "mutation_controls"
    return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True)


def irq_build(mutant: bool) -> subprocess.CompletedProcess[str]:
    obj = ROOT / "build/protected_offload/mutations" / ("irq_mutant" if mutant else "irq_nominal")
    obj.mkdir(parents=True, exist_ok=True)
    command = ["verilator", "--binary", "--sv", "--timing", "--assert", "-Wall", "-Wno-fatal"]
    if mutant:
        command.append("-DPROTECTED_MUT_LOST_SIMULTANEOUS_IRQ")
    command += ["--top-module", "tb_protected_irq_aggregator", "--Mdir", str(obj), str(IRQ_RTL), str(IRQ_TB)]
    result = run(command)
    (obj / "build.log").write_text(result.stdout + result.stderr)
    return result


def main() -> int:
    rows: list[dict[str, str]] = []
    for name, scenario, macro, extra, expected in CASES:
        if name == "tag_reuse_before_completion_consumption":
            report = ROOT / "reports/protected_offload_tag_lifetime_mutation.csv"
            tag_rows = list(csv.DictReader(report.open(newline=""))) if report.is_file() else []
            control = len(tag_rows) == 2 and tag_rows[0].get("status") == "PASS"
            detected = control and tag_rows[1].get("status") == "DETECTED" and tag_rows[1].get("detection") == expected
            rows.append({"mutation": name, "macro": "PROTECTED_MUT_TAG_REUSE", "status": "DETECTED" if detected else "MISSED",
                         "activated": "true" if detected else "false", "detection": expected if detected else "missing_tag_lifetime_evidence",
                         "expected_failure": expected, "compile_status": "PASS" if control else "FAIL",
                         "nominal_control": "PASS" if control else "FAIL", "exit_code": "0" if detected else "1"})
            continue
        if name == "lost_simultaneous_irq_event":
            nominal_build = irq_build(False)
            nominal_run = run([str(ROOT / "build/protected_offload/mutations/irq_nominal/Vtb_protected_irq_aggregator")]) if nominal_build.returncode == 0 else nominal_build
            mutant_build = irq_build(True)
            mutant_run = run([str(ROOT / "build/protected_offload/mutations/irq_mutant/Vtb_protected_irq_aggregator")]) if mutant_build.returncode == 0 else mutant_build
            activated = "set did not dominate ack" in mutant_run.stdout + mutant_run.stderr or "a_set_dominates_ack" in mutant_run.stdout + mutant_run.stderr
            detected = nominal_run.returncode == 0 and mutant_build.returncode == 0 and mutant_run.returncode != 0 and activated
            rows.append({"mutation": name, "macro": "PROTECTED_MUT_LOST_SIMULTANEOUS_IRQ", "status": "DETECTED" if detected else "MISSED",
                         "activated": str(activated).lower(), "detection": expected if detected else "unqualified_irq_mutation",
                         "expected_failure": expected, "compile_status": "PASS" if mutant_build.returncode == 0 else "FAIL",
                         "nominal_control": "PASS" if nominal_build.returncode == 0 and nominal_run.returncode == 0 else "FAIL",
                         "exit_code": str(mutant_run.returncode)})
            continue

        base = [sys.executable, str(RUNNER), "--scenario", scenario]
        control = run(base + (["--setup-pready-high"] if name == "apb_setup_phase_retirement" else []) + ["--model"], control=True)
        report_path = ROOT / f"reports/integration_mutation_{macro.lower()}.csv"
        report_mtime_before = report_path.stat().st_mtime_ns if report_path.exists() else 0
        mutation = run(base + ["--define", macro, *extra])
        combined = mutation.stdout + mutation.stderr
        # The runner's own event-based qualification is independent of its
        # exit status. It emits this exact field only after the intended event
        # and failure signature have both been observed.
        mutation_rows = list(csv.DictReader(report_path.open(newline=""))) if report_path.is_file() else []
        report_row = mutation_rows[-1] if mutation_rows else {}
        detail = report_row.get("mutation_qualification", "")
        fresh_report = report_path.is_file() and report_path.stat().st_mtime_ns > report_mtime_before
        try:
            runtime_exit = int(report_row.get("mutation_exit_code", ""))
        except ValueError:
            runtime_exit = 0
        trace_path = ROOT / report_row.get("trace", "__missing_trace__")
        trace_matches = (trace_path.is_file() and bool(report_row.get("trace_sha256")) and
                         hashlib.sha256(trace_path.read_bytes()).hexdigest() == report_row["trace_sha256"])
        activated = (fresh_report and report_row.get("scenario") == scenario and
                     runtime_exit != 0 and trace_matches and detail == expected)
        # Simulator assertions also print `%Error`; only a failed Python
        # build subprocess is compilation failure. Runtime checker failures
        # remain valid mutation detections when the named event is observed.
        compile_failed = "CalledProcessError" in combined
        compile_status = "FAIL" if compile_failed else "PASS"
        control_ok = control.returncode == 0
        # The simulator's nonzero result and designated qualification are
        # recorded in a fresh row with a matching trace hash. The outer Python
        # wrapper may return either zero or one depending on whether the test's
        # unrelated end-of-test firmware marker was reached after the mutant
        # was caught, so its exit status is not the mutation verdict.
        detected = compile_status == "PASS" and control_ok and activated
        rows.append({"mutation": name, "macro": macro, "status": "DETECTED" if detected else "MISSED",
                     "activated": str(activated).lower(), "detection": detail or "no_designated_checker_failure",
                     "expected_failure": expected, "compile_status": compile_status,
                     "nominal_control": "PASS" if control_ok else "FAIL", "exit_code": str(mutation.returncode)})
        print(f"CROSSOVER_MUTATION|{name}|{'DETECTED' if detected else 'MISSED'}|control={control.returncode}|mutation={mutation.returncode}|evidence={detail or 'none'}")

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    count = sum(row["status"] == "DETECTED" for row in rows)
    print(f"CROSSOVER_MUTATIONS|status={'PASS' if count == len(CASES) else 'FAIL'}|qualified={count}/{len(CASES)}")
    return 0 if count == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
