#!/usr/bin/env python3
"""Qualify the active-descriptor tag-lifetime checker with a targeted mutant."""
from __future__ import annotations
import csv
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build/protected_offload/tag_lifetime_mutation"
REPORT = ROOT / "reports/protected_offload_tag_lifetime_mutation.csv"
SOURCES = [
    "integration/protected_offload/rtl/protected_queue_count_next.sv",
    "integration/protected_offload/rtl/protected_offload_dma.sv",
    "integration/protected_offload/sim/tb_protected_queue.sv",
]


def run(name: str, define: bool) -> tuple[str, str, str]:
    obj = BUILD / name
    shutil.rmtree(obj, ignore_errors=True)
    cmd = ["verilator", "--binary", "--sv", "--timing", "--assert", "-Wall",
           "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
           "-Wno-TIMESCALEMOD", "--top-module", "tb_protected_queue",
           "--Mdir", str(obj)]
    if define:
        cmd.append("-DPROTECTED_MUT_TAG_REUSE")
    cmd.extend(SOURCES)
    built = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if built.returncode:
        return "FAIL", "FAIL", (built.stderr or built.stdout)[-1000:]
    ran = subprocess.run([str(obj / "Vtb_protected_queue")], cwd=ROOT,
                         text=True, capture_output=True)
    output = ran.stdout + ran.stderr
    if define:
        detected = ran.returncode != 0 and "PROTECTED_TAG_REUSE_FAIL" in output
        return "PASS", "DETECTED" if detected else "MISSED", "active-tag checker marker observed" if detected else output[-1000:]
    return "PASS", "PASS" if ran.returncode == 0 and "active_tag_reuse_rejected=1" in output else "FAIL", "nominal active-tag control"


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, mutant in (("nominal_control", False), ("allow_duplicate_live_tag", True)):
        compile_status, result, detail = run(name, mutant)
        rows.append({"case": name, "compile_status": compile_status,
                     "status": result, "activated": "true" if mutant else "control",
                     "detection": "tag_lifetime_checker" if mutant and result == "DETECTED" else
                     ("none" if mutant else "nominal_component_test"),
                     "detail": detail})
    REPORT.parent.mkdir(exist_ok=True)
    with REPORT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    ok = rows[0]["status"] == "PASS" and rows[1]["status"] == "DETECTED" and all(r["compile_status"] == "PASS" for r in rows)
    print(f"TAG_LIFETIME_MUTATION|status={'PASS' if ok else 'FAIL'}|detected={int(rows[1]['status']=='DETECTED')}/1")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
