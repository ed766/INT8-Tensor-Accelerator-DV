# RTL Mutation Validation

| Mutation | Injected defect | Intended detection |
| --- | --- | --- |
| `MUT_UNSIGNED_MAC` | Interpret signed operands as unsigned | PyTorch result mismatch |
| `MUT_ZEROPOINT_BYPASS` | Ignore asymmetric input/weight offsets | Zero-point workloads |
| `MUT_ROUND_TRUNCATE` | Truncate instead of round | Signed remainder boundaries |
| `MUT_RELU_BYPASS` | Disable ReLU clamp | Negative ReLU cases |
| `MUT_SATURATION_WRAP` | Wrap instead of saturate | Positive/negative saturation |
| `MUT_TAG_CORRUPT` | Flip output tag LSB | Tag scoreboard/assertion |
| `MUT_BANK_ALIAS` | Force every command to bank zero | Alternating-bank workloads |
| `MUT_OUTPUT_ORDER` | Reverse output-channel packing | Exact word comparison |
| `MUT_K_LAST_EARLY` | Drop the terminal lane contribution | Multicycle K-boundary cases |

Each mutation must elaborate and execute. Detection requires an existing scoreboard or assertion failure; compilation failure is not counted.
