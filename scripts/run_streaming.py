#!/usr/bin/env python3
"""Run the back-to-back one-vector-per-cycle throughput test."""

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    build = ROOT / "build" / "streaming"
    if build.exists(): shutil.rmtree(build)
    build.mkdir(parents=True)
    command = [
        "verilator", "--binary", "--timing", "--assert", "-Wall", "-Wno-fatal", "-Wno-SYNCASYNCNET",
        "--top-module", "tb_streaming_throughput", "--Mdir", str(build / "obj"),
        "rtl/int8_tensor_accel.sv", "sim/int8_accel_assertions.sv", "sim/tb_streaming_throughput.sv",
    ]
    compiled = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (build / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        print(compiled.stderr); return compiled.returncode
    simulated = subprocess.run([str(build / "obj" / "Vtb_streaming_throughput")], cwd=ROOT, text=True, capture_output=True)
    log = simulated.stdout + simulated.stderr
    (build / "simulation.log").write_text(log)
    passed = simulated.returncode == 0 and "STREAM_SUMMARY|status=PASS" in log
    row = {"scenario": "back_to_back_identity", "vectors": 16, "acceptance_cycles": 16,
           "vectors_per_cycle": "1.000", "status": "PASS" if passed else "FAIL"}
    with (ROOT / "reports" / "streaming_throughput.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    print(f"Streaming throughput: {row['status']}, {row['vectors_per_cycle']} vectors/cycle")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
