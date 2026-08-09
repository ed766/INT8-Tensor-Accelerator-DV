#!/usr/bin/env python3
"""Quantize a torch.nn.Linear layer and measure integer inference error."""

from __future__ import annotations

import csv
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    torch.manual_seed(2026)
    layer = torch.nn.Linear(4, 4, bias=True)
    inputs = torch.linspace(-1.0, 1.0, 64, dtype=torch.float32).reshape(16, 4)
    with torch.no_grad():
        float_output = layer(inputs)
        input_scale = max(float(inputs.abs().max()) / 127.0, 1e-9)
        weight_scale = torch.clamp(layer.weight.abs().amax(dim=1) / 127.0, min=1e-9)
        q_input = torch.clamp(torch.round(inputs / input_scale), -128, 127).to(torch.int32)
        q_weight = torch.clamp(torch.round(layer.weight / weight_scale[:, None]), -128, 127).to(torch.int32)
        q_bias = torch.round(layer.bias / (input_scale * weight_scale)).to(torch.int32)
        accumulator = torch.matmul(q_input, q_weight.T) + q_bias
        dequantized = accumulator.to(torch.float32) * (input_scale * weight_scale)[None, :]
        error = (float_output - dequantized).abs()
    row = {
        "model": "torch.nn.Linear(4,4)", "samples": inputs.shape[0],
        "input_scale": f"{input_scale:.8f}",
        "mean_absolute_error": f"{float(error.mean()):.8f}",
        "maximum_absolute_error": f"{float(error.max()):.8f}",
        "int32_accumulator_min": int(accumulator.min()),
        "int32_accumulator_max": int(accumulator.max()),
        "status": "PASS" if float(error.max()) < 0.02 else "FAIL",
    }
    with (ROOT / "reports" / "pytorch_linear_quantization.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    (ROOT / "docs" / "pytorch_linear_demo.md").write_text(
        "# PyTorch Linear Quantization Demo\n\n"
        "A deterministic `torch.nn.Linear(4, 4)` layer is converted to symmetric INT8 activations and "
        "per-output-channel INT8 weights. PyTorch computes the integer dot products and dequantizes the "
        "INT32 accumulator for comparison with the original floating-point layer.\n\n"
        "| Samples | Mean absolute error | Maximum absolute error | INT32 range | Status |\n"
        "| ---: | ---: | ---: | ---: | --- |\n"
        f"| {row['samples']} | {row['mean_absolute_error']} | {row['maximum_absolute_error']} | "
        f"{row['int32_accumulator_min']} to {row['int32_accumulator_max']} | {row['status']} |\n\n"
        "This demonstrates the model-to-integer mapping; the RTL regression uses exact integer comparisons, "
        "so floating-point tolerance is never used to excuse an RTL mismatch.\n"
    )
    print(f"PyTorch Linear quantization: {row['status']}, max error={row['maximum_absolute_error']}")
    return 0 if row["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
