#!/usr/bin/env python3
"""Compile and execute torch.fx-derived accelerator programs."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    subprocess.run([sys.executable, "scripts/fx_graph_compiler.py"], cwd=ROOT, check=True)
    build = ROOT / "build" / "fx_graphs"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True)
    command = ["verilator", "--binary", "--timing", "--assert", "-Wall", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
               "-Wno-UNUSEDSIGNAL", "-Wno-WIDTHTRUNC", "-Wno-WIDTHEXPAND", "--top-module", "tb_fx_graphs",
               "--Mdir", str(build / "obj"), "-I" + str(ROOT / "build"),
               "rtl/int8_tensor_accel.sv", "sim/int8_accel_assertions.sv", "sim/tb_fx_graphs.sv"]
    compiled = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (build / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        print(compiled.stderr)
        return compiled.returncode
    simulated = subprocess.run([str(build / "obj" / "Vtb_fx_graphs")], cwd=ROOT, text=True, capture_output=True)
    log = simulated.stdout + simulated.stderr
    (build / "simulation.log").write_text(log)
    match = re.search(r"FX_RTL_SUMMARY\|status=(\w+)\|graphs=(\d+)\|samples=(\d+)\|commands=(\d+)\|words_checked=(\d+)\|failures=(\d+)\|bank_swaps=(\d+)", log)
    passed = simulated.returncode == 0 and match is not None and match.group(1) == "PASS"
    row = {
        "scenario": "torch_fx_graph_matrix", "graphs": match.group(2) if match else 0,
        "samples": match.group(3) if match else 0, "commands": match.group(4) if match else 0,
        "words_checked": match.group(5) if match else 0, "failures": match.group(6) if match else "NA",
        "bank_swaps": match.group(7) if match else 0, "status": "PASS" if passed else "FAIL",
    }
    with (ROOT / "reports" / "fx_rtl_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    print(f"FX RTL graphs: {row['status']} ({row['graphs']} graphs, {row['words_checked']} words)")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
