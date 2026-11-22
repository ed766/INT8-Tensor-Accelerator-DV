"""Check MLIR schedule legality and execute generated firmware on the RTL."""
import csv
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "integration/protected_offload/scripts"))
import run_mlp_demo as demo

HERE = Path(__file__).resolve().parent


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
        ("shape", source.replace("16x16xi8", "8x16xi8")),
    ):
        bad = demo.BUILD / f"bad-{name}.mlir"
        bad.write_text(invalid_source)
        rejected = subprocess.run([tool, str(bad)], capture_output=True, text=True)
        demo.require(rejected.returncode != 0 and "quantization contract" in rejected.stderr,
                     f"reject unsupported {name}")
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


if __name__ == "__main__":
    main()
