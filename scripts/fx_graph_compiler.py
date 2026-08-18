#!/usr/bin/env python3
"""Compile supported torch.fx graphs into bit-exact accelerator programs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.fx import symbolic_trace

ROOT = Path(__file__).resolve().parents[1]
MAX_LAYERS = 3
MAX_K = 64
OUTPUTS = 4


@dataclass
class LayerProgram:
    name: str
    k: int
    relu: bool
    weights: list[list[int]]
    biases: list[int]
    shift: int


@dataclass
class GraphProgram:
    name: str
    seed: int
    input_k: int
    nodes: list[str]
    layers: list[LayerProgram]
    inputs: list[list[int]]
    expected: list[list[list[int]]]
    float_mae: float


def rounded_shift(value: torch.Tensor, shift: int) -> torch.Tensor:
    if shift == 0:
        return value
    magnitude = value.abs() + (1 << (shift - 1))
    rounded = torch.bitwise_right_shift(magnitude, shift)
    return torch.where(value < 0, -rounded, rounded)


def choose_shift(accumulator: torch.Tensor) -> int:
    maximum = max(1, int(accumulator.abs().max()))
    return min(31, max(0, math.ceil(math.log2(maximum / 96.0))))


def build_model(seed: int, input_k: int, layer_count: int, relu_mask: int) -> nn.Sequential:
    torch.manual_seed(seed)
    modules: list[nn.Module] = []
    width = input_k
    for layer in range(layer_count):
        modules.append(nn.Linear(width, OUTPUTS))
        if (relu_mask >> layer) & 1:
            modules.append(nn.ReLU())
        width = OUTPUTS
    return nn.Sequential(*modules).eval()


def compile_model(name: str, seed: int, model: nn.Module, input_k: int) -> GraphProgram:
    traced = symbolic_trace(model)
    modules = dict(traced.named_modules())
    nodes = [f"{node.op}:{node.target}" for node in traced.graph.nodes]
    linear_nodes: list[tuple[str, nn.Linear, bool]] = []
    graph_nodes = list(traced.graph.nodes)
    for index, node in enumerate(graph_nodes):
        if node.op in {"placeholder", "output"}:
            continue
        if node.op != "call_module":
            raise ValueError(f"{name}: unsupported FX operation {node.op}:{node.target}")
        module = modules[str(node.target)]
        if isinstance(module, nn.ReLU):
            continue
        if not isinstance(module, nn.Linear):
            raise ValueError(f"{name}: unsupported module {type(module).__name__}")
        if module.out_features != OUTPUTS or module.in_features not in {4, 8, 16, 32, 64}:
            raise ValueError(f"{name}: Linear geometry {module.in_features}x{module.out_features} is unsupported")
        relu = False
        if index + 1 < len(graph_nodes):
            next_node = graph_nodes[index + 1]
            relu = next_node.op == "call_module" and isinstance(modules.get(str(next_node.target)), nn.ReLU)
        linear_nodes.append((str(node.target), module, relu))
    if not 1 <= len(linear_nodes) <= MAX_LAYERS:
        raise ValueError(f"{name}: requires 1..{MAX_LAYERS} Linear layers")

    generator = torch.Generator().manual_seed(seed ^ 0xF00D)
    float_inputs = torch.randn((4, input_k), generator=generator) * 0.6
    input_scale = max(float(float_inputs.abs().max()) / 96.0, 1e-9)
    quant = torch.clamp(torch.round(float_inputs / input_scale), -128, 127).to(torch.int64)
    inputs = quant.tolist()
    expected: list[list[list[int]]] = [[] for _ in inputs]
    layers: list[LayerProgram] = []
    activation_scale = input_scale
    for layer_name, module, relu in linear_nodes:
        weight_scale = max(float(module.weight.detach().abs().max()) / 96.0, 1e-9)
        weights = torch.clamp(torch.round(module.weight.detach() / weight_scale), -128, 127).to(torch.int64)
        biases = torch.round(module.bias.detach() / (activation_scale * weight_scale)).to(torch.int64)
        accumulator = torch.matmul(quant, weights.T) + biases
        shift = choose_shift(accumulator)
        quant = torch.clamp(rounded_shift(accumulator, shift), 0 if relu else -128, 127).to(torch.int64)
        layers.append(LayerProgram(layer_name, weights.shape[1], relu, weights.tolist(), biases.tolist(), shift))
        for sample, values in enumerate(quant.tolist()):
            expected[sample].append(values)
        activation_scale = activation_scale * weight_scale * (1 << shift)

    with torch.no_grad():
        float_output = model(float_inputs)
    dequantized = quant.to(torch.float32) * activation_scale
    float_mae = float((float_output - dequantized).abs().mean())
    return GraphProgram(name, seed, input_k, nodes, layers, inputs, expected, float_mae)


def emit_case_function(lines: list[str], name: str, entries: dict[int, int], default: int = 0) -> None:
    lines.extend([f"function automatic integer signed {name}(input integer i);", "  begin", "    case (i)"])
    lines.extend(f"      {index}: {name} = {value};" for index, value in sorted(entries.items()))
    lines.extend([f"      default: {name} = {default};", "    endcase", "  end", "endfunction"])


def emit_sv(programs: list[GraphProgram], path: Path) -> None:
    lines = [f"localparam integer FX_GRAPH_COUNT = {len(programs)};", "localparam integer FX_SAMPLES = 4;"]
    emit_case_function(lines, "fx_layer_count", {g: len(p.layers) for g, p in enumerate(programs)})
    emit_case_function(lines, "fx_input_k", {g: p.input_k for g, p in enumerate(programs)})
    layer_k: dict[int, int] = {}
    layer_relu: dict[int, int] = {}
    layer_shift: dict[int, int] = {}
    weights: dict[int, int] = {}
    biases: dict[int, int] = {}
    inputs: dict[int, int] = {}
    expected: dict[int, int] = {}
    for g, program in enumerate(programs):
        for sample, values in enumerate(program.inputs):
            for k, value in enumerate(values):
                inputs[(g * 4 + sample) * MAX_K + k] = value
        for layer, spec in enumerate(program.layers):
            key = g * MAX_LAYERS + layer
            layer_k[key] = spec.k
            layer_relu[key] = int(spec.relu)
            layer_shift[key] = spec.shift
            for output, row in enumerate(spec.weights):
                biases[(key * OUTPUTS) + output] = spec.biases[output]
                for k, value in enumerate(row):
                    weights[((key * OUTPUTS + output) * MAX_K) + k] = value
            for sample in range(4):
                for output, value in enumerate(program.expected[sample][layer]):
                    expected[(((g * 4 + sample) * MAX_LAYERS + layer) * OUTPUTS) + output] = value
    emit_case_function(lines, "fx_layer_k", layer_k)
    emit_case_function(lines, "fx_layer_relu", layer_relu)
    emit_case_function(lines, "fx_layer_shift", layer_shift)
    emit_case_function(lines, "fx_weight", weights)
    emit_case_function(lines, "fx_bias", biases)
    emit_case_function(lines, "fx_input", inputs)
    emit_case_function(lines, "fx_expected", expected)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graphs", type=int, default=20)
    args = parser.parse_args()
    programs: list[GraphProgram] = []
    for index in range(args.graphs):
        input_k = (4, 8, 16)[index % 3]
        layer_count = 1 + (index % 3)
        relu_mask = (index * 5 + 1) & ((1 << layer_count) - 1)
        seed = 4100 + index
        model = build_model(seed, input_k, layer_count, relu_mask)
        programs.append(compile_model(f"fx_graph_{index:02d}", seed, model, input_k))

    # Negative compilation evidence: functional graph operations are deliberately outside this accelerator contract.
    class Unsupported(nn.Module):
        def forward(self, value: torch.Tensor) -> torch.Tensor:
            return torch.sigmoid(value)

    rejected = False
    try:
        compile_model("unsupported_sigmoid", 1, Unsupported(), 4)
    except ValueError:
        rejected = True
    if not rejected:
        raise RuntimeError("unsupported FX operator was not rejected")

    emit_sv(programs, ROOT / "build" / "generated_fx_graphs.svh")
    manifest = {
        "schema": "int8-fx-compiler-v1",
        "torch_version": torch.__version__,
        "graphs": [
            {
                "name": p.name,
                "seed": p.seed,
                "input_k": p.input_k,
                "nodes": p.nodes,
                "layers": [
                    {"name": layer.name, "k": layer.k, "relu": layer.relu, "shift": layer.shift,
                     "parameter_bank": index & 1}
                    for index, layer in enumerate(p.layers)
                ],
                "samples": len(p.inputs),
                "float_mae": p.float_mae,
            }
            for p in programs
        ],
        "unsupported_sigmoid_rejected": rejected,
    }
    encoded = json.dumps(manifest, indent=2) + "\n"
    manifest["artifact_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    (ROOT / "reports" / "fx_graph_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (ROOT / "reports" / "fx_compile_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["graph", "seed", "layers", "nodes", "input_k", "samples", "float_mae", "status"], lineterminator="\n")
        writer.writeheader()
        for p in programs:
            writer.writerow({"graph": p.name, "seed": p.seed, "layers": len(p.layers), "nodes": len(p.nodes),
                             "input_k": p.input_k, "samples": len(p.inputs), "float_mae": f"{p.float_mae:.8f}", "status": "PASS"})
    coverage = [
        ("graph_depth_1", any(len(p.layers) == 1 for p in programs)),
        ("graph_depth_2", any(len(p.layers) == 2 for p in programs)),
        ("graph_depth_3", any(len(p.layers) == 3 for p in programs)),
        ("input_k_4", any(p.input_k == 4 for p in programs)),
        ("input_k_8", any(p.input_k == 8 for p in programs)),
        ("input_k_16", any(p.input_k == 16 for p in programs)),
        ("relu_fused", any(layer.relu for p in programs for layer in p.layers)),
        ("linear_without_relu", any(not layer.relu for p in programs for layer in p.layers)),
        ("parameter_bank_reuse", any(len(p.layers) >= 3 for p in programs)),
        ("unsupported_operator_rejected", rejected),
    ]
    with (ROOT / "reports" / "fx_coverage.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["coverage_point", "status"])
        writer.writerows((name, "COVERED" if hit else "MISSING") for name, hit in coverage)
    print(f"FX_COMPILE|status=PASS|graphs={len(programs)}|unsupported_rejected=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
