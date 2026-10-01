#!/usr/bin/env python3
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build/protected_offload/mutations"
REPORT = ROOT / "reports/protected_offload_mutations.csv"
SOURCES = [
    ROOT / "rtl/int8_tensor_accel.sv",
    ROOT / "integration/protected_offload/rtl/protected_queue_count_next.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_dma.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_apb_csr.sv",
    ROOT / "integration/protected_offload/sim/tb_protected_offload.sv",
]
MUTATIONS = [
    ("wrong_byte_lane", "PROTECTED_MUT_WRONG_BYTE_LANE", []),
    ("drop_chunk", "PROTECTED_MUT_DROP_CHUNK", []),
    ("stale_bank_generation", "PROTECTED_MUT_STALE_BANK_GENERATION", ["+BAD_GENERATION=1"]),
    ("permission_bypass", "PROTECTED_MUT_PERMISSION_BYPASS", ["+FAULT=1"]),
    ("wrong_asid", "PROTECTED_MUT_WRONG_ASID", []),
    ("stale_translation", "PROTECTED_MUT_STALE_TRANSLATION", []),
    ("wrong_response_tag", "PROTECTED_MUT_WRONG_RESPONSE_TAG", []),
    ("early_completion", "PROTECTED_MUT_EARLY_COMPLETION", []),
    ("lost_irq", "PROTECTED_MUT_LOST_IRQ", []),
    ("wrong_vector_count", "PROTECTED_MUT_WRONG_VECTOR_COUNT", []),
]
EXPECTED = {
    "wrong_byte_lane": ("OUTPUT_MISMATCH|", "submit"),
    "drop_chunk": ("MUTATION_DIAG|category=input_chunk_accounting|", "accepted_commands="),
    "stale_bank_generation": ("MUTATION_DIAG|category=bank_generation_guard|", "MUTATION_DIAG|"),
    "permission_bypass": ("MUTATION_DIAG|category=input_permission_containment|", "COMPLETION_OBSERVED|"),
    "wrong_asid": ("a_translation_context_matches_descriptor", "a_translation_context_matches_descriptor"),
    "stale_translation": ("OUTPUT_MISMATCH|", "submit"),
    "wrong_response_tag": ("MUTATION_DIAG|category=response_identity|", "COMPLETION_OBSERVED|"),
    "early_completion": ("OUTPUT_MISMATCH|", "submit"),
    "lost_irq": ("a_irq_tracks_completion", "COMPLETION_OBSERVED|"),
    "wrong_vector_count": ("MUTATION_DIAG|category=completion_accounting|", "COMPLETION_OBSERVED|"),
}


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, macro, args in MUTATIONS:
        obj = BUILD / name
        command = ["verilator", "--binary", "--sv", "--timing", "--assert", "-Wall", "-Wno-fatal",
                   "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
                   f"-D{macro}", "--top-module", "tb_protected_offload", "--Mdir", str(obj),
                   *map(str, SOURCES)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if build.returncode != 0:
            rows.append({"mutation": name, "macro": macro, "status": "FAIL",
                         "detection": "compile_failed", "activated": "false", "expected_failure": EXPECTED[name][0], "exit_code": build.returncode})
            continue
        event = BUILD / f"{name}.csv"
        run = subprocess.run([str(obj / "Vtb_protected_offload"), "+K=16", "+BATCH=2",
                              f"+EVENT_FILE={event}", *args], cwd=ROOT, text=True, capture_output=True)
        combined = run.stdout + run.stderr
        signature, activation = EXPECTED[name]
        event_text = event.read_text(errors="replace") if event.exists() else ""
        activated = activation in combined or activation in event_text
        expected_failure = signature in combined
        detected = run.returncode != 0 and activated and expected_failure
        if not run.returncode:
            bucket = "no_failure"
        elif not activated:
            bucket = "stimulus_not_activated"
        elif not expected_failure:
            bucket = "wrong_failure_signature"
        elif "MUTATION_DIAG|" in combined:
            bucket = combined.split("MUTATION_DIAG|", 1)[1].splitlines()[0].split("|", 1)[0]
        elif "OUTPUT_MISMATCH|" in combined:
            bucket = "output_data_mismatch"
        elif "a_translation_context_matches_descriptor" in combined:
            bucket = "translation_context_assertion"
        elif "a_irq_tracks_completion" in combined:
            bucket = "irq_completion_assertion"
        else:
            bucket = "unexpected"
        (BUILD / f"{name}.log").write_text(combined)
        rows.append({"mutation": name, "macro": macro,
                     "status": "DETECTED" if detected else "MISSED",
                     "detection": bucket, "activated": str(activated).lower(),
                     "expected_failure": signature, "exit_code": run.returncode})
    with REPORT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    detected = sum(row["status"] == "DETECTED" for row in rows)
    print(f"PROTECTED_OFFLOAD_MUTATIONS|status={'PASS' if detected == len(rows) else 'FAIL'}|detected={detected}/{len(rows)}")
    return 0 if detected == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
