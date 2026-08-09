#!/usr/bin/env python3
"""Small hand-computed checks for the PyTorch integer oracle."""

from __future__ import annotations

import torch


def requant(x: torch.Tensor, w: torch.Tensor, bias: torch.Tensor, mult: torch.Tensor, shift: torch.Tensor) -> torch.Tensor:
    acc = torch.matmul(w.to(torch.int32), x.to(torch.int32)) + bias
    scaled = torch.bitwise_right_shift(acc.to(torch.int64) * mult.to(torch.int64), shift.to(torch.int64))
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
    print(f"PyTorch model self-test: 4 / 4 PASS (torch {torch.__version__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
