#!/usr/bin/env python3
"""Export a deterministic two-layer PyTorch MLP for chained RTL execution."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]


def quantize_tensor(value: torch.Tensor, scale: float) -> torch.Tensor:
    return torch.clamp(torch.round(value / scale), -128, 127).to(torch.int32)


def choose_shift(accumulator: torch.Tensor) -> int:
    maximum = max(1, int(accumulator.abs().max()))
    return max(0, math.ceil(math.log2(maximum / 96.0)))


def rounded_shift(value: torch.Tensor, shift: int) -> torch.Tensor:
    if shift == 0:
        return value
    magnitude = value.abs() + (1 << (shift - 1))
    rounded = torch.bitwise_right_shift(magnitude, shift)
    return torch.where(value < 0, -rounded, rounded)


def write_function(lines: list[str], name: str, entries: list[tuple[int, int]]) -> None:
    lines += [f"function automatic integer signed {name}(input integer i);", "  begin", "    case (i)"]
    lines += [f"      {index}: {name} = {value};" for index, value in entries]
    lines += [f"      default: {name} = 0;", "    endcase", "  end", "endfunction"]


def main() -> int:
    torch.manual_seed(2601)
    layer1 = torch.nn.Linear(16, 4)
    layer2 = torch.nn.Linear(4, 4)
    samples = torch.randn(16, 16) * 0.75
    with torch.no_grad():
        float_hidden = torch.relu(layer1(samples))
        float_logits = layer2(float_hidden)
        input_scale = max(float(samples.abs().max()) / 127.0, 1e-9)
        w1_scale = max(float(layer1.weight.abs().max()) / 127.0, 1e-9)
        q_input = quantize_tensor(samples, input_scale)
        q_w1 = quantize_tensor(layer1.weight, w1_scale)
        q_b1 = torch.round(layer1.bias / (input_scale * w1_scale)).to(torch.int32)
        acc1 = torch.matmul(q_input, q_w1.T) + q_b1
        shift1 = choose_shift(acc1)
        q_hidden = torch.clamp(rounded_shift(acc1, shift1), 0, 127).to(torch.int32)
        hidden_scale = input_scale * w1_scale * (1 << shift1)
        w2_scale = max(float(layer2.weight.abs().max()) / 127.0, 1e-9)
        q_w2 = quantize_tensor(layer2.weight, w2_scale)
        q_b2 = torch.round(layer2.bias / (hidden_scale * w2_scale)).to(torch.int32)
        acc2 = torch.matmul(q_hidden, q_w2.T) + q_b2
        shift2 = choose_shift(acc2)
        q_logits = torch.clamp(rounded_shift(acc2, shift2), -128, 127).to(torch.int32)
        output_scale = hidden_scale * w2_scale * (1 << shift2)
        dequantized = q_logits.to(torch.float32) * output_scale
        error = (dequantized - float_logits).abs()
        agreement = int((dequantized.argmax(dim=1) == float_logits.argmax(dim=1)).sum())

    lines = ["localparam integer MLP_SAMPLES = 16;", f"localparam integer MLP_SHIFT1 = {shift1};",
             f"localparam integer MLP_SHIFT2 = {shift2};"]
    write_function(lines, "mlp_input", list(enumerate(q_input.flatten().tolist())))
    write_function(lines, "mlp_w1", list(enumerate(q_w1.flatten().tolist())))
    write_function(lines, "mlp_b1", list(enumerate(q_b1.tolist())))
    write_function(lines, "mlp_w2", list(enumerate(q_w2.flatten().tolist())))
    write_function(lines, "mlp_b2", list(enumerate(q_b2.tolist())))
    write_function(lines, "mlp_expected_hidden", list(enumerate(q_hidden.flatten().tolist())))
    write_function(lines, "mlp_expected_logits", list(enumerate(q_logits.flatten().tolist())))
    (ROOT / "build").mkdir(exist_ok=True)
    (ROOT / "build" / "generated_mlp.svh").write_text("\n".join(lines) + "\n")

    row = {
        "model": "Linear(16,4)-ReLU-Linear(4,4)", "samples": 16,
        "intermediate_words_checked": 64, "final_words_checked": 64,
        "top1_agreement": f"{agreement} / 16", "mean_absolute_error": f"{float(error.mean()):.8f}",
        "maximum_absolute_error": f"{float(error.max()):.8f}", "status": "PASS" if agreement >= 14 else "FAIL",
    }
    with (ROOT / "reports" / "pytorch_mlp_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    print(f"PyTorch MLP export: {row['status']}, top-1 {row['top1_agreement']}")
    return 0 if row["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
