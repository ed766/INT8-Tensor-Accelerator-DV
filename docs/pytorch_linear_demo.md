# PyTorch Linear Quantization Demo

A deterministic `torch.nn.Linear(4, 4)` layer is converted to symmetric INT8 activations and per-output-channel INT8 weights. PyTorch computes the integer dot products and dequantizes the INT32 accumulator for comparison with the original floating-point layer.

| Samples | Mean absolute error | Maximum absolute error | INT32 range | Status |
| ---: | ---: | ---: | ---: | --- |
| 16 | 0.00166904 | 0.00470918 | -15799 to 43567 | PASS |

This demonstrates the model-to-integer mapping; the RTL regression uses exact integer comparisons, so floating-point tolerance is never used to excuse an RTL mismatch.
