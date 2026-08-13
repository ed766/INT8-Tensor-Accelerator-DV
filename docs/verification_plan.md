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

Functional and cross coverage are project-defined and derived from workloads that execute against RTL. Code coverage and formal results are reported independently.
