#!/usr/bin/env python3
"""Compile the RTL and compare every result against generated PyTorch vectors."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, check=check, text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", default="")
    parser.add_argument("--expect-fail", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    build = ROOT / "build" / (f"mut_{args.mutation.lower()}" if args.mutation else "sim")
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True, exist_ok=True)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)

    compile_command = [
        "verilator", "--binary", "--timing", "--assert", "-Wall", "-Wno-fatal", "-Wno-SYNCASYNCNET",
        "--top-module", "tb_int8_tensor_accel", "--Mdir", str(build / "obj"),
        "-I" + str(ROOT / "build"),
    ]
    if args.coverage:
        compile_command += ["--coverage-line", "--coverage-toggle"]
    if args.mutation:
        compile_command += [f"-D{args.mutation}", "-DMUTATION_TEST"]
    compile_command += [
        str(ROOT / "rtl" / "int8_tensor_accel.sv"),
        str(ROOT / "sim" / "int8_accel_assertions.sv"),
        str(ROOT / "sim" / "tb_int8_tensor_accel.sv"),
    ]
    compiled = run(compile_command, check=False)
    (build / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        print(compiled.stderr)
        return compiled.returncode

    sim_command = [str(build / "obj" / "Vtb_int8_tensor_accel")]
    try:
        simulated = subprocess.run(sim_command, cwd=build, check=False, text=True,
                                   capture_output=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        (build / "simulation.log").write_text((error.stdout or "") + (error.stderr or "") + "\nTIMEOUT\n")
        return 0 if args.expect_fail else 1
    log = simulated.stdout + simulated.stderr
    (build / "simulation.log").write_text(log)
    result_pattern = re.compile(
        r"RESULT\|case=(?P<case>\d+)\|name=(?P<name>[^|]+)\|status=(?P<status>\w+)\|"
        r"tag=(?P<tag>\d+)\|expected=(?P<expected>[0-9a-fA-F]+)\|observed=(?P<observed>[0-9a-fA-F]+)\|"
        r"observed_tag=(?P<observed_tag>\d+)\|latency=(?P<latency>\d+)"
    )
    rows = [match.groupdict() for match in result_pattern.finditer(log)]
    if not args.mutation:
        with (reports / "rtl_vs_pytorch_summary.csv").open("w", newline="") as handle:
            fields = ["case", "name", "status", "tag", "expected", "observed", "observed_tag", "latency"]
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    passed = len(rows) > 0 and all(row["status"] == "PASS" for row in rows) and simulated.returncode == 0
    if args.expect_fail:
        detected = not passed
        print(f"Mutation {args.mutation}: {'DETECTED' if detected else 'MISSED'}")
        return 0 if detected else 1
    print(f"RTL/PyTorch regression: {sum(r['status'] == 'PASS' for r in rows)} / {len(rows)} PASS")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
