#!/usr/bin/env python3
"""Summarize measured request latency under output backpressure."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def main() -> int:
    with (ROOT / "reports" / "rtl_vs_pytorch_summary.csv").open() as handle:
        result_rows = list(csv.DictReader(handle))
    with (ROOT / "reports" / "scenario_manifest.csv").open() as handle:
        manifests = {row["name"]: row for row in csv.DictReader(handle)}
    groups: dict[str, list[int]] = defaultdict(list)
    for row in result_rows:
        stall = int(manifests[row["name"]]["sink_stall"])
        bucket = "0 cycles" if stall == 0 else "1-2 cycles" if stall <= 2 else "3-4 cycles" if stall <= 4 else "5-6 cycles"
        groups[bucket].append(int(row["latency"]))
    order = ("0 cycles", "1-2 cycles", "3-4 cycles", "5-6 cycles")
    summary = []
    for bucket in order:
        values = groups[bucket]
        summary.append({
            "output_stall": bucket, "requests": len(values),
            "mean_latency_cycles": f"{sum(values) / len(values):.2f}",
            "p50_cycles": nearest_rank(values, 0.50), "p95_cycles": nearest_rank(values, 0.95),
            "max_cycles": max(values),
        })
    with (ROOT / "reports" / "performance_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    table = [
        "# Performance Characterization", "",
        "Behavioral Verilator measurements from accepted input to accepted output. Configuration time is excluded.", "",
        "| Output-ready stall | Requests | Mean latency | p50 | p95 | Max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary:
        table.append(
            f"| {row['output_stall']} | {row['requests']} | {row['mean_latency_cycles']} | "
            f"{row['p50_cycles']} | {row['p95_cycles']} | {row['max_cycles']} |"
        )
    table += [
        "", "The single-entry output stage can accept one vector per cycle when the consumer is ready. "
        "Backpressure stalls the pipeline and increases end-to-end latency. These are RTL simulation results, not silicon timing signoff.", "",
    ]
    (ROOT / "docs" / "performance.md").write_text("\n".join(table))
    print(f"Performance report: {sum(len(v) for v in groups.values())} measured requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
