# Two-Layer PyTorch to RTL Demonstration

A deterministic `Linear(16,4)-ReLU-Linear(4,4)` network is calibrated and quantized in PyTorch. Layer-one weights are placed in parameter bank 0 and layer-two weights in bank 1. For each sample:

1. RTL executes the 16-element first-layer command.
2. All four observed hidden activation bytes are checked against PyTorch.
3. Those observed RTL bytes become the second layer's input.
4. All four final logits are checked exactly.

Floating-point and quantized PyTorch predictions are compared separately from the bit-exact quantized PyTorch/RTL check. See `reports/pytorch_mlp_summary.csv` and `reports/pytorch_mlp_rtl_summary.csv`.
