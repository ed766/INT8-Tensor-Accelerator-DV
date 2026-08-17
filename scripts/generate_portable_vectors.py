#!/usr/bin/env python3
"""Generate deterministic packed vectors shared by simulation and future FPGA hosts."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "portable" / "portable_vectors.mem"
META = ROOT / "portable" / "portable_vectors.json"
GOLDEN = ROOT / "reports" / "portable_golden.csv"
SEED = 0x51A7


def u8(value: int) -> int:
    return value & 0xFF


def requant(acc: int, multiplier: int, shift: int, relu: bool, output_zp: int) -> int:
    product = acc * multiplier
    magnitude = abs(product)
    scaled = product if shift == 0 else ((magnitude + (1 << (shift - 1))) >> shift) * (-1 if product < 0 else 1)
    scaled += output_zp
    if relu and scaled < 0:
        scaled = 0
    return max(-128, min(127, scaled))


def cfg(bank: int, kind: int, output: int, index: int, data: int) -> int:
    return (0 << 60) | (bank << 59) | (kind << 56) | (output << 54) | (index << 48) | ((data & 0xFFFFFFFF) << 16)


def main() -> int:
    rng = random.Random(SEED)
    words: list[int] = []
    golden: list[dict[str, str | int]] = []
    for case in range(6):
        bank = case & 1
        k = (4, 8, 16, 4, 8, 16)[case]
        tag = 0x40 + case
        input_zp = (-2, 0, 1, -1, 2, 0)[case]
        inputs = [rng.randint(-8, 8) for _ in range(k)]
        outputs: list[int] = []
        for output in range(4):
            weights = [rng.randint(-5, 5) for _ in range(k)]
            bias = (case - 2) * 3 + output
            multiplier = 1 + (case % 2)
            shift = case % 3
            relu = bool((case + output) % 2)
            weight_zp = (output % 3) - 1
            output_zp = output - 2
            for index, weight in enumerate(weights):
                words.append(cfg(bank, 0, output, index, u8(weight)))
            words.append(cfg(bank, 1, output, 0, bias))
            words.append(cfg(bank, 2, output, 0, (shift << 16) | (multiplier & 0xFFFF)))
            control = (u8(output_zp) << 24) | (u8(weight_zp) << 16) | (u8(input_zp) << 8) | int(relu)
            words.append(cfg(bank, 3, output, 0, control))
            acc = bias + sum((a - input_zp) * (w - weight_zp) for a, w in zip(inputs, weights))
            outputs.append(requant(acc, multiplier, shift, relu, output_zp))
        words.append((1 << 60) | (bank << 59) | (k << 52) | (tag << 44))
        for offset in range(0, k, 4):
            packed = sum(u8(inputs[offset + lane]) << (lane * 8) for lane in range(4))
            words.append((2 << 60) | (tag << 48) | packed)
        words.append((4 << 60) | ((case % 3) << 48))
        expected = sum(u8(outputs[index]) << (index * 8) for index in range(4))
        words.append((3 << 60) | (tag << 48) | expected)
        golden.append({"case": case, "tag": tag, "k": k, "bank": bank,
                       "expected": f"{expected:08x}", "stall_cycles": case % 3})
    words.append(0xF000000000000000)
    payload = "".join(f"{word:016x}\n" for word in words)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(payload)
    ROOT.joinpath("reports").mkdir(exist_ok=True)
    with GOLDEN.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=golden[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(golden)
    META.write_text(json.dumps({
        "schema": "int8-portable-v1", "seed": SEED, "cases": len(golden),
        "records": len(words), "sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }, indent=2) + "\n")
    print(f"PORTABLE_GENERATE|status=PASS|cases={len(golden)}|records={len(words)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
