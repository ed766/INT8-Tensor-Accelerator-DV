# Verification Plan

| Requirement | Stimulus | Checker | Assertion / coverage | Evidence |
| --- | --- | --- | --- | --- |
| Signed INT8 dot product | Directed corners + 25 seeds | PyTorch integer oracle | Signed/zero/corner bins | `rtl_vs_pytorch_summary.csv` |
| Bias and requantization | Per-channel multiplier/shift matrix | Exact output-word comparison | Unit/scaled and zero/nonzero shift | `functional_coverage.csv` |
| ReLU and saturation | Negative, positive, overflow cases | Exact signed INT8 result | Six result classes per channel | `cross_coverage.csv` |
| Ready/valid ordering | Source gaps and sink stalls | Tag and count scoreboard | Stability, occupancy, prior-accept assertions | Simulation log |
| Steady-state throughput | 16 consecutive tagged vectors | Cycle-by-cycle output scoreboard | Simultaneous retire/accept | `streaming_throughput.csv` |
| Checker sensitivity | Four compile-time RTL defects | Expected mismatch/assertion failure | Mutation status | `mutation_summary.csv` |
| Implementation proxy | Reviewed 4×4 configuration | Yosys elaboration/statistics | Warning-clean lint | `synthesis_summary.csv` |
| Latency sensitivity | Output stalls from 0–6 cycles | Measured accept-to-output cycles | p50/p95/max | `performance_summary.csv` |

Functional coverage is project-defined and traceable to scenario data. Raw Verilator code coverage is reported separately. Neither is a commercial coverage-signoff claim.
