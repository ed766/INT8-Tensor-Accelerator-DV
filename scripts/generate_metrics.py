#!/usr/bin/env python3
"""Generate canonical project metrics and the concise README evidence block."""

from __future__ import annotations

import csv
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- BEGIN GENERATED METRICS -->"
END = "<!-- END GENERATED METRICS -->"
DASHBOARD_START = "<!-- BEGIN GENERATED BENCHMARK DASHBOARD -->"
DASHBOARD_END = "<!-- END GENERATED BENCHMARK DASHBOARD -->"


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
    mlp = rows("reports/pytorch_mlp_rtl_summary.csv")[0]
    formal = rows("reports/formal_summary.csv")
    edges = rows("reports/protocol_edge_summary.csv")[0]
    portable = rows("reports/portable_validation_summary.csv")
    portable_meta = json.loads((ROOT / "portable" / "portable_vectors.json").read_text())
    axi_integration = rows("reports/axi_stream_integration_summary.csv")
    axi_coverage = rows("reports/axi_stream_integration_coverage.csv")
    assertion_text = (ROOT / "sim" / "int8_accel_assertions.sv").read_text()
    assertions = len(re.findall(r"^\s*a_[a-zA-Z0-9_]+:", assertion_text, re.MULTILINE))
    monitor_text = (ROOT / "rtl" / "int8_accel_health_monitor.sv").read_text()
    monitor_assertions = len(re.findall(r"^\s*a_[a-zA-Z0-9_]+:", monitor_text, re.MULTILINE))
    wrapper_text = (ROOT / "rtl" / "int8_accel_axi_wrapper.sv").read_text()
    wrapper_assertions = len(re.findall(r"^\s*a_[a-zA-Z0-9_]+:", wrapper_text, re.MULTILINE))
    benchmark = rows("reports/rv32_accel_benchmark.csv") if (ROOT / "reports/rv32_accel_benchmark.csv").exists() else []
    benchmark_correct = rows("reports/rv32_accel_correctness.csv") if (ROOT / "reports/rv32_accel_correctness.csv").exists() else []
    benchmark_pressure = rows("reports/rv32_accel_backpressure.csv") if (ROOT / "reports/rv32_accel_backpressure.csv").exists() else []
    benchmark_mutations = rows("reports/rv32_accel_mutations.csv") if (ROOT / "reports/rv32_accel_mutations.csv").exists() else []
    fx_compile = rows("reports/fx_compile_summary.csv") if (ROOT / "reports/fx_compile_summary.csv").exists() else []
    fx_rtl = rows("reports/fx_rtl_summary.csv") if (ROOT / "reports/fx_rtl_summary.csv").exists() else []
    fx_coverage = rows("reports/fx_coverage.csv") if (ROOT / "reports/fx_coverage.csv").exists() else []
    branch_value = (
        f"{code['branch_hit']} / {code['branch_total']} ({code['branch_percent']}%)"
        if code["branch_percent"] != "NA" else "NA (Verilator 5.020 LCOV)"
    )
    metrics = [
        ("pytorch_rtl_scenarios", f"{sum(r['status'] == 'PASS' for r in regression)} / {len(regression)}", "Every output word and tag compared"),
        ("functional_coverage", f"{sum(r['status'] == 'COVERED' for r in feature)} / {len(feature)}", "Project-defined feature points"),
        ("interaction_coverage", f"{sum(r['status'] == 'COVERED' for r in crosses)} / {len(crosses)}", "Same-transaction channel/result crosses"),
        ("two_layer_mlp", mlp["status"], f"{mlp['intermediate_words']} intermediate + {mlp['final_words']} final words"),
        ("streaming_throughput", f"{streaming['vectors_per_cycle']} vectors/cycle", f"{streaming['vectors']} K=4 commands; {streaming['active_macs_per_cycle']} active MACs/cycle"),
        ("protocol_edge_checks", f"{edges['checks']} / {edges['checks']}", "Illegal command, bank isolation, FIFO pressure, and reset"),
        ("portable_vector_checks", f"{sum(r['status'] == 'PASS' for r in portable)} / {len(portable)}", f"Packed stream {portable_meta['sha256'][:12]} shared with future FPGA host"),
        ("axi_stream_integration", f"{sum(r['status'] == 'PASS' for r in axi_integration)} / {len(axi_integration)}", f"{sum(int(r['checks']) for r in axi_integration)} AXI/decoder/end-to-end checks"),
        ("axi_integration_coverage", f"{sum(r['status'] == 'COVERED' for r in axi_coverage)} / {len(axi_coverage)}", "Event-derived AXI ordering, error, stream, decoder, and replay points"),
        ("named_assertions", str(assertions), "Bound reusable SVA properties"),
        ("portable_monitor_assertions", str(monitor_assertions), "Synthesizable monitor completion and backpressure properties"),
        ("axi_wrapper_assertions", str(wrapper_assertions), "AXI-Lite and AXI-Stream payload stability properties"),
        ("rtl_mutations", f"{sum(r['status'] == 'DETECTED' for r in mutations)} / {len(mutations)}", "Expected defects detected"),
        ("formal_groups", f"{sum(r['status'] == 'PASS' for r in formal)} / {len(formal)}", "Reduced-geometry safety and reachability"),
        ("raw_line_coverage", f"{code['line_hit']} / {code['line_total']} ({code['line_percent']}%)", "Verilator execution evidence"),
        ("reviewed_line_coverage", f"{code['reviewed_line_hit']} / {code['reviewed_line_total']} ({code['reviewed_line_percent']}%)", f"{code['reviewed_exclusions']} explicit exclusions"),
        ("raw_branch_coverage", branch_value, "Verilator branch/expression proxy"),
        ("yosys_synthesis", synth["status"], f"4x4 baseline: {synth['cells']} generic cells"),
    ]
    if benchmark:
        metrics.extend([
            ("rv32_accel_matrix", f"{sum(r['status'] == 'PASS' for r in benchmark)} / {len(benchmark)}", "GCC RV32I cold/warm cycle benchmark"),
            ("rv32_accel_correctness", f"{sum(r['status'] == 'PASS' for r in benchmark_correct)} / {len(benchmark_correct)}", "Scalar and accelerator outputs match PyTorch"),
            ("rv32_accel_backpressure", f"{sum(r['status'] == 'PASS' for r in benchmark_pressure)} / {len(benchmark_pressure)}", "Measured 0/25/75% output-stall cases"),
            ("rv32_accel_mutations", f"{sum(r['status'] == 'PASS' for r in benchmark_mutations)} / {len(benchmark_mutations)}", "Benchmark checker sensitivity"),
        ])
    if fx_compile:
        metrics.extend([
            ("fx_graph_compilation", f"{sum(r['status'] == 'PASS' for r in fx_compile)} / {len(fx_compile)}", "torch.fx Linear/ReLU graphs compiled"),
            ("fx_rtl_execution", fx_rtl[0]["status"], f"{fx_rtl[0]['words_checked']} intermediate/final words checked"),
            ("fx_compiler_coverage", f"{sum(r['status'] == 'COVERED' for r in fx_coverage)} / {len(fx_coverage)}", "Depth, K, activation, bank-reuse, and rejection points"),
        ])
    with (ROOT / "reports" / "project_metrics.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value", "note"])
        writer.writerows(metrics)
    table = [START, "| Evidence | Result |", "| --- | ---: |"]
    labels = {
        "pytorch_rtl_scenarios": "PyTorch-to-RTL comparisons",
        "functional_coverage": "Functional coverage",
        "interaction_coverage": "Interaction crosses",
        "two_layer_mlp": "Two-layer PyTorch/RTL chain",
        "streaming_throughput": "Measured steady-state throughput",
        "protocol_edge_checks": "Protocol edge checks",
        "portable_vector_checks": "Portable packed-vector checks",
        "axi_stream_integration": "AXI/record integration tests",
        "axi_integration_coverage": "AXI/record integration coverage",
        "named_assertions": "Named assertions",
        "portable_monitor_assertions": "Portable monitor assertions",
        "axi_wrapper_assertions": "AXI wrapper assertions",
        "rtl_mutations": "RTL mutations detected",
        "formal_groups": "Formal safety/cover groups",
        "raw_line_coverage": "Raw line coverage",
        "reviewed_line_coverage": "Reviewed executable line coverage",
        "raw_branch_coverage": "Raw branch/expression coverage",
        "yosys_synthesis": "Yosys synthesis proxy",
        "rv32_accel_matrix": "RV32I/accelerator benchmark matrix",
        "rv32_accel_correctness": "RV32I/accelerator correctness",
        "rv32_accel_backpressure": "RV32I/accelerator backpressure",
        "rv32_accel_mutations": "RV32I benchmark mutations",
        "fx_graph_compilation": "PyTorch FX graphs compiled",
        "fx_rtl_execution": "FX graph RTL execution",
        "fx_compiler_coverage": "FX compiler coverage",
    }
    table.extend(f"| {labels[key]} | `{value}` |" for key, value, _ in metrics)
    table.append(END)
    readme = ROOT / "README.md"
    text = readme.read_text()
    replacement = "\n".join(table)
    text = re.sub(re.escape(START) + r".*?" + re.escape(END), replacement, text, flags=re.DOTALL)
    if benchmark:
        cold = [float(row["end_to_end_speedup"]) for row in benchmark if row["mode"] == "cold"]
        warm = [float(row["end_to_end_speedup"]) for row in benchmark if row["mode"] == "warm"]
        compute = [float(row["compute_speedup"]) for row in benchmark]
        warm_break_even = {
            int(row["k"]): min(
                int(candidate["batch"])
                for candidate in benchmark
                if candidate["mode"] == "warm"
                and candidate["k"] == row["k"]
                and float(candidate["end_to_end_speedup"]) > 1.0
            )
            for row in benchmark
            if row["mode"] == "warm"
        }
        break_even_text = ", ".join(f"K={k}: batch {batch}" for k, batch in sorted(warm_break_even.items()))
        dashboard = [
            DASHBOARD_START,
            "| Measured comparison | Result |",
            "| --- | ---: |",
            f"| Cold end-to-end speedup | `{min(cold):.2f}x - {max(cold):.2f}x` |",
            f"| Warm end-to-end speedup | `{min(warm):.2f}x - {max(warm):.2f}x` |",
            f"| Compute-only speedup | `{min(compute):.2f}x - {max(compute):.2f}x` |",
            f"| Median cold / warm speedup | `{statistics.median(cold):.2f}x / {statistics.median(warm):.2f}x` |",
            f"| First measured warm break-even | `{break_even_text}` |",
            f"| Evidence matrix | `{sum(row['status'] == 'PASS' for row in benchmark)} / {len(benchmark)}` benchmark, "
            f"`{sum(row['status'] == 'PASS' for row in benchmark_correct)} / {len(benchmark_correct)}` correctness, "
            f"`{sum(row['status'] == 'PASS' for row in benchmark_pressure)} / {len(benchmark_pressure)}` backpressure |",
            DASHBOARD_END,
        ]
        text = re.sub(
            re.escape(DASHBOARD_START) + r".*?" + re.escape(DASHBOARD_END),
            "\n".join(dashboard),
            text,
            flags=re.DOTALL,
        )
    readme.write_text(text)
    metric_lines = ["# Project Metrics", "", "| Metric | Value | Interpretation |", "| --- | ---: | --- |"]
    metric_lines.extend(f"| `{key}` | {value} | {note} |" for key, value, note in metrics)
    metric_lines += ["", "All values are regenerated from checked-in CSV evidence by `make release-check`.", ""]
    (ROOT / "docs" / "project_metrics.md").write_text("\n".join(metric_lines))
    print("Project metrics regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
