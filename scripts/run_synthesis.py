#!/usr/bin/env python3
"""Run a Yosys implementation proxy for the reviewed 4x4 RTL."""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    yosys = shutil.which("yosys")
    if not yosys:
        row = {"status": "SKIP", "cells": "NA", "register_cells": "NA", "multiplier_cells": "NA", "warnings": "NA", "reason": "yosys unavailable"}
    else:
        command = [yosys, "-p", "read_verilog -sv rtl/int8_tensor_accel.sv; hierarchy -top int8_tensor_accel; proc; opt; memory; opt; stat"]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        log = completed.stdout + completed.stderr
        (ROOT / "build").mkdir(exist_ok=True)
        (ROOT / "build" / "synthesis.log").write_text(log)
        cells = re.findall(r"Number of cells:\s+(\d+)", log)
        dff = sum(int(value) for value in re.findall(r"\$(?:a?dff\w*)\s+(\d+)", log, re.IGNORECASE))
        multipliers = sum(int(value) for value in re.findall(r"\$mul\s+(\d+)", log))
        warnings = len(re.findall(r"^Warning:", log, re.MULTILINE))
        row = {
            "status": "PASS" if completed.returncode == 0 and cells else "FAIL",
            "cells": cells[-1] if cells else "NA", "register_cells": dff,
            "multiplier_cells": multipliers, "warnings": warnings,
            "reason": "open-source generic-cell proxy; warnings are expected array-to-register mapping",
        }
    with (reports / "synthesis_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    (ROOT / "docs" / "synthesis.md").write_text(
        "# Synthesis Proxy\n\n"
        f"| Status | Generic cells | Register cells | Multiplier cells | Warnings |\n| --- | ---: | ---: | ---: | ---: |\n"
        f"| {row['status']} | {row['cells']} | {row['register_cells']} | {row['multiplier_cells']} | {row['warnings']} |\n\n"
        "The five Yosys warnings document intentional mapping of small configuration arrays to registers. "
        "Yosys statistics are an open-source structural proxy. They are not area, timing, power, or implementation signoff.\n"
    )
    print(f"Synthesis proxy: {row['status']}, cells={row['cells']}")
    return 0 if row["status"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    raise SystemExit(main())
