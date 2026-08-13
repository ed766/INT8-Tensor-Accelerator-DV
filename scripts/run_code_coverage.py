#!/usr/bin/env python3
"""Collect merged raw Verilator coverage and review remaining RTL holes."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compile_and_run(build: Path, top: str, sources: list[str], database: Path) -> int:
    """Compile one coverage bench and write its native Verilator database."""
    main_cpp = build / "coverage_main.cpp"
    main_cpp.write_text("\n".join([
        "#include <cstdlib>", '#include "verilated.h"', '#include "verilated_cov.h"',
        f'#include "V{top}.h"', "",
        "int main(int argc, char** argv) {", "  VerilatedContext context;",
        "  context.commandArgs(argc, argv);", f"  V{top} dut(&context);",
        "  while (!context.gotFinish()) { dut.eval(); context.timeInc(1); }",
        "  dut.final();", '  const char* path = std::getenv("VERILATOR_COVERAGE_FILENAME");',
        '  VerilatedCov::write(path ? path : "coverage.dat");', "  return 0;", "}", "",
    ]))
    command = [
        "verilator", "--cc", "--exe", "--build", "--timing", "--assert", "--coverage",
        "-Wall", "-Wno-fatal", "-Wno-SYNCASYNCNET", "--top-module", top,
        "--Mdir", str(build), "-I" + str(ROOT / "build"), *sources, str(main_cpp),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    env = os.environ.copy()
    env["VERILATOR_COVERAGE_FILENAME"] = str(database)
    simulated = subprocess.run(
        [str(build / f"V{top}")], cwd=ROOT, env=env, text=True, capture_output=True,
    )
    if simulated.returncode:
        print(simulated.stdout + simulated.stderr)
    return simulated.returncode


def exclusion_reason(source_name: str, line_number: int) -> str | None:
    """Return a narrow, source-derived reason for structurally inactive points."""
    path = ROOT / source_name if not Path(source_name).is_absolute() else Path(source_name)
    if not path.exists() or path.name != "int8_tensor_accel.sv":
        return None
    lines = path.read_text().splitlines()
    text = lines[line_number - 1].strip()
    port_end = next(index for index, line in enumerate(lines, 1) if index > 3 and line.strip() == ");")
    if line_number <= port_end:
        return "module port/declaration instrumentation"
    declaration_prefixes = ("logic ", "localparam ", "integer ", "function ", "endfunction")
    if text.startswith(declaration_prefixes):
        return "internal declaration instrumentation"
    if "$fatal" in text or text.startswith("if ((LANES"):
        return "elaboration-time parameter legality guard"
    mutation_markers = (
        "1'b0 && relu", "requantize = scaled[7:0]", "selected_bank = 1'b0",
        "active_tag ^", "$unsigned(input_value)", "input_value;",
    )
    if any(marker in text for marker in mutation_markers):
        return "compile-time mutation-only behavior"
    if text in ("scaled = 0;", "if (scaled > 127)", "requantize = 8'sd127;",
                "requantize = -8'sd128;"):
        return "Verilator function-line attribution artifact; exact RTL result class is observed"
    if "perf_bank_swaps <= perf_bank_swaps" in text:
        return "Verilator conditional-line attribution artifact; bank-swap counter is explicitly checked"
    return None


def main() -> int:
    build = ROOT / "build" / "coverage"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    database = build / "regression.dat"
    if compile_and_run(
        build, "tb_int8_tensor_accel",
        ["rtl/int8_tensor_accel.sv", "sim/int8_accel_assertions.sv", "sim/tb_int8_tensor_accel.sv"],
        database,
    ):
        return 1

    edge_build = build / "protocol_edges"
    edge_build.mkdir()
    edge_database = build / "protocol_edges.dat"
    if compile_and_run(
        edge_build, "tb_protocol_edges",
        ["rtl/int8_tensor_accel.sv", "sim/int8_accel_assertions.sv", "sim/tb_protocol_edges.sv"],
        edge_database,
    ):
        return 1
    info_paths = []
    for name, native_database in (("regression", database), ("protocol_edges", edge_database)):
        info = build / f"{name}.info"
        converted = subprocess.run(
            ["verilator_coverage", "--write-info", str(info), str(native_database)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if converted.returncode:
            print(converted.stderr)
            return converted.returncode
        info_paths.append(info)
    line_hits: dict[tuple[str, int], int] = {}
    brf = brh = 0
    for info in info_paths:
        source = ""
        for line in info.read_text().splitlines():
            if line.startswith("SF:"):
                source = line[3:]
            elif line.startswith("DA:") and (source.startswith("rtl/") or "/rtl/" in source):
                number, count = map(int, line[3:].split(","))
                canonical_source = str(Path(source).relative_to(ROOT)) if Path(source).is_absolute() else source
                key = (canonical_source, number)
                line_hits[key] = max(line_hits.get(key, 0), count)
            elif line.startswith("BRF:"):
                brf = max(brf, int(line[4:]))
            elif line.startswith("BRH:"):
                brh = max(brh, int(line[4:]))
    lf = len(line_hits)
    lh = sum(count > 0 for count in line_hits.values())
    line_pct = 100.0 * lh / lf if lf else 0.0
    branch_pct = 100.0 * brh / brf if brf else 0.0
    holes = []
    for (source_name, number), count in sorted(line_hits.items()):
        if count == 0:
            reason = exclusion_reason(source_name, number)
            holes.append({
                "file": source_name, "line": number, "raw_hit_count": count,
                "classification": "reviewed_exclusion" if reason else "executable_and_worth_testing",
                "rationale": reason or "legal uncovered behavior",
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
