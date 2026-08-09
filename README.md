# INT8 Tensor Accelerator RTL and PyTorch DV

A compact signed-INT8 tensor dot-product accelerator implemented in SystemVerilog and verified against an independent PyTorch integer model. The project focuses on numerical correctness, quantization edge cases, streaming backpressure, assertion-based checking, coverage, mutation sensitivity, and open-source implementation evidence.

![Architecture and verification flow](docs/images/architecture.svg)

## Why This Project

The accelerator complements the rest of the portfolio rather than repeating SoC, cache, or AXI-fabric work. It demonstrates hardware/ML co-design: translating an explicit quantized numerical contract into RTL and proving that the implementation matches PyTorch across directed corner cases and seeded tensors.

## Measured Evidence

<!-- BEGIN GENERATED METRICS -->
| Evidence | Result |
| --- | ---: |
| PyTorch-to-RTL comparisons | `63 / 63` |
| Functional coverage | `35 / 35` |
| Interaction crosses | `24 / 24` |
| Measured steady-state throughput | `1.000 vectors/cycle` |
| Named assertions | `8` |
| RTL mutations detected | `4 / 4` |
| Raw line coverage | `75 / 85 (88.24%)` |
| Reviewed executable line coverage | `75 / 75 (100.00%)` |
| Raw branch/expression coverage | `NA (Verilator 5.020 LCOV)` |
| Yosys synthesis proxy | `PASS` |
<!-- END GENERATED METRICS -->

Detailed evidence is in [project metrics](docs/project_metrics.md) and the [verification plan](docs/verification_plan.md).

## Architecture

The reviewed configuration implements:

- four signed INT8 input lanes;
- four output channels with a 4×4 signed MAC array;
- signed INT32 accumulation and per-output bias;
- signed multiplier plus arithmetic right-shift requantization;
- independently enabled ReLU and signed INT8 saturation per output;
- ready/valid input and output with 8-bit transaction tags;
- a one-entry result stage supporting one vector per cycle when unstalled;
- accepted/completed/output-stall verification counters.

See the exact [numerical contract](docs/numerical_contract.md).

## Verification Flow

1. PyTorch creates deterministic directed, cross-targeted, and seeded-random tensors.
2. The generator computes INT32 accumulators and final quantized INT8 outputs.
3. The SystemVerilog bench programs the RTL configuration and drives each tagged vector.
4. Every output word and tag is compared exactly against the PyTorch result.
5. Bound assertions check ready/valid stability, occupancy, ordering, reset, and configuration safety.
6. Coverage, latency, mutation, code-coverage, and synthesis reports are regenerated from the run.

The project deliberately uses integer tensor operations, not tolerance-based floating-point comparisons. That makes any one-bit result difference a failure.

A separate [PyTorch Linear demo](docs/pytorch_linear_demo.md) quantizes a deterministic `torch.nn.Linear(4, 4)` layer and measures the numerical difference between floating-point and hardware-friendly integer inference.

## Reviewer Quick Path

With Python, PyTorch, Verilator, and Yosys installed:

```bash
make project-check
make release-check
```

If PyTorch is installed in a virtual environment:

```bash
make release-check PYTHON=/path/to/venv/bin/python
```

High-signal artifacts:

- [PyTorch/RTL comparison](reports/rtl_vs_pytorch_summary.csv)
- [Functional coverage](reports/functional_coverage.csv)
- [Interaction coverage](reports/cross_coverage.csv)
- [Mutation results](reports/mutation_summary.csv)
- [Performance](docs/performance.md)
- [Verification plan](docs/verification_plan.md)

## Repository Layout

```text
rtl/       synthesizable accelerator RTL
sim/       SystemVerilog bench and bound assertions
scripts/   PyTorch vectors, regression, coverage, mutation, and report automation
docs/      reviewer-facing architecture and evidence
reports/   normalized checked-in CSV/Markdown results
```

## Limitations

- The design is a fixed reviewed 4×4 dot-product engine, not a full systolic array or production NPU.
- It implements signed symmetric INT8 arithmetic with deterministic fixed-point scaling; no floating point, stochastic rounding, sparsity, or training is supported.
- The interface is a compact streaming/configuration protocol rather than AXI.
- PyTorch, Verilator, and Yosys results are open-source pre-silicon evidence, not accuracy certification, physical-design signoff, or commercial verification closure.
- UVM is intentionally not duplicated here; the portfolio's AXI4 QoS fabric project owns the reusable real-UVM/VIP story.
