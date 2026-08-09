#!/usr/bin/env python3
"""Generate deterministic INT8 accelerator vectors with PyTorch as the oracle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import torch


@dataclass
class Case:
    name: str
    seed: int
    x: torch.Tensor
    w: torch.Tensor
    bias: torch.Tensor
    mult: torch.Tensor
    shift: torch.Tensor
    relu_mask: int
    source_gap: int = 0
    sink_stall: int = 0
    family: str = "directed"


def tensor(values: list[int], shape: tuple[int, ...]) -> torch.Tensor:
    return torch.tensor(values, dtype=torch.int32).reshape(shape)


def identity_case(name: str, x: list[int], **kwargs: object) -> Case:
    return Case(
        name=name,
        seed=0,
        x=tensor(x, (4,)),
        w=torch.eye(4, dtype=torch.int32),
        bias=torch.zeros(4, dtype=torch.int32),
        mult=torch.ones(4, dtype=torch.int32),
        shift=torch.zeros(4, dtype=torch.int32),
        relu_mask=0,
        **kwargs,
    )


def directed_cases() -> list[Case]:
    cases = [
        identity_case("zero", [0, 0, 0, 0]),
        identity_case("identity_positive", [1, 7, 63, 127]),
        identity_case("identity_signed", [-1, -8, 9, 42]),
        identity_case("input_corners", [-128, 127, 0, 1]),
        Case("bias_only", 0, tensor([0, 0, 0, 0], (4,)), torch.zeros((4, 4), dtype=torch.int32),
             tensor([-5, 0, 5, 127], (4,)), torch.ones(4, dtype=torch.int32),
             torch.zeros(4, dtype=torch.int32), 0),
        Case("relu_clamp", 0, tensor([-4, 3, -2, 5], (4,)), torch.eye(4, dtype=torch.int32),
             torch.zeros(4, dtype=torch.int32), torch.ones(4, dtype=torch.int32),
             torch.zeros(4, dtype=torch.int32), 0b1111),
        Case("positive_saturation", 0, tensor([127, 127, 127, 127], (4,)),
             torch.full((4, 4), 127, dtype=torch.int32), torch.zeros(4, dtype=torch.int32),
             torch.ones(4, dtype=torch.int32), torch.zeros(4, dtype=torch.int32), 0),
        Case("negative_saturation", 0, tensor([-128, -128, -128, -128], (4,)),
             torch.full((4, 4), 127, dtype=torch.int32), torch.zeros(4, dtype=torch.int32),
             torch.ones(4, dtype=torch.int32), torch.zeros(4, dtype=torch.int32), 0),
        Case("scaled_shift", 0, tensor([16, -16, 32, -32], (4,)), torch.eye(4, dtype=torch.int32),
             tensor([1, -1, 3, -3], (4,)), tensor([2, 3, 4, 5], (4,)),
             tensor([1, 2, 2, 3], (4,)), 0),
        Case("mixed_channels", 0, tensor([3, -5, 7, -9], (4,)),
             tensor([1, 2, 3, 4, -4, 3, -2, 1, 7, 0, -7, 1, -1, -1, -1, -1], (4, 4)),
             tensor([0, 2, -3, 4], (4,)), torch.ones(4, dtype=torch.int32),
             torch.zeros(4, dtype=torch.int32), 0b0101),
        identity_case("source_gap", [2, -3, 4, -5], source_gap=3),
        identity_case("sink_backpressure", [5, -6, 7, -8], sink_stall=5),
        identity_case("source_and_sink_backpressure", [-9, 10, -11, 12], source_gap=2, sink_stall=4),
        Case("weight_corners", 0, tensor([1, 1, 1, 1], (4,)),
             tensor([-128, 127, 0, 1, 127, -128, 1, 0, 0, 1, -128, 127, 1, 0, 127, -128], (4, 4)),
             torch.zeros(4, dtype=torch.int32), torch.ones(4, dtype=torch.int32),
             torch.zeros(4, dtype=torch.int32), 0),
    ]
    return cases


def cross_cases() -> list[Case]:
    cases: list[Case] = []
    classes = ("positive", "negative", "zero", "sat_pos", "sat_neg", "relu_zero")
    for channel in range(4):
        for result_class in classes:
            w = torch.zeros((4, 4), dtype=torch.int32)
            x = torch.zeros(4, dtype=torch.int32)
            bias = torch.zeros(4, dtype=torch.int32)
            relu = 0
            if result_class == "positive":
                x[channel] = 9
                w[channel, channel] = 3
            elif result_class == "negative":
                x[channel] = -9
                w[channel, channel] = 3
            elif result_class == "sat_pos":
                x[channel] = 127
                w[channel, channel] = 127
            elif result_class == "sat_neg":
                x[channel] = -128
                w[channel, channel] = 127
            elif result_class == "relu_zero":
                x[channel] = -12
                w[channel, channel] = 2
                relu = 1 << channel
            cases.append(Case(
                name=f"cross_{result_class}_ch{channel}", seed=0, x=x, w=w, bias=bias,
                mult=torch.ones(4, dtype=torch.int32), shift=torch.zeros(4, dtype=torch.int32),
                relu_mask=relu, source_gap=channel & 1, sink_stall=(channel + 1) % 3,
                family="cross",
            ))
    return cases


def random_cases(count: int = 25) -> list[Case]:
    cases: list[Case] = []
    for seed in range(1, count + 1):
        gen = torch.Generator().manual_seed(seed)
        x = torch.randint(-128, 128, (4,), generator=gen, dtype=torch.int32)
        w = torch.randint(-128, 128, (4, 4), generator=gen, dtype=torch.int32)
        bias = torch.randint(-256, 257, (4,), generator=gen, dtype=torch.int32)
        mult = torch.randint(1, 5, (4,), generator=gen, dtype=torch.int32)
        shift = torch.randint(0, 5, (4,), generator=gen, dtype=torch.int32)
        cases.append(Case(
            name=f"random_seed_{seed:02d}", seed=seed, x=x, w=w, bias=bias,
            mult=mult, shift=shift, relu_mask=seed & 0xF,
            source_gap=seed % 4, sink_stall=(seed * 3) % 7, family="random",
        ))
    return cases


def evaluate(case: Case) -> tuple[torch.Tensor, torch.Tensor]:
    accumulator = torch.matmul(case.w.to(torch.int32), case.x.to(torch.int32)) + case.bias
    product = accumulator.to(torch.int64) * case.mult.to(torch.int64)
    scaled = torch.bitwise_right_shift(product, case.shift.to(torch.int64))
    for channel in range(4):
        if case.relu_mask & (1 << channel):
            scaled[channel] = torch.clamp(scaled[channel], min=0)
    return accumulator, torch.clamp(scaled, -128, 127).to(torch.int32)


def pack(values: torch.Tensor) -> int:
    word = 0
    for index, value in enumerate(values.tolist()):
        word |= (int(value) & 0xFF) << (index * 8)
    return word


def signed32(value: int) -> int:
    return value - (1 << 32) if value & (1 << 31) else value


def result_class(value: int, accumulator: int, relu: bool) -> str:
    if value == 127 and accumulator > 127:
        return "sat_pos"
    if value == -128 and accumulator < -128:
        return "sat_neg"
    if value == 0 and relu and accumulator < 0:
        return "relu_zero"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def write_svh(path: Path, rows: list[dict[str, object]]) -> None:
    fields = {
        "F_INPUT_WORD": 0, "F_EXPECTED_WORD": 1, "F_TAG": 2, "F_RELU_MASK": 3,
        "F_SOURCE_GAP": 4, "F_SINK_STALL": 5, "F_WEIGHT_BASE": 6,
        "F_BIAS_BASE": 22, "F_MULT_BASE": 26, "F_SHIFT_BASE": 30,
    }
    lines = [f"localparam integer NUM_CASES = {len(rows)};"]
    lines.extend(f"localparam integer {name} = {value};" for name, value in fields.items())
    lines += [
        "function automatic integer signed case_field(input integer c, input integer f);",
        "  begin",
        "    case (c)",
    ]
    for index, row in enumerate(rows):
        values = [
            signed32(int(row["input_word"])), signed32(int(row["expected_word"])), int(row["tag"]),
            int(row["relu_mask"]), int(row["source_gap"]), int(row["sink_stall"]),
            *json.loads(str(row["weights"])), *json.loads(str(row["bias"])),
            *json.loads(str(row["multiplier"])), *json.loads(str(row["shift"])),
        ]
        lines.append(f"      {index}: case (f)")
        lines.extend(f"        {field}: case_field = {value};" for field, value in enumerate(values))
        lines += ["        default: case_field = 0;", "      endcase"]
    lines += ["      default: case_field = 0;", "    endcase", "  end", "endfunction"]
    lines += ["function automatic string case_name(input integer c);", "  begin", "    case (c)"]
    lines.extend(f'      {index}: case_name = "{row["name"]}";' for index, row in enumerate(rows))
    lines += ['      default: case_name = "unknown";', "    endcase", "  end", "endfunction", ""]
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    args.build_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)

    cases = directed_cases() + cross_cases() + random_cases()
    rows: list[dict[str, object]] = []
    for tag, case in enumerate(cases):
        accumulator, output = evaluate(case)
        row: dict[str, object] = {
            "case": tag, "name": case.name, "family": case.family, "seed": case.seed, "tag": tag,
            "input": json.dumps(case.x.tolist()), "weights": json.dumps(case.w.flatten().tolist()),
            "bias": json.dumps(case.bias.tolist()), "multiplier": json.dumps(case.mult.tolist()),
            "shift": json.dumps(case.shift.tolist()), "relu_mask": case.relu_mask,
            "source_gap": case.source_gap, "sink_stall": case.sink_stall,
            "input_word": pack(case.x), "expected_word": pack(output),
            "accumulator": json.dumps(accumulator.tolist()), "expected": json.dumps(output.tolist()),
            "result_classes": json.dumps([
                result_class(int(output[i]), int(accumulator[i]), bool(case.relu_mask & (1 << i)))
                for i in range(4)
            ]),
        }
        rows.append(row)

    fieldnames = list(rows[0])
    with (args.report_dir / "scenario_manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_svh(args.build_dir / "generated_vectors.svh", rows)
    digest = hashlib.sha256((args.report_dir / "scenario_manifest.csv").read_bytes()).hexdigest()
    (args.report_dir / "pytorch_model_summary.md").write_text(
        "# PyTorch Golden Model\n\n"
        f"- PyTorch version: `{torch.__version__.split('+', 1)[0]}` (runtime build suffix intentionally normalized)\n"
        f"- Deterministic scenarios: `{len(rows)}`\n"
        f"- Manifest SHA-256: `{digest}`\n"
        "- Arithmetic: signed INT8 inputs/weights, INT32 dot products and bias, "
        "signed fixed-point multiplier/right shift, optional ReLU, signed INT8 saturation.\n"
        "- The model predicts integer results independently of the RTL implementation.\n"
    )
    print(f"Generated {len(rows)} PyTorch-backed scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
