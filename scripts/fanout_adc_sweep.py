#!/usr/bin/env python3
"""Measure two-head inference sensitivity to a fixed-range ADC model."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import torch

from fx_graph_compiler import GraphProgram, compile_fanout, rounded_shift


BITS = (4, 6, 8, 10, 12, 16)
RANGE_BITS = 15


def convert_adc(accumulator, bits):
    """Round to signed ADC codes, clamp, then decode in accumulator units."""
    step_shift = RANGE_BITS + 1 - bits
    minimum, maximum = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    code = rounded_shift(accumulator, step_shift)
    clipped = (code < minimum) | (code > maximum)
    return code.clamp(minimum, maximum) * (1 << step_shift), clipped


def replay(program: GraphProgram, bits: int | None, device: str):
    inputs = torch.tensor(program.inputs, dtype=torch.int64, device=device)
    outputs, clipped = [], []
    for index, layer in enumerate(program.layers):
        source = inputs if index == 0 else outputs[0]
        weights = torch.tensor(layer.weights, dtype=torch.int64, device=device)
        biases = torch.tensor(layer.biases, dtype=torch.int64, device=device)
        # Batch all samples and output channels using integer ops on CPU and CUDA.
        accumulator = (source[:, None, :] * weights[None, :, :]).sum(dim=-1) + biases
        if bits is None:
            mask = torch.zeros_like(accumulator, dtype=torch.bool)
        else:
            accumulator, mask = convert_adc(accumulator, bits)
        outputs.append(rounded_shift(accumulator, layer.shift).clamp(0 if layer.relu else -128, 127))
        clipped.append(mask)
    return torch.stack(outputs, dim=1).cpu(), torch.stack(clipped, dim=1).cpu()


def run_checks(program):
    values = torch.tensor([-40000, -6144, -2048, -2047, 0, 2047, 2048, 6144, 30720, 40000])
    decoded, clipped = convert_adc(values, 4)
    expected = [-32768, -8192, -4096, 0, 0, 0, 4096, 8192, 28672, 28672]
    if decoded.tolist() != expected or clipped.tolist() != [
        True, False, False, False, False, False, False, False, True, True
    ]:
        raise RuntimeError("ADC clipping or half-away-from-zero rounding failed")
    golden = torch.tensor(program.expected)
    bypass, _ = replay(program, None, "cpu")
    if not torch.equal(bypass, golden):
        raise RuntimeError("ADC bypass differs from the compiler golden bytes")
    return golden


def write_plot(rows, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 3, figsize=(10.5, 3.1), layout="constrained")
    for axis, field, title in zip(
        axes,
        ("mae_lsb", "changed_pct", "adc_clipped_pct"),
        ("Mean error (INT8 LSB)", "Outputs changed (%)", "ADC conversions clipped (%)"),
        strict=True,
    ):
        for layer, linestyle in (("trunk", ":"), ("head1", "-"), ("head2", "--")):
            points = [row for row in rows if row["layer"] == layer]
            axis.plot(BITS, [row[field] for row in points], linestyle, marker="o", label=layer)
        axis.set(title=title, xlabel="ADC bits", xticks=BITS, ylim=(0, None))
        axis.grid(alpha=0.25)
    axes[0].legend()
    figure.suptitle("Fixed-range ADC sensitivity on the shared-trunk INT8 graph")
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("build/fanout-adc"))
    parser.add_argument("--cuda", action="store_true", help="also check exact CUDA parity")
    parser.add_argument("--no-plot", action="store_true", help="skip the optional matplotlib dependency")
    args = parser.parse_args()
    if args.cuda and not torch.cuda.is_available():
        parser.error("--cuda requires a CUDA-enabled PyTorch installation and GPU")

    program = compile_fanout()
    golden = run_checks(program)
    if args.cuda:
        cuda_bypass, _ = replay(program, None, "cuda")
        if not torch.equal(cuda_bypass, golden):
            raise RuntimeError("CUDA bypass differs from the compiler golden bytes")

    rows = []
    for bits in BITS:
        values, clipped = replay(program, bits, "cpu")
        if args.cuda:
            cuda_values, cuda_clipped = replay(program, bits, "cuda")
            if not torch.equal(values, cuda_values) or not torch.equal(clipped, cuda_clipped):
                raise RuntimeError(f"CPU/CUDA mismatch at {bits} ADC bits")
        error = (values - golden).abs()
        for index, name in enumerate(("trunk", "head1", "head2")):
            delta = error[:, index, :]
            mask = clipped[:, index, :]
            rows.append(dict(bits=bits, layer=name, values=delta.numel(),
                             mae_lsb=delta.sum().item() / delta.numel(),
                             changed_pct=100 * delta.count_nonzero().item() / delta.numel(),
                             adc_clipped_pct=100 * mask.count_nonzero().item() / mask.numel()))

    args.out.mkdir(parents=True, exist_ok=True)
    fixture = asdict(program)
    fixture.pop("float_mae")  # Only the exact integer workload is needed for replay.
    encoded = json.dumps(fixture, sort_keys=True).encode()
    with (args.out / "sweep.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    config = dict(schema="fanout-adc-v1", torch_version=torch.__version__,
                  bit_widths=BITS, nominal_half_range=1 << RANGE_BITS,
                  boundary="post-bias and pre-requantization on each Linear",
                  rounding="nearest, ties away from zero", signed_codes=True,
                  fixture_sha256=hashlib.sha256(encoded).hexdigest(), fixture=fixture,
                  checks=dict(hand_calculated="pass", bypass="pass",
                              cuda_parity="pass" if args.cuda else "not run"))
    (args.out / "experiment.json").write_text(json.dumps(config, indent=2) + "\n")
    if not args.no_plot:
        write_plot(rows, args.out / "sweep.png")
    print(f"PASS: golden bypass and hand-calculated ADC checks. Evidence: {args.out}")
    if args.cuda:
        print("PASS: CPU/CUDA output and clipping mask matched at every bit width.")


if __name__ == "__main__":
    main()
