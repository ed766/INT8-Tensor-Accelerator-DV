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


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, macro, args in MUTATIONS:
        obj = BUILD / name
        command = ["verilator", "--binary", "--sv", "--timing", "--assert", "-Wall",
                   "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
                   f"-D{macro}", "--top-module", "tb_protected_offload", "--Mdir", str(obj),
                   *map(str, SOURCES)]
        build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if build.returncode != 0:
            rows.append({"mutation": name, "macro": macro, "status": "FAIL",
                         "detection": "compile_failed", "exit_code": build.returncode})
            continue
        event = BUILD / f"{name}.csv"
        run = subprocess.run([str(obj / "Vtb_protected_offload"), "+K=16", "+BATCH=2",
                              f"+EVENT_FILE={event}", *args], cwd=ROOT, text=True, capture_output=True)
        detected = run.returncode != 0
        combined = run.stdout + run.stderr
        if "timeout" in combined:
            bucket = "timeout"
        elif "Assertion failed" in combined:
            bucket = "assertion"
        elif "OUTPUT_MISMATCH" in combined:
            bucket = "memory_scoreboard"
        elif "failures=" in combined:
            bucket = "completion_scoreboard"
        else:
            bucket = "undetected"
        rows.append({"mutation": name, "macro": macro,
                     "status": "DETECTED" if detected else "MISSED",
                     "detection": bucket, "exit_code": run.returncode})
    with REPORT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    detected = sum(row["status"] == "DETECTED" for row in rows)
    print(f"PROTECTED_OFFLOAD_MUTATIONS|status={'PASS' if detected == len(rows) else 'FAIL'}|detected={detected}/{len(rows)}")
    return 0 if detected == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
