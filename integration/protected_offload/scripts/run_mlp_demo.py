#!/usr/bin/env python3
"""Run the cache/DMA/fabric MLP demo and require trace-backed cross coverage."""
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys

import torch

from check_crossover_trace import events
from shared_rtl_sources import ROOT, sources

sys.path.insert(0, str(ROOT / "scripts"))
from pytorch_mlp_demo import rounded_shift

BUILD = ROOT / "build/protected_offload/mlp_demo"
FIRMWARE = ROOT / "integration/protected_offload/firmware"
BOOT = ROOT / "integration/rv32_offload/firmware"
SAMPLES = 16
HIDDEN, OUTPUT = 0x1000401C, 0x1000601C


def export_vectors():
    generator = torch.Generator().manual_seed(2601)
    inputs = torch.randint(-31, 32, (SAMPLES, 16), generator=generator)
    weights1 = torch.randint(-12, 13, (4, 16), generator=generator)
    weights2 = torch.randint(-12, 13, (4, 4), generator=generator)
    biases1 = torch.tensor([89, -63, 28, 143])
    biases2 = torch.tensor([30, 97, -51, 118])
    hidden = rounded_shift(inputs @ weights1.T + biases1, 5).clamp(0, 127)
    output = rounded_shift(hidden @ weights2.T + biases2, 4).clamp(-128, 127)

    def pack(tensor):
        return [sum((int(v) & 255) << (8 * i) for i, v in enumerate(row))
                for row in tensor.reshape(-1, 4)]

    arrays = [
        ("uint32_t", "inputs", pack(inputs)),
        ("int8_t", "w1", weights1.flatten().tolist()),
        ("int8_t", "w2", weights2.flatten().tolist()),
        ("int32_t", "b1", biases1.tolist()),
        ("int32_t", "b2", biases2.tolist()),
        ("uint32_t", "expected_hidden", pack(hidden)),
        ("uint32_t", "expected_output", pack(output)),
    ]
    header = [f"#define SAMPLES {SAMPLES}", "#define SHIFT1 5", "#define SHIFT2 4"]
    for kind, name, values in arrays:
        header.append(f"static const {kind} {name}[] = {{{', '.join(map(str, values))}}};")
    (BUILD / "mlp_vectors.h").write_text("\n".join(header) + "\n")
    return dict(zip((HIDDEN, OUTPUT), (pack(hidden), pack(output))))


def riscv_tool(name):
    executable = "riscv64-unknown-elf-" + name
    pinned = ROOT.parent / "ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin" / executable
    if path := shutil.which(executable):
        return path
    if pinned.is_file():
        return str(pinned)
    raise SystemExit(f"Install {executable} or the Chiplet SoC RV32 toolchain")


def compile_firmware(folder, scalar, qos, retry):
    elf = folder / "firmware.elf"
    subprocess.run(
        [riscv_tool("gcc"), "-march=rv32im_zicsr", "-mabi=ilp32", "-O2",
         "-ffreestanding", "-nostdlib", "-fno-pic", "-msmall-data-limit=0", "-mno-relax",
         f"-DSCALAR={int(scalar)}", f"-DDMA_QOS={qos}", f"-DRETRY={int(retry)}", "-I", str(BUILD),
         str(BOOT / "crt0.S"), str(FIRMWARE / "mlp_demo.c"), f"-T{BOOT / 'link.ld'}",
         "-Wl,--build-id=none", "-o", str(elf)], check=True,
    )
    for stem, sections, base in (("firmware", [".text"], ""), ("data", [".rodata", ".data"], "@00000800\n")):
        binary = folder / f"{stem}.bin"
        subprocess.run([riscv_tool("objcopy"), "-O", "binary",
                        *[f"--only-section={section}" for section in sections],
                        str(elf), str(binary)], check=True)
        data = binary.read_bytes()
        data += bytes(-len(data) % 4)
        (folder / f"{stem}.hex").write_text(base + "".join(
            f"{int.from_bytes(data[i:i + 4], 'little'):08x}\n" for i in range(0, len(data), 4)
        ))


def run_case(executable, name, scalar=False, qos=8, contender=None, mutation=False, retry=False):
    folder = BUILD / name
    folder.mkdir(exist_ok=True)
    compile_firmware(folder, scalar, qos, retry)
    trace = folder / "crossover.trace"
    trace.unlink(missing_ok=True)
    digest = hashlib.sha256((folder / "firmware.elf").read_bytes())
    for source in sources:
        digest.update(source.read_bytes())
    digest.update(executable.parent.name.encode())
    command = [str(executable), f"+RUN_ID={name}", f"+SOURCE_BUILD_ID={digest.hexdigest()}",
               f"+FIRMWARE_HEX={folder / 'firmware.hex'}", f"+DATA_HEX={folder / 'data.hex'}",
               f"+CROSS_TRACE={trace}", "+MLP_DEMO"]
    if contender is not None:
        command += ["+MLP_CONTEND", f"+MLP_QOS={contender}"]
    if retry:
        command += ["+AXI_FAIL_WRITE_ADDR=10006024", "+AXI_FAIL_WRITE_COUNT=1"]
    run = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=120)
    (folder / "simulation.log").write_text(run.stdout + run.stderr)
    if mutation:
        require(run.returncode != 0 and "firmware result dead5000" in run.stdout, name)
    else:
        require(run.returncode == 0 and "PROTECTED_SHARED|status=PASS" in run.stdout, name)
    return trace, run.stdout


def require(condition, message):
    if not condition:
        raise SystemExit(f"MLP demo check failed: {message}; see {BUILD}")


def compile_rtl(define=""):
    folder = BUILD / (define or "obj")
    folder.mkdir(exist_ok=True)
    with (folder / "compile.log").open("w") as log:
        subprocess.run(
            ["verilator", "--binary", "--timing", "--assert", "-j", "4", "-Wno-fatal",
             "--top-module", "tb_rv32_protected_shared", "-GUSE_CACHE=1'b1",
             "-GCPU_ENABLE_M=1'b1", "-DTEST_MLP_DEMO",
             *([f"-D{define}"] if define else []),
             "--Mdir", str(folder), *map(str, sources)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
        )
    return folder / "Vtb_rv32_protected_shared"


def check_case(name, trace, log, expected, scalar, dma_qos, contender_qos):
    records = list(events(trace))
    published = [event for event in records if event["kind"] == "COMPLETE_PUBLISH"]
    reads = [event for event in records if event["kind"] == "MEM_RSP" and event["write"] == "0"]
    writes = [event for event in records if event["kind"] == "MEM_RSP" and event["committed"] == "1"]
    cycles = int(re.search(r"benchmark_cycles=(\d+)", log)[1])
    by_address = {int(event["addr"], 16): int(event["wdata"], 16) for event in writes}
    if scalar:
        require(not published and not reads and not writes, name + " scalar DMA isolation")
        return dict(mode=name, cycles=cycles, dma_bytes=0, contenders=0, overlap_cycles=0,
                    dma_max_ar_wait=0, contender_max_ar_wait=0, cross_bins=0, descriptor_min=0, descriptor_max=0, clean_final_line_event="", peer_burst_event="")
    require([(e["tag"], e["status"], e["vectors_done"]) for e in published] ==
            [("97", "0", str(SAMPLES)), ("98", "0", str(SAMPLES))], name + " completions")
    require(len(reads) == 5 * SAMPLES and len(writes) == 2 * SAMPLES, name + " DMA accounting")
    require(all(event["error"] == "0" for event in reads), name + " read status")
    for base, words in expected.items():
        require([by_address.get(base + 4 * i) for i in range(SAMPLES)] == words,
                name + " PyTorch output compare")
    maintenance = [e for e in records if e["kind"] == "MAINT_DONE"]
    require([(e["cmd"], e["error"]) for e in maintenance] == [("0", "0"), ("1", "0")],
            name + " clean/invalidate")
    require(int(maintenance[0]["cycle"]) < int(reads[0]["cycle"]) <
            int(published[0]["cycle"]) < int(published[1]["cycle"]) <
            int(maintenance[1]["cycle"]), name + " ownership timeline")
    clean_start = next(e for e in records if e["kind"] == "MAINT_START")
    clean_lines = {int(e["addr"], 16): e["eid"] for e in records
                   if e["kind"] == "AXI_AW" and e["master"] == "0" and e["len"] == "3"
                   and int(clean_start["cycle"]) <= int(e["cycle"]) <= int(maintenance[0]["cycle"])}
    require(0x10001080 in clean_lines, name + " final input cache line written back")
    peer_bursts = [e for e in records if e["kind"] == "AXI_AR" and e["master"] == "3"
                   and e["addr"] == "1000f000" and e["len"] == "3"]
    matches = re.findall(r"MLP_AXI\|contenders=(\d+)\|overlap=(\d+)\|dma_wait=(\d+)\|contender_wait=(\d+)\|qos=(\d+)\|peer_qos=(\d+)", log)
    require(len(matches) == 1, name + " fabric instrumentation")
    contenders, overlap, dma_wait, contender_wait, seen_qos, seen_peer = map(int, matches[0])
    require(seen_qos == dma_qos, name + " DMA QoS witness")
    require(contenders == len(peer_bursts), name + " peer burst accounting")
    if contender_qos is None:
        require(not contenders and not overlap, name + " idle fabric control")
    else:
        require(contenders and overlap and seen_peer == contender_qos, name + " competing AR and QoS witness")
    starts = {e["tag"]: int(e["cycle"]) for e in records if e["kind"] == "SUBMIT"}
    durations = sorted(int(e["cycle"]) - starts[e["tag"]] for e in published)
    return dict(mode=name, cycles=cycles, dma_bytes=4 * (len(reads) + len(writes)),
                contenders=contenders, overlap_cycles=overlap, dma_max_ar_wait=dma_wait,
                contender_max_ar_wait=contender_wait, cross_bins=1, descriptor_min=min(durations), descriptor_max=max(durations),
                clean_final_line_event=clean_lines[0x10001080],
                peer_burst_event=peer_bursts[0]["eid"] if peer_bursts else "")


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    for output in ("evidence.json", "summary.csv"):
        (BUILD / output).unlink(missing_ok=True)
    expected = export_vectors()
    rtl = compile_rtl()
    rows = []
    evidence = []
    for name, scalar, qos, peer in (
        ("scalar", True, 8, None), ("idle", False, 8, None),
        ("equal_qos", False, 8, 8), ("peer_high_qos", False, 8, 15),
        ("dma_high_qos", False, 15, 8),
    ):
        trace, log = run_case(rtl, name, scalar, qos, peer)
        rows.append(check_case(name, trace, log, expected, scalar, qos, peer))
        evidence.append(dict(mode=name, dma_qos=qos, peer_qos=peer,
                             trace=str(trace.relative_to(ROOT)),
                             trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest()))
    trace, _ = run_case(rtl, "fault_retry", contender=8, retry=True)
    records = list(events(trace))
    publications = [e for e in records if e["kind"] == "COMPLETE_PUBLISH" and e["tag"] == "98"]
    require([(e["status"], e["fault_stage"], e["vectors_done"]) for e in publications] ==
            [("5", "4", "2"), ("0", "0", str(SAMPLES))], "fault and retry completions")
    first, last = (int(e["cycle"]) for e in publications)
    writes = [e for e in records if e["kind"] == "MEM_RSP" and e["write"] == "1" and e["tag"] == "98"]
    require([(int(e["addr"], 16), e["committed"], e["error"])
             for e in writes if int(e["cycle"]) < first] ==
            [(OUTPUT, "1", "0"), (OUTPUT + 4, "1", "0"), (OUTPUT + 8, "0", "1")], "committed prefix and injected error")
    require([(int(e["addr"], 16), int(e["wdata"], 16), e["committed"])
             for e in writes if first < int(e["cycle"]) < last] ==
            [(OUTPUT + 4 * i, word, "1") for i, word in enumerate(expected[OUTPUT])], "retry output")
    evidence.append(dict(mode="fault_retry", trace=str(trace.relative_to(ROOT)),
                         trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
                         fault_event=publications[0]["eid"], retry_event=publications[1]["eid"]))
    trace, _ = run_case(compile_rtl("PROTECTED_MUT_FALSE_MAINTENANCE"), "skip_maintenance", mutation=True)
    mutated = list(events(trace))
    require(not any(e.get("kind") == "MAINT_START" for e in mutated) and
            any(e.get("kind") == "MEM_RSP" and e["write"] == "0" and
                int(e["addr"], 16) >= 0x10001080 and int(e["addr"], 16) < 0x100010a0
                for e in mutated), "bypassed maintenance and final-line DMA read")
    evidence.append(dict(mode="skip_maintenance", trace=str(trace.relative_to(ROOT)),
                         trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest()))
    (BUILD / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    with (BUILD / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print((BUILD / "summary.csv").read_text(), end="")
    print("MLP demo: 5/5 modes, 4/4 maintenance/QoS crosses, 1/1 committed-prefix retry cross, 1/1 maintenance mutation")


if __name__ == "__main__":
    main()
