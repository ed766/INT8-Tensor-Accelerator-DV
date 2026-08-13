#!/usr/bin/env python3
"""Hand-computed checks for asymmetric quantization and rounding."""

from __future__ import annotations

import torch


def requant(x: torch.Tensor, w: torch.Tensor, bias: torch.Tensor, mult: torch.Tensor,
            shift: torch.Tensor, input_zp: int = 0, weight_zp: torch.Tensor | None = None,
            output_zp: torch.Tensor | None = None) -> torch.Tensor:
    weight_zp = torch.zeros(w.shape[0], dtype=torch.int64) if weight_zp is None else weight_zp.to(torch.int64)
    output_zp = torch.zeros(w.shape[0], dtype=torch.int64) if output_zp is None else output_zp.to(torch.int64)
    acc = torch.matmul(w.to(torch.int64) - weight_zp[:, None], x.to(torch.int64) - input_zp) + bias
    product = acc * mult.to(torch.int64)
    magnitude = product.abs()
    offset = torch.where(shift == 0, torch.zeros_like(shift), torch.bitwise_left_shift(torch.ones_like(shift), shift - 1))
    rounded = torch.bitwise_right_shift(magnitude + offset, shift)
    scaled = torch.where(product < 0, -rounded, rounded) + output_zp
    return torch.clamp(scaled, -128, 127).to(torch.int32)


def main() -> int:
    identity = torch.eye(4, dtype=torch.int32)
    ones = torch.ones(4, dtype=torch.int32)
    zeros = torch.zeros(4, dtype=torch.int32)
    assert requant(torch.tensor([1, -2, 3, -4]), identity, zeros, ones, zeros).tolist() == [1, -2, 3, -4]
    assert requant(torch.tensor([127, 127, 127, 127]), torch.full((4, 4), 127), zeros, ones, zeros).tolist() == [127] * 4
    assert requant(torch.tensor([-128, -128, -128, -128]), torch.full((4, 4), 127), zeros, ones, zeros).tolist() == [-128] * 4
    assert requant(torch.tensor([16, -16, 8, -8]), identity, zeros,
                   torch.tensor([2, 2, 4, 4]), torch.tensor([1, 1, 2, 2])).tolist() == [16, -16, 8, -8]
    assert requant(torch.tensor([7, 7, 7, 7]), identity, zeros, ones, zeros, input_zp=7).tolist() == [0, 0, 0, 0]
    assert requant(torch.tensor([2, 0, 0, 0]), identity, zeros, torch.tensor([1, 1, 1, 1]),
                   torch.tensor([1, 1, 1, 1])).tolist()[0] == 1
    assert requant(torch.tensor([-3, 0, 0, 0]), identity, zeros, torch.tensor([1, 1, 1, 1]),
                   torch.tensor([1, 1, 1, 1])).tolist()[0] == -2
    assert requant(torch.zeros(4,dtype=torch.int64), torch.zeros((4,4),dtype=torch.int64), zeros, ones, zeros,
                   output_zp=torch.tensor([-3,0,3,7])).tolist() == [-3,0,3,7]
    print(f"PyTorch model self-test: 8 / 8 PASS (torch {torch.__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
