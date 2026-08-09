#!/usr/bin/env python3
"""Generate traceable feature and same-transaction cross coverage reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with (ROOT / "reports" / "scenario_manifest.csv").open() as handle:
        rows = list(csv.DictReader(handle))

    def values(key: str) -> list[list[int]]:
        return [json.loads(row[key]) for row in rows]

    inputs = values("input")
    weights = values("weights")
    biases = values("bias")
    mults = values("multiplier")
    shifts = values("shift")
    result_classes = [json.loads(row["result_classes"]) for row in rows]

    bins: list[tuple[str, bool, str]] = []
    def add(name: str, predicate: bool, source: str) -> None:
        bins.append((name, predicate, source))

    families = ("directed", "cross", "random")
    for family in families:
        add(f"family_{family}", any(r["family"] == family for r in rows), "scenario_manifest")
    for label, predicate in (
        ("input_zero", lambda v: v == 0), ("input_positive", lambda v: v > 0),
        ("input_negative", lambda v: v < 0), ("input_int8_min", lambda v: v == -128),
        ("input_int8_max", lambda v: v == 127),
    ):
        add(label, any(predicate(v) for vector in inputs for v in vector), "input_tensor")
    for label, predicate in (
        ("weight_zero", lambda v: v == 0), ("weight_positive", lambda v: v > 0),
        ("weight_negative", lambda v: v < 0), ("weight_int8_min", lambda v: v == -128),
        ("weight_int8_max", lambda v: v == 127),
    ):
        add(label, any(predicate(v) for matrix in weights for v in matrix), "weight_tensor")
    for result in ("positive", "negative", "zero", "sat_pos", "sat_neg", "relu_zero"):
        add(f"result_{result}", any(result in classes for classes in result_classes), "pytorch_result")
    add("relu_enabled", any(int(r["relu_mask"]) != 0 for r in rows), "configuration")
    add("relu_disabled", any(int(r["relu_mask"]) == 0 for r in rows), "configuration")
    add("unit_multiplier", any(1 in vector for vector in mults), "configuration")
    add("scaled_multiplier", any(any(v != 1 for v in vector) for vector in mults), "configuration")
    add("zero_shift", any(0 in vector for vector in shifts), "configuration")
    add("nonzero_shift", any(any(v != 0 for v in vector) for vector in shifts), "configuration")
    for label, predicate in (("bias_zero", lambda v: v == 0), ("bias_positive", lambda v: v > 0), ("bias_negative", lambda v: v < 0)):
        add(label, any(predicate(v) for vector in biases for v in vector), "configuration")
    add("source_gap", any(int(r["source_gap"]) > 0 for r in rows), "source_protocol")
    add("sink_backpressure", any(int(r["sink_stall"]) > 0 for r in rows), "sink_protocol")
    add("source_and_sink_pressure", any(int(r["source_gap"]) > 0 and int(r["sink_stall"]) > 0 for r in rows), "protocol_cross")
    for channel in range(4):
        add(f"output_channel_{channel}", any(classes[channel] != "zero" for classes in result_classes), "pytorch_result")

    coverage_path = ROOT / "reports" / "functional_coverage.csv"
    with coverage_path.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["bin", "status", "evidence"])
        writer.writerows((name, "COVERED" if hit else "MISSING", source) for name, hit, source in bins)

    crosses: list[tuple[str, bool, str]] = []
    for channel in range(4):
        for result in ("positive", "negative", "zero", "sat_pos", "sat_neg", "relu_zero"):
            contributors = [r["name"] for r, classes in zip(rows, result_classes) if classes[channel] == result]
            crosses.append((f"channel_{channel}_x_{result}", bool(contributors), ";".join(contributors)))
    with (ROOT / "reports" / "cross_coverage.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["cross_bin", "status", "contributing_tests"])
        writer.writerows((name, "COVERED" if hit else "MISSING", contributors) for name, hit, contributors in crosses)

    feature_hit = sum(hit for _, hit, _ in bins)
    cross_hit = sum(hit for _, hit, _ in crosses)
    (ROOT / "docs" / "coverage.md").write_text(
        "# Coverage\n\n"
        f"- Feature coverage: **{feature_hit} / {len(bins)}**\n"
        f"- Same-transaction channel/result crosses: **{cross_hit} / {len(crosses)}**\n"
        "- Evidence is derived from the generated PyTorch scenario manifest and actual RTL comparison lane.\n"
        "- These are project-defined functional metrics, not commercial simulator coverage signoff.\n\n"
        "The cross model requires each output channel to independently produce positive, negative, zero, "
        "positive saturation, negative saturation, and ReLU-clamped results.\n"
    )
    print(f"Functional coverage: {feature_hit} / {len(bins)}; crosses: {cross_hit} / {len(crosses)}")
    return 0 if feature_hit == len(bins) and cross_hit == len(crosses) else 1


if __name__ == "__main__":
    raise SystemExit(main())
