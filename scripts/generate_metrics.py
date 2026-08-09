#!/usr/bin/env python3
"""Generate canonical project metrics and the concise README evidence block."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN GENERATED METRICS -->"
END = "<!-- END GENERATED METRICS -->"


def rows(path: str) -> list[dict[str, str]]:
    with (ROOT / path).open() as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    regression = rows("reports/rtl_vs_pytorch_summary.csv")
    feature = rows("reports/functional_coverage.csv")
    crosses = rows("reports/cross_coverage.csv")
    mutations = rows("reports/mutation_summary.csv")
    code = rows("reports/code_coverage_summary.csv")[0]
    synth = rows("reports/synthesis_summary.csv")[0]
    streaming = rows("reports/streaming_throughput.csv")[0]
    assertion_text = (ROOT / "sim" / "int8_accel_assertions.sv").read_text()
    assertions = len(re.findall(r"^\s*a_[a-zA-Z0-9_]+:", assertion_text, re.MULTILINE))
    branch_value = (
        f"{code['branch_hit']} / {code['branch_total']} ({code['branch_percent']}%)"
        if code["branch_percent"] != "NA" else "NA (Verilator 5.020 LCOV)"
    )
    metrics = [
        ("pytorch_rtl_scenarios", f"{sum(r['status'] == 'PASS' for r in regression)} / {len(regression)}", "Every output word and tag compared"),
        ("functional_coverage", f"{sum(r['status'] == 'COVERED' for r in feature)} / {len(feature)}", "Project-defined feature points"),
        ("interaction_coverage", f"{sum(r['status'] == 'COVERED' for r in crosses)} / {len(crosses)}", "Same-transaction channel/result crosses"),
        ("streaming_throughput", f"{streaming['vectors_per_cycle']} vectors/cycle", f"{streaming['vectors']} consecutive vectors"),
        ("named_assertions", str(assertions), "Bound reusable SVA properties"),
        ("rtl_mutations", f"{sum(r['status'] == 'DETECTED' for r in mutations)} / {len(mutations)}", "Expected defects detected"),
        ("raw_line_coverage", f"{code['line_hit']} / {code['line_total']} ({code['line_percent']}%)", "Verilator execution evidence"),
        ("reviewed_line_coverage", f"{code['reviewed_line_hit']} / {code['reviewed_line_total']} ({code['reviewed_line_percent']}%)", f"{code['reviewed_exclusions']} explicit exclusions"),
        ("raw_branch_coverage", branch_value, "Verilator branch/expression proxy"),
        ("yosys_synthesis", synth["status"], f"{synth['cells']} generic cells"),
    ]
    with (ROOT / "reports" / "project_metrics.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value", "note"])
        writer.writerows(metrics)
    table = [START, "| Evidence | Result |", "| --- | ---: |"]
    labels = {
        "pytorch_rtl_scenarios": "PyTorch-to-RTL comparisons",
        "functional_coverage": "Functional coverage",
        "interaction_coverage": "Interaction crosses",
        "streaming_throughput": "Measured steady-state throughput",
        "named_assertions": "Named assertions",
        "rtl_mutations": "RTL mutations detected",
        "raw_line_coverage": "Raw line coverage",
        "reviewed_line_coverage": "Reviewed executable line coverage",
        "raw_branch_coverage": "Raw branch/expression coverage",
        "yosys_synthesis": "Yosys synthesis proxy",
    }
    table.extend(f"| {labels[key]} | `{value}` |" for key, value, _ in metrics)
    table.append(END)
    readme = ROOT / "README.md"
    text = readme.read_text()
    replacement = "\n".join(table)
    text = re.sub(re.escape(START) + r".*?" + re.escape(END), replacement, text, flags=re.DOTALL)
    readme.write_text(text)
    metric_lines = ["# Project Metrics", "", "| Metric | Value | Interpretation |", "| --- | ---: | --- |"]
    metric_lines.extend(f"| `{key}` | {value} | {note} |" for key, value, note in metrics)
    metric_lines += ["", "All values are regenerated from checked-in CSV evidence by `make release-check`.", ""]
    (ROOT / "docs" / "project_metrics.md").write_text("\n".join(metric_lines))
    print("Project metrics regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
