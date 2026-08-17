# Verification Plan

| Requirement | Stimulus | Independent checker | Assertion / coverage | Evidence |
| --- | --- | --- | --- | --- |
| Multicycle `K=4–64` MAC | Directed matrix + 100 seeds | PyTorch integer oracle | K, operand, accumulator, result bins | `rtl_vs_pytorch_summary.csv` |
| Asymmetric quantization | Input/weight/output zero-point classes | Exact adjusted dot product | Zero-point × ReLU × saturation crosses | `cross_coverage.csv` |
| Signed rounding and saturation | Positive/negative remainder boundaries | Signed round-to-nearest model | Exact/remainder/result bins | `functional_coverage.csv` |
| Double-buffered parameters | Alternating bank commands and live inactive-bank writes | Bank-aware scoreboard | Active-bank protection and bank-swap properties | `protocol_edge_summary.csv` |
| Result FIFO and backpressure | Full FIFO, simultaneous pop/push, delayed output | Tagged output scoreboard | FIFO bounds/stability/accounting | assertions + edge test |
| Reset containment | Reset during accumulation | No ghost-result checker | reset clears command/FIFO state | edge test |
| Two-layer inference | Exported PyTorch MLP | Hidden and final word comparison | 128 exact word comparisons | `pytorch_mlp_rtl_summary.csv` |
| Checker sensitivity | Nine compile-time RTL defects | Existing model/assertions | Mutation detection | `mutation_summary.csv` |
| Solver evidence | Reduced 2×2 engine | SymbiYosys/Z3 | Safety plus non-vacuous covers | `formal_summary.csv` |
| Implementation scaling | 4×4 and 8×8 variants | Yosys elaboration/statistics | Warning-clean Verilator lint | `synthesis_summary.csv` |
| Portable simulation/FPGA contract | Packed configuration, command, activation, stall, and expected-result records | Exact RTL output/tag checks plus synthesizable health counters | completion accounting and stable result tag | `portable_validation_summary.csv` |
| AXI/control-plane integration | AXI-Lite register ordering/errors, AXI-Stream backpressure, packed decoder, end-to-end replay | Exact result/tag, counters, sticky error status, and decoder field checks | B/R/input/output stability plus 17 event-derived integration points | `axi_stream_integration_summary.csv`, `axi_stream_integration_coverage.csv` |
| GCC RV32I hardware/software co-verification | 40 cold/warm geometries, 25 operand corners, 15 output-stall configurations | Scalar C result and accelerator result independently compared with one PyTorch oracle | APB ownership, stream stability, command/chunk/result accounting, latency progression | `rv32_accel_benchmark.csv`, `rv32_accel_correctness.csv`, `rv32_accel_backpressure.csv` |
| Benchmark checker sensitivity | Dropped chunk, duplicate command, corrupted result, altered scalar rounding, frozen latency counter | Firmware comparisons, accounting checks, assertions, and timeouts | Five expected-fail buckets | `rv32_accel_mutations.csv` |

Functional and cross coverage are project-defined and derived from workloads that execute against RTL. Code coverage and formal results are reported independently.
