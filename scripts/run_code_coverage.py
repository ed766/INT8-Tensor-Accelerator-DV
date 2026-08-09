#!/usr/bin/env python3
"""Collect raw Verilator line/branch coverage for the accelerator RTL."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    build = ROOT / "build" / "coverage"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    main_cpp = build / "coverage_main.cpp"
    main_cpp.write_text("\n".join([
        "#include <cstdlib>", '#include "verilated.h"', '#include "verilated_cov.h"',
        '#include "Vtb_int8_tensor_accel.h"', "",
        "int main(int argc, char** argv) {", "  VerilatedContext context;",
        "  context.commandArgs(argc, argv);", "  Vtb_int8_tensor_accel top(&context);",
        "  while (!context.gotFinish()) { top.eval(); context.timeInc(1); }",
        "  top.final();", '  const char* path = std::getenv("VERILATOR_COVERAGE_FILENAME");',
        '  VerilatedCov::write(path ? path : "coverage.dat");', "  return 0;", "}", "",
    ]))
    compile_command = [
        "verilator", "--cc", "--exe", "--build", "--timing", "--assert", "--coverage",
        "-Wall", "-Wno-fatal", "-Wno-SYNCASYNCNET", "--top-module", "tb_int8_tensor_accel",
        "--Mdir", str(build), "-I" + str(ROOT / "build"),
        "rtl/int8_tensor_accel.sv", "sim/int8_accel_assertions.sv", "sim/tb_int8_tensor_accel.sv",
        str(main_cpp),
    ]
    subprocess.run(compile_command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    database = build / "coverage.dat"
    env = os.environ.copy()
    env["VERILATOR_COVERAGE_FILENAME"] = str(database)
    simulated = subprocess.run([str(build / "Vtb_int8_tensor_accel")], cwd=ROOT, env=env, text=True, capture_output=True)
    if simulated.returncode:
        print(simulated.stdout + simulated.stderr)
        return simulated.returncode
    info = build / "coverage.info"
    converted = subprocess.run(
        ["verilator_coverage", "--write-info", str(info), str(database)],
        cwd=ROOT, text=True, capture_output=True,
    )
    if converted.returncode:
        print(converted.stderr)
        return converted.returncode
    source = ""
    line_hits: dict[tuple[str, int], int] = {}
    brf = brh = 0
    for line in info.read_text().splitlines():
        if line.startswith("SF:"):
            source = line[3:]
        elif line.startswith("DA:") and (source.startswith("rtl/") or "/rtl/" in source):
            number, count = map(int, line[3:].split(","))
            key = (source, number)
            line_hits[key] = max(line_hits.get(key, 0), count)
        elif line.startswith("BRF:"): brf += int(line[4:])
        elif line.startswith("BRH:"): brh += int(line[4:])
    lf = len(line_hits)
    lh = sum(count > 0 for count in line_hits.values())
    line_pct = 100.0 * lh / lf if lf else 0.0
    branch_pct = 100.0 * brh / brf if brf else 0.0
    reviewed_reasons = {
        21: "module port/declaration instrumentation",
        26: "module port/declaration instrumentation",
        28: "module port/declaration instrumentation",
        29: "module port/declaration instrumentation",
        30: "module port/declaration instrumentation",
        39: "module port/declaration instrumentation",
        40: "module port/declaration instrumentation",
        45: "module port/declaration instrumentation",
        63: "Verilator function-assignment artifact; relu_zero crosses hit on all four channels",
        126: "structurally unreachable default for exhaustive 2-bit cfg_kind",
    }
    holes = []
    for (source_name, number), count in sorted(line_hits.items()):
        if count == 0:
            holes.append({
                "file": source_name, "line": number, "raw_hit_count": count,
                "classification": "reviewed_exclusion" if number in reviewed_reasons else "executable_and_worth_testing",
                "rationale": reviewed_reasons.get(number, "legal uncovered behavior"),
            })
    with (ROOT / "reports" / "coverage_hole_review.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(holes[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(holes)
    exclusions = sum(row["classification"] == "reviewed_exclusion" for row in holes)
    reviewed_total = lf - exclusions
    reviewed_pct = 100.0 * lh / reviewed_total if reviewed_total else 0.0
    row = {"scope": "raw_accelerator_rtl", "line_hit": lh, "line_total": lf,
           "line_percent": f"{line_pct:.2f}", "branch_hit": brh, "branch_total": brf,
           "branch_percent": f"{branch_pct:.2f}" if brf else "NA",
           "reviewed_line_hit": lh, "reviewed_line_total": reviewed_total,
           "reviewed_line_percent": f"{reviewed_pct:.2f}", "reviewed_exclusions": exclusions}
    with (ROOT / "reports" / "code_coverage_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    branch_line = (
        f"- Raw branch/expression coverage: **{brh} / {brf} ({branch_pct:.2f}%)**\n"
        if brf else
        "- Raw branch/expression coverage: **NA** (not exported by Verilator 5.020 LCOV)\n"
    )
    (ROOT / "docs" / "code_coverage.md").write_text(
        "# Code Coverage\n\n"
        f"- Raw line coverage: **{lh} / {lf} ({line_pct:.2f}%)**\n"
        f"- Reviewed executable line coverage: **{lh} / {reviewed_total} ({reviewed_pct:.2f}%)**, "
        f"with **{exclusions}** denominator-visible exclusions\n"
        + branch_line +
        "\nEvery exclusion is listed in `reports/coverage_hole_review.csv`. Raw coverage remains the primary value. "
        "Functional intent and assertion inventory are tracked separately.\n"
    )
    print(f"Code coverage: line {line_pct:.2f}%, branch {branch_pct:.2f}%" if brf else
          f"Code coverage: line {line_pct:.2f}%, branch NA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
