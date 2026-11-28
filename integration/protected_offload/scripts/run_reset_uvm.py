#!/usr/bin/env python3
"""Run protected-offload reset recovery with UVM and RV32 firmware."""

import csv
import hashlib
import os
from pathlib import Path
import re
import subprocess

import run_mlp_demo as demo
from shared_rtl_sources import ROOT, sources


BUILD = ROOT / "build/protected_offload/reset_uvm"
SIM = ROOT / "integration/protected_offload/sim"
TOP = "tb_protected_reset_uvm"
WINDOWS = ("first_read_response", "partial_output_write", "pending_completion_irq", "pending_write_response")
COVER_BINS = ("c_read_recovered", "c_write_recovered", "c_irq_recovered", "c_write_response_recovered",
              "c_local_read", "c_local_b", "c_local_queued")
LOCAL_WINDOWS = ("local_read_response", "local_write_response", "local_queued_descriptors")


def compile_simulator(folder, *, retain_completion=False):
    folder.mkdir(parents=True, exist_ok=True)
    uvm = Path(os.environ.get("UVM_HOME", Path.home() / "uvm-verilator/src")).resolve()
    if not (uvm / "uvm_pkg.sv").is_file():
        raise SystemExit("Set UVM_HOME to the src directory of chipsalliance/uvm-verilator")
    rtl = sources[:-1]  # Compile the integration DUT with the dedicated UVM top.
    if retain_completion:
        dma = next(source for source in rtl if source.name == "protected_offload_dma.sv")
        original = "      completion_count <= '0;"
        text = dma.read_text()
        if text.count(original) != 1:
            raise SystemExit("Expected exactly one DMA completion-count reset assignment")
        mutant = folder / dma.name
        modified = text.replace(original, "      // Mutation: retain completion count on reset.")
        if not mutant.exists() or mutant.read_text() != modified:
            mutant.write_text(modified)
        rtl = [mutant if source == dma else source for source in rtl]
    with (folder / "compile.log").open("w") as log:
        subprocess.run(
            [os.environ.get("VERILATOR_UVM", "verilator"), "--binary", "-j", "4",
             "--timing", "--assert", "--coverage-user", "-Wno-fatal",
             "+define+UVM_NO_DPI", f"+incdir+{uvm}", "--top-module", TOP,
             "--Mdir", str(folder), str(uvm / "uvm_pkg.sv"),
             *map(str, rtl), str(SIM / "protected_reset_uvm.sv"), str(SIM / f"{TOP}.sv")],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
        )
    return folder / f"V{TOP}"


def require_native_cross(coverage, stage):
    observed = {}
    for line in coverage.read_text().splitlines():
        for label in COVER_BINS:
            if f"\x01o\x02{label}\x01" in line or f"\x01o\x02{label}'" in line:
                observed[label] = int(line.rsplit(" ", 1)[1])
    expected = {label: int(index == stage) for index, label in enumerate(COVER_BINS)}
    if observed != expected:
        raise SystemExit(f"Unexpected native cross hits in {coverage}: {observed}")
    return COVER_BINS[stage]


def run_case(executable, stage, seed=None, *, mutation=False):
    scenario = WINDOWS[stage]
    name = "retained_completion_mutation" if mutation else (
        f"{scenario}_directed" if seed is None else f"{scenario}_{seed}")
    folder = BUILD / name
    folder.mkdir(exist_ok=True)
    trace = folder / "crossover.trace"
    trace.unlink(missing_ok=True)
    coverage = folder / "coverage.dat"
    coverage.unlink(missing_ok=True)
    build_id = hashlib.sha256(executable.read_bytes() + (BUILD / "firmware.elf").read_bytes()).hexdigest()
    command = [
        str(executable), f"+RESET_STAGE={stage}", f"+RUN_ID={name}", f"+CROSS_TRACE={trace}",
        f"+SOURCE_BUILD_ID={build_id}",
        "+CROSS_TRACE_FLUSH", f"+FIRMWARE_HEX={BUILD / 'firmware.hex'}",
        f"+DATA_HEX={BUILD / 'data.hex'}", f"+GOLDEN_HEX={BUILD / 'golden.hex'}",
    ]
    if seed is not None:
        command += ["+RANDOM_TIMING", f"+verilator+seed+{seed}"]
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    (folder / "simulation.log").write_text(output)
    witness = re.search(
        rf"^RESET_WINDOW\|stage={stage}\|outstanding={stage}\|committed=(\d+)"
        r"\|old_publications=(\d+)\|dma_b_responses=(\d+)$",
        output, re.M,
    )
    timing = re.search(r"^RESET_TIMING\|stage=\d+\|hold=(\d+)\|reset=(\d+)\|stall=(\d+)$",
                       output, re.M)
    passed = f"RESET_CROSS_PASS|stage={stage}|outstanding={stage}|outcome=same_tag_recovered"
    if mutation:
        accepted = (result.returncode != 0 and passed not in output and
                    "a_quiet_before_resubmit: stale completion, IRQ, or DMA response" in output)
    else:
        accepted = (result.returncode == 0 and passed in output and
                    re.search(r"UVM_ERROR\s*:\s*0\b", output) and
                    re.search(r"UVM_FATAL\s*:\s*0\b", output))
    if not (witness and timing and accepted):
        raise SystemExit(f"Reset recovery case failed: {folder / 'simulation.log'}")
    if not trace.is_file() or trace.read_bytes().count(b"|kind=RESET_ASSERT|") != 1:
        raise SystemExit(f"Missing unique reset assertion in {trace}")
    pending_write_event = ""
    if scenario == "pending_write_response":
        events = demo.events(trace)
        reset_index = next(i for i, event in enumerate(events) if event["kind"] == "RESET_ASSERT")
        requests = [event for event in events[:reset_index]
                    if event["kind"] == "MEM_REQ" and event.get("write") == "1"]
        responses = [event for event in events[:reset_index]
                     if event["kind"] == "MEM_RSP" and event.get("write") == "1"]
        if (events[reset_index].get("mem_pending") != "1" or len(requests) != 1 or responses
                or witness.groups() != ("1", "0", "0")):
            raise SystemExit(f"Missing committed-write / pending-response witness in {trace}")
        pending_write_event = requests[0]["eid"]
    native_bin = ""
    if not mutation:
        native_bin = require_native_cross(coverage, stage)
    return dict(stage=scenario,
                outstanding=("read_response", "write_data", "unacked_irq", "write_response")[stage],
                mode="mutation" if mutation else ("directed" if seed is None else "randomized"),
                seed=seed, hold_cycles=timing[1], reset_cycles=timing[2], stall_cycles=timing[3],
                prefix_words=witness[1], old_publications=witness[2], old_dma_b_responses=witness[3],
                outcome="stale_completion_detected" if mutation else "same_tag_recovered",
                native_bin=native_bin, pending_write_event=pending_write_event,
                trace=str(trace.relative_to(BUILD)),
                trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())


def run_local_case(executable, stage, firmware, seed):
    name = f"{LOCAL_WINDOWS[stage - 4]}_{seed if seed is not None else 'directed'}"
    folder = BUILD / name
    folder.mkdir(exist_ok=True)
    trace, coverage = folder / "crossover.trace", folder / "coverage.dat"
    trace.unlink(missing_ok=True)
    coverage.unlink(missing_ok=True)
    build_id = hashlib.sha256(executable.read_bytes() + (firmware / "firmware.elf").read_bytes()).hexdigest()
    command = [str(executable), f"+RESET_STAGE={stage}", f"+RUN_ID={name}", f"+CROSS_TRACE={trace}",
               f"+SOURCE_BUILD_ID={build_id}", f"+FIRMWARE_HEX={firmware / 'firmware.hex'}",
               f"+DATA_HEX={firmware / 'data.hex'}", f"+GOLDEN_HEX={BUILD / 'golden.hex'}"]
    if seed is not None:
        command += ["+RANDOM_TIMING", f"+verilator+seed+{seed}"]
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    log = folder / "simulation.log"
    log.write_text(output)
    window = re.search(rf"^LOCAL_RESET_WINDOW\|stage={stage}\|old_submits=(\d+)\|queued=(\d+)"
                       r"\|completed=(\d+)\|first_prefix=(\d+)$", output, re.M)
    done = re.search(rf"^LOCAL_RESET_PASS\|stage={stage}\|drained_r=(\d+)\|drained_b=(\d+)"
                     r"\|live_retires=(\d+)\|replacements=(\d+)$", output, re.M)
    timing = re.search(rf"^RESET_TIMING\|stage={stage}\|hold=(\d+)\|reset=\d+\|stall=(\d+)$",
                       output, re.M)
    if (result.returncode or not window or not done or not timing
            or not re.search(r"UVM_ERROR\s*:\s*0\b", output)
            or not re.search(r"UVM_FATAL\s*:\s*0\b", output)):
        raise SystemExit(f"Local reset recovery failed: {log}")
    events = demo.events(trace)
    resets = [event for event in events if event["kind"] == "OFFLOAD_RESET_ASSERT"]
    releases = [event for event in events if event["kind"] == "OFFLOAD_RESET_RELEASE"]
    if (len(resets) != 1 or len(releases) != 1 or resets[0].get("mem_pending") != "1"
            or any(event["kind"] == "RESET_ASSERT" for event in events)):
        raise SystemExit(f"Missing isolated reset with an outstanding DMA access: {trace}")
    return dict(stage=LOCAL_WINDOWS[stage - 4], seed=seed, hold_cycles=timing[1], stall_cycles=timing[2],
                old_submits=window[1], queued=window[2], completed=window[3], first_prefix=window[4],
                drained_r=done[1], drained_b=done[2], live_retires=done[3], replacements=done[4],
                native_bin=require_native_cross(coverage, stage), reset_event=resets[0]["eid"],
                release_event=releases[0]["eid"], trace=str(trace.relative_to(BUILD)),
                trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest())


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    report = BUILD / "reset_cross.csv"
    local_report = BUILD / "local_reset_cross.csv"
    report.unlink(missing_ok=True)
    local_report.unlink(missing_ok=True)
    demo.BUILD = BUILD
    golden = demo.export_vectors()[demo.HIDDEN]
    if golden == golden[::-1]:
        raise SystemExit("Original and recovery fixtures must produce distinct byte sequences")
    (BUILD / "golden.hex").write_text("".join(f"{word:08x}\n" for word in golden))
    demo.compile_firmware(BUILD, False, 8, False, reset_recovery=True)
    nominal = compile_simulator(BUILD / "obj")
    rows = [run_case(nominal, stage, seed)
            for stage in range(len(WINDOWS)) for seed in (None, 11, 29, 97)]
    for stage in WINDOWS:
        holds = {row["hold_cycles"] for row in rows if row["stage"] == stage and row["seed"]}
        if len(holds) < 2:
            raise SystemExit(f"Randomized seeds did not vary the reset offset for {stage}")
    local_rows = []
    for jobs, stages in ((1, (4, 5)), (3, (6,))):
        firmware = BUILD / f"local_firmware_{jobs}"
        firmware.mkdir(exist_ok=True)
        demo.compile_firmware(firmware, False, 8, False, local_reset_jobs=jobs)
        for stage in stages:
            local_rows.extend(run_local_case(nominal, stage, firmware, seed) for seed in (None, 11, 29, 97))
    mutant = compile_simulator(BUILD / "mutant", retain_completion=True)
    rows.append(run_case(mutant, 2, mutation=True))
    with report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Reset recovery: {len(rows) - 1} nominal runs, {len(WINDOWS)} legal crosses, "
          f"stale completion detected. {report}")
    with local_report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=local_rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(local_rows)
    print(f"Local reset recovery: {len(local_rows)} nominal runs, {len(LOCAL_WINDOWS)} legal crosses. {local_report}")


if __name__ == "__main__":
    main()
