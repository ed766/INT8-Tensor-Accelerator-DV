#!/usr/bin/env python3
"""Compile and execute the firmware-visible TLB invalidation control test."""
from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build" / "protected_offload" / "tlb_control"
BUILD.mkdir(parents=True, exist_ok=True)
command = ["verilator", "--binary", "--sv", "--timing", "--assert", "-Wall", "-Wno-fatal",
           "-Wno-TIMESCALEMOD", "--top-module", "tb_protected_tlb_control", "--Mdir", str(BUILD / "obj"),
           "integration/protected_offload/rtl/protected_tlb_control_apb.sv",
           "integration/protected_offload/sim/tb_protected_tlb_control.sv"]
compiled = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
run = subprocess.run([str(BUILD / "obj" / "Vtb_protected_tlb_control")], cwd=ROOT, text=True, capture_output=True) if compiled.returncode == 0 else compiled
text = compiled.stdout + compiled.stderr + run.stdout + run.stderr
match = re.search(r"TLBCTL_RESULT\|status=(PASS|FAIL)\|checks=(\d+)", text)
status = match.group(1) if match and run.returncode == 0 else "FAIL"
checks = match.group(2) if match else "0"
with (ROOT / "reports" / "protected_tlb_control_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=["test", "status", "checks"])
    writer.writeheader(); writer.writerow({"test": "firmware_visible_tlb_invalidate", "status": status, "checks": checks})
print(f"PROTECTED_TLB_CONTROL|status={status}|checks={checks}")
raise SystemExit(status != "PASS")
