# Mutation Validation

| Mutation | Injected fault | Expected detection |
| --- | --- | --- |
| `MUT_UNSIGNED_MAC` | Treat signed operands as unsigned | PyTorch result mismatch |
| `MUT_RELU_BYPASS` | Disable the negative ReLU clamp | Directed and cross-case mismatch |
| `MUT_SATURATION_WRAP` | Wrap instead of saturating to INT8 | Positive/negative saturation mismatch |
| `MUT_TAG_CORRUPT` | Flip the output tag LSB | Tag scoreboard failure |

Mutations are compiled one at a time and pass validation only when the nominal checker or assertion detects the injected defect. A compile failure is not counted as detection.
