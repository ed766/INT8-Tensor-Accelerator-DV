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
    protected_directed = rows("reports/protected_offload_directed_summary.csv") if (ROOT / "reports/protected_offload_directed_summary.csv").exists() else []
    protected_random = rows("reports/protected_offload_random_summary.csv") if (ROOT / "reports/protected_offload_random_summary.csv").exists() else []
    protected_model = rows("reports/protected_offload_model_summary.csv") if (ROOT / "reports/protected_offload_model_summary.csv").exists() else []
    protected_feature = rows("reports/protected_offload_functional_coverage.csv") if (ROOT / "reports/protected_offload_functional_coverage.csv").exists() else []
    protected_cross = rows("reports/protected_offload_cross_coverage.csv") if (ROOT / "reports/protected_offload_cross_coverage.csv").exists() else []
    protected_mutations = rows("reports/protected_offload_integration_mutations.csv") if (ROOT / "reports/protected_offload_integration_mutations.csv").exists() else []
    protected_formal = rows("reports/protected_offload_formal.csv") if (ROOT / "reports/protected_offload_formal.csv").exists() else []
    protected_components = rows("reports/protected_offload_component_smoke.csv") if (ROOT / "reports/protected_offload_component_smoke.csv").exists() else []
    protected_firmware = rows("reports/protected_offload_firmware.csv") if (ROOT / "reports/protected_offload_firmware.csv").exists() else []
    protected_code = rows("reports/protected_offload_code_coverage.csv")[0] if (ROOT / "reports/protected_offload_code_coverage.csv").exists() else None
    protected_shared = rows("reports/protected_shared_firmware.csv") if (ROOT / "reports/protected_shared_firmware.csv").exists() else []
    protected_shared_random = rows("reports/protected_shared_random.csv") if (ROOT / "reports/protected_shared_random.csv").exists() else []
    protected_compiler = rows("reports/protected_shared_compiler_matrix.csv") if (ROOT / "reports/protected_shared_compiler_matrix.csv").exists() else []
    protected_cache = rows("reports/protected_cache_ownership.csv") if (ROOT / "reports/protected_cache_ownership.csv").exists() else []
    protected_cache_negative = rows("reports/protected_cache_negative.csv") if (ROOT / "reports/protected_cache_negative.csv").exists() else []
    protected_matched = rows("reports/protected_offload_matched_performance.csv") if (ROOT / "reports/protected_offload_matched_performance.csv").exists() else []
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
    if protected_directed:
        metrics.extend([
            ("protected_offload_directed", f"{sum(r['status'] == 'PASS' for r in protected_directed)} / {len(protected_directed)}", "Memory-to-memory DMA RTL scenarios"),
            ("protected_offload_random", f"{sum(r['status'] == 'PASS' for r in protected_random)} / {len(protected_random)}", "Deterministic descriptor/protection/fault workloads"),
            ("protected_offload_model", f"{sum(r['status'] == 'PASS' for r in protected_model)} / {len(protected_model)}", "Python orchestration plus compiled C++ event model"),
            ("protected_offload_coverage", f"{sum(r['status'] == 'COVERED' for r in protected_feature)} / {len(protected_feature)}; {sum(r['status'] == 'COVERED' for r in protected_cross)} / {len(protected_cross)}", "Functional points; same-execution crosses"),
            ("protected_offload_mutations", f"{sum(r['status'] == 'DETECTED' for r in protected_mutations)} / {len(protected_mutations)}", "Expected controller defects detected"),
            ("protected_offload_formal", f"{sum(r['status'] == 'PASS' for r in protected_formal)} / {len(protected_formal)}", "Bounded solver checks with reachable covers"),
            ("protected_offload_components", f"{sum(r['status'] == 'PASS' for r in protected_components)} / {len(protected_components)}", "Descriptor, queue, AXI adapter, and IOMMU checks"),
            ("protected_offload_firmware", f"{sum(r.get('execution_status') == 'PASS' for r in protected_firmware)} / {len(protected_firmware)}", "GCC-built RV32 APB/DMA execution matrix"),
            ("protected_shared_fabric", f"{sum(r['status'] == 'PASS' for r in protected_shared)} / {len(protected_shared)}", "Firmware-owned host/DMA/PTW/QoS-fabric executions"),
            ("protected_shared_random", f"{sum(r['status'] == 'PASS' for r in protected_shared_random)} / {len(protected_shared_random)}", "Seeded executable integration workloads"),
            ("protected_shared_compiler", f"{sum(r['status'] == 'PASS' for r in protected_compiler)} / {len(protected_compiler)}", "RV32I/RV32IM crossed with O0/O2/Os"),
            ("protected_cache_ownership", f"{sum(r['status'] == 'PASS' for r in protected_cache)} / {len(protected_cache)}; {sum(r['status'] == 'PASS' for r in protected_cache_negative)} / {len(protected_cache_negative)}", "Positive handoffs; intended-negative detections"),
            ("protected_matched_performance", f"{sum(r['status'] == 'PASS' for r in protected_matched)} / {len(protected_matched)}", "Five matched RV32I/RV32IM/accelerator paths"),
        ])
        if protected_code:
            metrics.append(("protected_offload_code", f"raw {protected_code['line_hit']} / {protected_code['line_total']} ({protected_code['line_percent']}%)", protected_code["note"]))
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
        "protected_offload_directed": "Protected-offload directed RTL",
        "protected_offload_random": "Protected-offload seeded RTL",
        "protected_offload_model": "Protected-offload trace replay",
        "protected_offload_coverage": "Protected-offload coverage / crosses",
        "protected_offload_mutations": "Protected-offload RTL mutations",
        "protected_offload_formal": "Protected-offload bounded properties",
        "protected_offload_components": "Protected-offload component checks",
        "protected_offload_firmware": "Protected-offload GCC/RV32 execution",
        "protected_offload_code": "Protected-offload line coverage",
        "protected_shared_fabric": "Firmware-owned fabric execution",
        "protected_shared_random": "Firmware-owned seeded integration",
        "protected_shared_compiler": "RV32I/RV32IM compiler matrix",
        "protected_cache_ownership": "Cached ownership positive / negative",
        "protected_matched_performance": "Matched five-path performance",
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
