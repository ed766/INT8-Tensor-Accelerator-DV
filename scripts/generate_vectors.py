#!/usr/bin/env python3
"""Generate multicycle INT8 linear-layer workloads with PyTorch as the oracle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import torch

OUTPUTS = 4
LANES = 4
MAX_K = 64


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
    bank: int = 0
    input_zp: int = 0
    weight_zp: torch.Tensor | None = None
    output_zp: torch.Tensor | None = None
    source_gap: int = 0
    sink_stall: int = 0
    family: str = "directed"

    def __post_init__(self) -> None:
        if self.weight_zp is None:
            self.weight_zp = torch.zeros(OUTPUTS, dtype=torch.int32)
        if self.output_zp is None:
            self.output_zp = torch.zeros(OUTPUTS, dtype=torch.int32)


def make_case(name: str, k: int, *, seed: int = 0, bank: int = 0,
              result: str = "mixed", input_zp: int = 0, weight_zp: int = 0,
              output_zp: int = 0, relu: bool = False, source_gap: int = 0,
              sink_stall: int = 0) -> Case:
    gen = torch.Generator().manual_seed(seed or (k * 101 + bank * 17 + len(name)))
    x = torch.randint(-32, 33, (k,), generator=gen, dtype=torch.int32)
    w = torch.randint(-16, 17, (OUTPUTS, k), generator=gen, dtype=torch.int32)
    bias = torch.randint(-64, 65, (OUTPUTS,), generator=gen, dtype=torch.int32)
    mult = torch.ones(OUTPUTS, dtype=torch.int32)
    shift = torch.zeros(OUTPUTS, dtype=torch.int32)
    relu_mask = 0b1111 if relu else 0
    if result == "zero":
        x.zero_(); w.zero_(); bias.zero_()
    elif result == "positive":
        x.fill_(3); w.fill_(1); bias.fill_(1)
    elif result == "negative":
        x.fill_(-3); w.fill_(1); bias.fill_(-1)
    elif result == "sat_pos":
        x.fill_(127); w.fill_(127); bias.zero_()
    elif result == "sat_neg":
        x.fill_(-128); w.fill_(127); bias.zero_()
    elif result == "relu_zero":
        x.fill_(-12); w.fill_(2); bias.zero_(); relu_mask = 0b1111
    return Case(name, seed, x, w, bias, mult, shift, relu_mask, bank,
                input_zp, torch.full((OUTPUTS,), weight_zp, dtype=torch.int32),
                torch.full((OUTPUTS,), output_zp, dtype=torch.int32),
                source_gap, sink_stall)


def directed_cases() -> list[Case]:
    cases: list[Case] = []
    for bank in (0, 1):
        for k in (4, 8, 16, 32, 64):
            cases.append(make_case(f"k{k}_bank{bank}", k, seed=100 + k + bank, bank=bank))
    for index, result in enumerate(("zero", "positive", "negative", "sat_pos", "sat_neg", "relu_zero")):
        cases.append(make_case(f"result_{result}", 8, bank=index & 1, result=result,
                               relu=result == "sat_pos"))
    for index, values in enumerate(((-7, 0, 0), (5, -3, 2), (17, 9, -11), (-13, 7, 19))):
        case = make_case(f"zero_points_{index}", 16, bank=index & 1,
                         input_zp=values[0], weight_zp=values[1], output_zp=values[2],
                         relu=bool(index & 1))
        if index == 0:
            case.x.fill_(values[0]); case.w.fill_(values[1]); case.bias.zero_()
        cases.append(case)
    for index, (mult, shift) in enumerate(((3, 1), (5, 2), (-3, 2), (-5, 3))):
        case = make_case(f"rounding_{index}", 8, bank=index & 1, seed=300 + index)
        case.mult.fill_(mult); case.shift.fill_(shift)
        cases.append(case)
    for index, (source_gap, sink_stall) in enumerate(((1, 0), (0, 2), (2, 6))):
        cases.append(make_case(f"pressure_{index}", 32, bank=index & 1, seed=400 + index,
                               source_gap=source_gap, sink_stall=sink_stall))
    corner_min = make_case("signed_extrema", 4, bank=0)
    corner_min.x = torch.tensor([-128, 127, -1, 1], dtype=torch.int32)
    corner_min.w = torch.tensor([
        [-128, 127, 1, -1], [127, -128, -1, 1], [1, 1, 1, 1], [-1, -1, -1, -1]
    ], dtype=torch.int32)
    cases.append(corner_min)
    bias_case = make_case("bias_boundaries", 4, bank=1, result="zero")
    bias_case.bias = torch.tensor([-129, -128, 127, 128], dtype=torch.int32)
    cases.append(bias_case)
    mixed = make_case("per_channel_quantization", 16, bank=0, seed=501, input_zp=-4)
    mixed.weight_zp = torch.tensor([-3, 0, 5, 11], dtype=torch.int32)
    mixed.output_zp = torch.tensor([-9, 0, 7, 13], dtype=torch.int32)
    mixed.mult = torch.tensor([1, 3, -5, 7], dtype=torch.int32)
    mixed.shift = torch.tensor([0, 1, 2, 3], dtype=torch.int32)
    mixed.relu_mask = 0b1010
    cases.append(mixed)
    assert len(cases) == 30
    return cases


def random_cases(count: int = 100) -> list[Case]:
    cases: list[Case] = []
    k_values = (4, 8, 16, 32, 64)
    for seed in range(1, count + 1):
        gen = torch.Generator().manual_seed(0xACC000 + seed)
        k = k_values[(seed - 1) % len(k_values)]
        x = torch.randint(-128, 128, (k,), generator=gen, dtype=torch.int32)
        w = torch.randint(-128, 128, (OUTPUTS, k), generator=gen, dtype=torch.int32)
        bias = torch.randint(-1024, 1025, (OUTPUTS,), generator=gen, dtype=torch.int32)
        mult = torch.randint(-7, 8, (OUTPUTS,), generator=gen, dtype=torch.int32)
        mult[mult == 0] = 1
        shift = torch.randint(0, 6, (OUTPUTS,), generator=gen, dtype=torch.int32)
        cases.append(Case(
            name=f"random_seed_{seed:03d}", seed=seed, x=x, w=w, bias=bias,
            mult=mult, shift=shift, relu_mask=seed & 0xF, bank=(seed // 3) & 1,
            input_zp=int(torch.randint(-16, 17, (), generator=gen)),
            weight_zp=torch.randint(-16, 17, (OUTPUTS,), generator=gen, dtype=torch.int32),
            output_zp=torch.randint(-16, 17, (OUTPUTS,), generator=gen, dtype=torch.int32),
            source_gap=seed % 4, sink_stall=(seed * 5) % 8, family="random",
        ))
    return cases


def rounded_shift(product: torch.Tensor, shift: torch.Tensor) -> torch.Tensor:
    magnitude = torch.abs(product)
    offset = torch.where(shift == 0, torch.zeros_like(shift), torch.bitwise_left_shift(torch.ones_like(shift), shift - 1))
    rounded = torch.bitwise_right_shift(magnitude + offset, shift)
    return torch.where(product < 0, -rounded, rounded)


def evaluate(case: Case) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    adjusted_x = case.x.to(torch.int64) - case.input_zp
    adjusted_w = case.w.to(torch.int64) - case.weight_zp.to(torch.int64).reshape(-1, 1)
    accumulator = torch.matmul(adjusted_w, adjusted_x) + case.bias.to(torch.int64)
    product = accumulator * case.mult.to(torch.int64)
    scaled = rounded_shift(product, case.shift.to(torch.int64)) + case.output_zp.to(torch.int64)
    for channel in range(OUTPUTS):
        if case.relu_mask & (1 << channel):
            scaled[channel] = torch.clamp(scaled[channel], min=0)
    return accumulator, product, torch.clamp(scaled, -128, 127).to(torch.int32)


def pack(values: torch.Tensor) -> int:
    return sum((int(value) & 0xFF) << (index * 8) for index, value in enumerate(values.tolist()))


def signed32(value: int) -> int:
    return value - (1 << 32) if value & (1 << 31) else value


def result_class(value: int, product: int, relu: bool, output_zp: int) -> str:
    if value == 127 and product > 127:
        return "sat_pos"
    if value == -128 and product < -128:
        return "sat_neg"
    if value == 0 and relu and product + output_zp < 0:
        return "relu_zero"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def write_function(lines: list[str], name: str, entries: list[tuple[tuple[int, ...], int]], args: list[str]) -> None:
    signature = ", ".join(f"input integer {arg}" for arg in args)
    lines += [f"function automatic integer signed {name}({signature});", "  begin"]
    if len(args) == 1:
        lines += [f"    case ({args[0]})"]
        lines += [f"      {key[0]}: {name} = {value};" for key, value in entries]
    else:
        expression = " + ".join(f"({arg} * {1000 ** index})" for index, arg in enumerate(args))
        lines += [f"    case ({expression})"]
        for key, value in entries:
            encoded = sum(component * (1000 ** index) for index, component in enumerate(key))
            lines.append(f"      {encoded}: {name} = {value};")
    lines += [f"      default: {name} = 0;", "    endcase", "  end", "endfunction"]


def write_svh(path: Path, cases: list[Case], rows: list[dict[str, object]]) -> None:
    lines = [f"localparam integer NUM_CASES = {len(cases)};"]
    scalar_names = ("k", "bank", "tag", "relu_mask", "source_gap", "sink_stall", "input_zp", "expected_word")
    for field in scalar_names:
        write_function(lines, f"case_{field}", [
            ((i,), signed32(int(row[field])) if field == "expected_word" else int(row[field]))
            for i, row in enumerate(rows)
        ], ["c"])
    for field in ("bias", "multiplier", "shift", "weight_zp", "output_zp"):
        entries = []
        for case_index, row in enumerate(rows):
            for output_index, value in enumerate(json.loads(str(row[field]))):
                entries.append(((case_index, output_index), int(value)))
        write_function(lines, f"case_{field}", entries, ["c", "o"])
    weight_entries = []
    input_entries = []
    for case_index, case in enumerate(cases):
        for output_index in range(OUTPUTS):
            for k_index, value in enumerate(case.w[output_index].tolist()):
                weight_entries.append(((case_index, output_index, k_index), int(value)))
        for k_index, value in enumerate(case.x.tolist()):
            input_entries.append(((case_index, k_index), int(value)))
    write_function(lines, "case_weight", weight_entries, ["c", "o", "k"])
    write_function(lines, "case_input", input_entries, ["c", "k"])
    lines += ["function automatic string case_name(input integer c);", "  begin", "    case (c)"]
    lines += [f'      {index}: case_name = "{row["name"]}";' for index, row in enumerate(rows)]
    lines += ['      default: case_name = "unknown";', "    endcase", "  end", "endfunction", ""]
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    args.build_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    cases = directed_cases() + random_cases()
    rows: list[dict[str, object]] = []
    previous_bank: int | None = None
    for tag, case in enumerate(cases):
        accumulator, product, output = evaluate(case)
        rows.append({
            "case": tag, "name": case.name, "family": case.family, "seed": case.seed,
            "tag": tag & 0xFF, "k": len(case.x), "bank": case.bank,
            "input": json.dumps(case.x.tolist()), "weights": json.dumps(case.w.flatten().tolist()),
            "bias": json.dumps(case.bias.tolist()), "multiplier": json.dumps(case.mult.tolist()),
            "shift": json.dumps(case.shift.tolist()), "relu_mask": case.relu_mask,
            "input_zp": case.input_zp, "weight_zp": json.dumps(case.weight_zp.tolist()),
            "output_zp": json.dumps(case.output_zp.tolist()), "source_gap": case.source_gap,
            "sink_stall": case.sink_stall, "expected_word": pack(output),
            "accumulator": json.dumps(accumulator.tolist()), "product": json.dumps(product.tolist()),
            "expected": json.dumps(output.tolist()), "bank_swap": int(previous_bank is not None and previous_bank != case.bank),
            "result_classes": json.dumps([
                result_class(int(output[i]), int(product[i]), bool(case.relu_mask & (1 << i)), int(case.output_zp[i]))
                for i in range(OUTPUTS)
            ]),
        })
        previous_bank = case.bank
    with (args.report_dir / "scenario_manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    write_svh(args.build_dir / "generated_vectors.svh", cases, rows)
    digest = hashlib.sha256((args.report_dir / "scenario_manifest.csv").read_bytes()).hexdigest()
    (args.report_dir / "pytorch_model_summary.md").write_text(
        "# PyTorch Golden Model\n\n"
        f"- PyTorch version: `{torch.__version__.split('+', 1)[0]}`\n"
        f"- Workloads: `{len(rows)}` (`30` directed + `100` seeded random)\n"
        f"- Manifest SHA-256: `{digest}`\n"
        "- Arithmetic: asymmetric signed INT8 inputs and weights, INT32 accumulation, per-channel "
        "round-to-nearest requantization, output zero point, optional ReLU, and INT8 saturation.\n"
    )
    print(f"Generated {len(rows)} multicycle PyTorch-backed workloads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
