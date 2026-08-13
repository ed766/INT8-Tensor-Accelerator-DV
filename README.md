# Tiled INT8 Tensor Accelerator RTL and PyTorch DV

A command-driven quantized linear-layer accelerator implemented in SystemVerilog and checked bit-for-bit against PyTorch. The engine executes configurable `K=4–64` dot products over four output channels, supports double-buffered parameters and asymmetric quantization, and preserves tagged results through a four-entry output FIFO.

![Architecture and verification flow](docs/images/architecture.svg)

## Why This Project

This project is the portfolio's ML/datapath example. It shows how a PyTorch model becomes an explicit integer numerical contract, how that contract maps into multicycle RTL, and how numerical, protocol, performance, and implementation behavior are independently verified.

## Measured Evidence

<!-- BEGIN GENERATED METRICS -->
| Evidence | Result |
| --- | ---: |
| PyTorch-to-RTL comparisons | `130 / 130` |
| Functional coverage | `64 / 64` |
| Interaction crosses | `48 / 48` |
| Two-layer PyTorch/RTL chain | `PASS` |
| Measured steady-state throughput | `0.500 vectors/cycle` |
| Protocol edge checks | `15 / 15` |
| Named assertions | `21` |
| RTL mutations detected | `9 / 9` |
| Formal safety/cover groups | `2 / 2` |
| Raw line coverage | `159 / 173 (91.91%)` |
| Reviewed executable line coverage | `159 / 159 (100.00%)` |
| Raw branch/expression coverage | `NA (Verilator 5.020 LCOV)` |
| Yosys synthesis proxy | `PASS` |
<!-- END GENERATED METRICS -->

See [project metrics](docs/project_metrics.md), the [verification plan](docs/verification_plan.md), and the [two-layer PyTorch demonstration](docs/pytorch_mlp_demo.md).

## Architecture

- Four signed INT8 activation lanes and four output channels in the reviewed baseline.
- Configurable `K=4/8/16/32/64`, processed four activation/weight pairs per output each active cycle.
- Two complete weight/quantization banks; the inactive bank can be configured while the active bank executes.
- Signed INT32 accumulation with per-channel bias.
- Per-channel multiplier, round-to-nearest right shift, output zero point, ReLU, and INT8 saturation.
- Asymmetric input and per-output weight zero points.
- Command validation, tagged streaming chunks, and a four-entry output FIFO.
- A parameterized `8×8` structural variant used for synthesis-cost comparison.

The exact behavior is defined in the [numerical contract](docs/numerical_contract.md).

## Verification Flow

1. PyTorch generates 30 directed and 100 seeded-random workloads.
2. The independent model predicts adjusted operands, INT32 accumulators, signed rounded requantization, and final INT8 outputs.
3. The SystemVerilog bench loads either parameter bank, issues a tagged command, and streams every activation chunk.
4. Every RTL result word and tag is compared exactly; floating-point tolerance is never used for RTL checking.
5. A two-layer `Linear(16,4)-ReLU-Linear(4,4)` model feeds RTL-observed hidden activations into the second RTL layer.
6. Assertions, protocol-edge tests, functional/cross coverage, RTL mutations, bounded formal checks, code coverage, performance, and synthesis reports are regenerated.

## Reviewer Quick Path

```bash
make project-check PYTHON=/path/to/pytorch/python
make release-check PYTHON=/path/to/pytorch/python
```

High-signal evidence:

- [PyTorch/RTL comparison](reports/rtl_vs_pytorch_summary.csv)
- [Two-layer RTL chain](reports/pytorch_mlp_rtl_summary.csv)
- [Functional coverage](reports/functional_coverage.csv)
- [Interaction crosses](reports/cross_coverage.csv)
- [RTL mutation sensitivity](reports/mutation_summary.csv)
- [Performance characterization](docs/performance.md)
- [Formal evidence](docs/formal.md)
- [Synthesis comparison](docs/synthesis.md)

## Repository Layout

```text
rtl/       synthesizable tiled accelerator RTL
sim/       SystemVerilog benches and bound assertions
formal/    reduced-geometry safety and reachability tasks
scripts/   PyTorch export, regression, coverage, mutation, and report automation
docs/      reviewer-facing architecture and verification evidence
reports/   normalized checked-in CSV results
```

## Limitations

- This is a compact linear-layer engine, not a complete NPU, systolic array, training engine, or software compiler.
- The reviewed functional regression uses the `4×4` baseline; `8×8` is separately reported synthesis evidence.
- No convolution frontend, floating point, sparsity, stochastic rounding, DMA, or AXI interface is included.
- UVM is intentionally not duplicated; the portfolio's AXI4 QoS fabric owns the reusable UVM/VIP story.
- PyTorch, Verilator, SymbiYosys, and Yosys results are open-source pre-silicon evidence, not accuracy certification or physical-design signoff.
