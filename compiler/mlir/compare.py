"""Check MLIR schedule legality and execute generated firmware on the RTL."""
import csv
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from fx_graph_compiler import build_model, compile_model
from torch import nn

sys.path.insert(0, str(ROOT / "integration/protected_offload/scripts"))
import run_mlp_demo as demo

HERE = Path(__file__).resolve().parent


def export_fx(program, folder):
    first, second, *remaining = program.layers
    samples = len(program.inputs)
    if first.k != program.input_k or second.k != 4 or not first.relu or second.relu:
        raise ValueError("Expected Linear/ReLU followed by Linear")
    from_type = f"tensor<{samples}x{program.input_k}xi8>"
    to_type = f"tensor<{samples}x4xi8>"
    source = f"""module {{
  func.func private @linear_relu({from_type}) -> {to_type}
  func.func private @linear({to_type}) -> {to_type}
  func.func @model(%input: {from_type}) -> {to_type}
      attributes {{int8.quantization = "signed-i8-nearest-away-saturate-v1"}} {{
    %hidden = func.call @linear_relu(%input) : ({from_type}) -> {to_type}
    %output = func.call @linear(%hidden) : ({to_type}) -> {to_type}
    return %output : {to_type}
  }}
}}
"""
    if remaining:
        third, = remaining
        if third.k != 4 or third.relu:
            raise ValueError("Expected a four-input Linear third layer")
        source = source.replace(
            f"    return %output : {to_type}",
            f"    %final = func.call @linear(%output) : ({to_type}) -> {to_type}\n"
            f"    return %final : {to_type}",
        )
    (folder / f"{program.name}.mlir").write_text(source)

    def pack(samples):
        return [sum((value & 255) << (8 * lane)
                    for lane, value in enumerate(sample[i:i + 4]))
                for sample in samples for i in range(0, len(sample), 4)]

    expected = [pack([sample[layer] for sample in program.expected])
                for layer in range(len(program.layers))]
    hidden, output = expected[0], expected[-1]
    arrays = (
        ("uint32_t", "inputs", pack(program.inputs)),
        ("int8_t", "w1", [v for row in first.weights for v in row]),
        ("int8_t", "w2", [v for row in second.weights for v in row]),
        ("int32_t", "b1", first.biases), ("int32_t", "b2", second.biases),
        ("uint32_t", "expected_hidden", hidden), ("uint32_t", "expected_output", output),
    )
    if remaining:
        arrays += (
            ("int8_t", "w3", [v for row in third.weights for v in row]),
            ("int32_t", "b3", third.biases),
            ("uint32_t", "expected_middle", expected[1]),
        )
    header = [f"#define MLIR_LAYERS {len(program.layers)}", f"#define SAMPLES {samples}", f"#define INPUT_K {first.k}",
              f"#define SHIFT1 {first.shift}", f"#define SHIFT2 {second.shift}"]
    if remaining:
        header.append(f"#define SHIFT3 {third.shift}")
    for kind, name, values in arrays:
        header.append(f"static const {kind} {name}[] = {{{', '.join(map(str, values))}}};")
    (folder / "mlp_vectors.h").write_text("\n".join(header) + "\n")
    outputs = {demo.HIDDEN: hidden, demo.OUTPUT: output}
    if remaining:
        outputs[0x1000701c] = expected[1]
    return outputs


def check_fx_matrix(tool, filecheck, executable):
    rows = []
    for samples, width in ((4, 8), (8, 32), (16, 64)):
        name = f"fx_b{samples}_k{width}"
        program = compile_model(name, 2601, build_model(2601, width, 2, 1), width, samples=samples)
        expected = export_fx(program, demo.BUILD)
        for schedule, check in (("staged", "STAGED"), ("chained", "CHAIN")):
            staged = schedule == "staged"
            variant = f"{name}_{schedule}"
            header = demo.BUILD / f"{variant}.inc"
            lowered = subprocess.check_output(
                [tool, str(demo.BUILD / f"{name}.mlir"), f"--emit-header={header}",
                 *(["--force-staging"] if staged else [])], text=True)
            subprocess.run([filecheck, str(HERE / "checks.txt"), f"--check-prefix={check}"],
                           input=lowered, text=True, check=True)
            (demo.BUILD / f"{variant}.mlir").write_text(lowered)
            for load, peer in (("idle", None), ("contended", 15)):
                trace, log = demo.run_case(executable, f"{variant}_{load}", contender=peer,
                                           schedule=header)
                row = demo.check_case(variant, trace, log, expected, False, 8, peer,
                                      staged=staged, samples=samples, input_k=width)
                stage = 0x10009000 if staged else demo.HIDDEN
                reads = [event for event in demo.events(trace) if event.get("kind") == "MEM_RSP"
                         and event.get("write") == "0" and event.get("tag") == "98"]
                demo.require([int(event["addr"], 16) for event in reads] ==
                             [stage + 4 * i for i in range(samples)], variant + " DMA input")
                rows.append(dict(batch=samples, input_width=width, schedule=schedule, load=load,
                                 cycles=row["cycles"], dma_bytes=row["dma_bytes"],
                                 maintenance_ops=4 if staged else 2,
                                 overlap_cycles=row["overlap_cycles"],
                                 dma_max_ar_wait=row["dma_max_ar_wait"],
                                 trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest()))
    return rows


def check_three_layers(tool, filecheck, executable):
    (demo.BUILD / "three_layer_comparison.csv").unlink(missing_ok=True)
    name = "fx_three_layer"
    expected = export_fx(compile_model(name, 2601, build_model(2601, 32, 3, 1),
                                      32, samples=16), demo.BUILD)
    rows = []
    for staged, check in ((True, "THREE-STAGED"), (False, "THREE-CHAIN")):
        mode = "three_staged" if staged else "three_chained"
        header = demo.BUILD / f"{mode}.inc"
        lowered = subprocess.check_output(
            [tool, str(demo.BUILD / f"{name}.mlir"), f"--emit-header={header}",
             *(["--force-staging"] if staged else [])], text=True)
        subprocess.run([filecheck, str(HERE / "checks.txt"), f"--check-prefix={check}"],
                       input=lowered, text=True, check=True)
        lowering = demo.BUILD / f"{mode}.mlir"
        lowering.write_text(lowered)
        subprocess.run([tool, "--verify-schedule", str(lowering)], check=True)

        trace, log = demo.run_case(executable, mode, contender=15, schedule=header)
        row = demo.check_case(mode, trace, log, expected, False, 8, 15, staged=staged,
                              input_k=32, layers=3)
        records = list(demo.events(trace))
        for tag, buffer in (("98", demo.HIDDEN), ("99", 0x1000701C)):
            source = 0x10009000 if staged else buffer
            reads = [e for e in records if e.get("kind") == "MEM_RSP" and
                     e["write"] == "0" and e["tag"] == tag]
            demo.require([(int(e["addr"], 16), int(e["rdata"], 16)) for e in reads] ==
                         [(source + 4 * i, word) for i, word in enumerate(expected[buffer])],
                         f"{mode} layer {tag} input bytes and buffer")
        if staged:
            # Deliberately overwrite the live first activation with the still
            # unproduced middle buffer. The verifier must reject this schedule.
            bad_ir = demo.BUILD / "premature_reuse.mlir"
            call = "    call @dma_layer2_staged_to_middle()"
            bad_ir.write_text(lowered.replace(call, "    call @stage_middle() : () -> ()\n" + call))
            rejected = subprocess.run([tool, "--verify-schedule", str(bad_ir)],
                                      text=True, capture_output=True)
            demo.require(rejected.returncode != 0 and "premature reuse" in rejected.stderr,
                         "schedule verifier must reject live staging reuse")
            # Exercise the rejected schedule through a test-only firmware include.
            bad_header = demo.BUILD / "premature_reuse.inc"
            consumer = "if (ok) ok = dma_layer2_staged_to_middle();"
            bad_header.write_text(header.read_text().replace(consumer,
                "if (ok) ok = stage_middle();\nif (ok) ok = clean_staged();\n" + consumer))
            bad_trace, _ = demo.run_case(executable, "premature_reuse", contender=15,
                                         schedule=bad_header, mutation=True)
            bad_reads = [e for e in demo.events(bad_trace) if e.get("kind") == "MEM_RSP"
                         and e.get("write") == "0" and e["tag"] == "98"]
            demo.require(bad_reads and bad_reads[0]["addr"] == "10009000"
                         and int(bad_reads[0]["rdata"], 16) != expected[demo.HIDDEN][0],
                         "premature reuse must corrupt the first staged DMA read")
            (demo.BUILD / "premature_reuse.txt").write_text(
                rejected.stderr + "\nFirst incorrect RTL read: " + str(bad_reads[0]) + "\n")
        rows.append(dict(schedule=mode, cycles=row["cycles"], dma_bytes=row["dma_bytes"],
                         maintenance_ops=sum(e.get("kind") == "MAINT_DONE" for e in records),
                         overlap_cycles=row["overlap_cycles"],
                         trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest()))
    report = demo.BUILD / "three_layer_comparison.csv"
    with report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(report.read_text(), end="")


def main():
    tool, filecheck = (str(Path(arg).resolve()) for arg in sys.argv[1:])
    demo.BUILD = ROOT / "build/int8-mlir/rtl"
    demo.BUILD.mkdir(parents=True, exist_ok=True)
    report = demo.BUILD / "comparison.csv"
    report.unlink(missing_ok=True)
    source = (HERE / "model.mlir").read_text()
    observed = demo.BUILD / "cpu-consumer.mlir"
    observed.write_text(source.replace("  func.func @model", (
        "  func.func private @observe_hidden(tensor<16x4xi8>)\n  func.func @model"
    )).replace("    %output =", (
        "    func.call @observe_hidden(%hidden) : (tensor<16x4xi8>) -> ()\n    %output ="
    )))
    for name, invalid_source in (
        ("rounding", source.replace("nearest-away", "truncate")),
        ("shape", source.replace("16x16xi8", "16x12xi8")),
    ):
        bad = demo.BUILD / f"bad-{name}.mlir"
        bad.write_text(invalid_source)
        rejected = subprocess.run([tool, str(bad)], capture_output=True, text=True)
        demo.require(rejected.returncode != 0 and ("unsupported model shape" if name == "shape" else "quantization contract") in rejected.stderr,
                     f"reject unsupported {name}")
    class Disconnected(nn.Module):
        def __init__(self):
            super().__init__()
            self.first = nn.Linear(4, 4)
            self.second = nn.Linear(4, 4)

        def forward(self, value):
            self.first(value)
            return self.second(value)

    try:
        compile_model("disconnected", 2601, Disconnected(), 4)
    except ValueError as error:
        demo.require("single sequential tensor path" in str(error), "wrong FX rejection")
    else:
        raise RuntimeError("FX importer accepted a disconnected graph")
    expected = demo.export_vectors()
    executable = demo.compile_rtl()
    results = []
    for name, model, options, check, input_base in (
        ("staged", HERE / "model.mlir", ["--force-staging"], "STAGED", 0x10009000),
        ("chained", HERE / "model.mlir", [], "CHAIN", 0x1000401C),
        ("cpu_consumer", observed, [], "OBSERVE", 0x10009000),
    ):
        header = demo.BUILD / f"{name}.inc"
        lowered = subprocess.check_output(
            [tool, str(model), *options, f"--emit-header={header}"], text=True)
        (demo.BUILD / f"{name}.mlir").write_text(lowered)
        subprocess.run([filecheck, str(HERE / "checks.txt"), f"--check-prefix={check}"],
                       input=lowered, text=True, check=True)
        trace, log = demo.run_case(executable, name, schedule=header)
        row = demo.check_case(name, trace, log, expected, False, 8, None,
                              staged=name != "chained")
        records = list(demo.events(trace))
        reads = [e for e in records if e.get("kind") == "MEM_RSP" and
                 e["write"] == "0" and e["tag"] == "98"]
        demo.require([int(e["addr"], 16) for e in reads] ==
                     [input_base + 4 * i for i in range(demo.SAMPLES)], name + " layer-2 input addresses")
        completion = next(e for e in records if e.get("kind") == "COMPLETE" and e["tag"] == "97")
        submit = next(e for e in records if e.get("kind") == "SUBMIT" and e["tag"] == "98")
        handoff = [e for e in records if int(completion["cycle"]) <= int(e["cycle"]) < int(submit["cycle"])]
        stage_writes = [e for e in handoff if e.get("kind") == "AXI_WRITE" and e["master"] == "0"
                        and 0x10009000 <= int(e["addr"], 16) < 0x10009040]
        stage_bytes = sum(int(e["strb"], 16).bit_count() for e in stage_writes)
        demo.require(stage_bytes == (0 if name == "chained" else 64),
                     name + " cache writeback before layer-2 submit")
        results.append(dict(schedule=name, cycles=row["cycles"], dma_payload_bytes=row["dma_bytes"],
                            staging_writeback_bytes=stage_bytes,
                            descriptors=sum(e.get("kind") == "SUBMIT" for e in records),
                            maintenance_ops=sum(e.get("kind") == "MAINT_DONE" for e in records),
                            trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest()))
    with report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=results[0])
        writer.writeheader()
        writer.writerows(results)
    print(report.read_text(), end="")
    matrix = demo.BUILD / "fx_comparison.csv"
    matrix.unlink(missing_ok=True)
    rows = check_fx_matrix(tool, filecheck, executable)
    with matrix.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(matrix.read_text(), end="")
    check_three_layers(tool, filecheck, executable)


if __name__ == "__main__":
    main()
