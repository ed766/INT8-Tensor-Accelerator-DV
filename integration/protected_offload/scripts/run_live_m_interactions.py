#!/usr/bin/env python3
"""Supplemental live M/service witnesses; never inflate canonical closure."""
import csv
import json
import hashlib
import argparse
import os
import subprocess
import sys
from pathlib import Path

from check_crossover_trace import events, check
from check_compute_host_evidence import check_host_trace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_name("run_shared_firmware.py")
MANIFEST = json.loads((ROOT / "integration/protected_offload/spec/live_m_coverage.json").read_text())
if MANIFEST["schema"] != 1 or len(MANIFEST["opcodes"]) != 8 or len(MANIFEST["contexts"]) * 8 != MANIFEST["required_bins"]:
    raise ValueError("invalid live-M coverage manifest")


def qualify(trace, mode):
    parsed = events(trace)
    busy = chip = sleep = False
    pressure = False
    witnesses = []
    opcodes = set()
    for event in parsed:
        kind = event.get("kind")
        if kind == "RESET_ASSERT":
            busy = chip = sleep = False
        elif kind == "DMA_ACTIVE_START":
            busy = True
        elif kind == "DMA_ACTIVE_END":
            busy = False
        elif kind == "CHIPLET_EVT":
            chip = event.get("busy") == "1"
        elif kind == "CHIPLET_POWER":
            sleep = event.get("state") == "2"
        elif kind == "MDIV_BUSY" and event.get("busy") == "1":
            pressure = event.get("comp_occ") == "4" and event.get("dma_busy") == "1"
        elif kind == "RETIRE":
            instruction = int(event.get("insn", "0"), 16)
            if instruction & 0xfe00007f == 0x02000033 and event.get("trap") == "0":
                if busy:
                    opcodes.add((instruction >> 12) & 7)
                active = busy and (chip if mode.startswith("dual") else sleep if mode == "sleep" else True)
                if mode == "pressure":active = active and pressure
                if mode.startswith("dual_"):
                    active = active and (instruction >> 12) & 7 == int(mode[-1])
                if active:
                    witnesses.append(event["eid"])
    errors = []
    if not witnesses:
        errors.append("required live M/service overlap not reached")
    if mode == "dma" and opcodes != set(range(8)):
        errors.append("all eight M opcodes must retire while DMA active")
    if mode == "irq":
        pending = next((e for e in parsed if e.get("kind") == "IRQ_SET" and
                        e.get("muldiv_busy") == "1" and e.get("ext") == "1"), None)
        following = [e for e in parsed if pending and e.get("kind") == "RETIRE" and
                     int(e["cycle"]) > int(pending["cycle"])]
        arithmetic = following[0] if following else None
        handler = next((e for e in following if e.get("intr") == "1"), None)
        if not pending or not arithmetic or not handler or int(arithmetic.get("insn", "0"), 16) & 0xfe00007f != 0x02000033 or handler.get("mepc") != arithmetic.get("next_pc"):
            errors.append("pending IRQ must follow M retirement with exact next-PC mepc")
        else:
            witnesses.extend(e["eid"] for e in (pending, arithmetic, handler))
    if mode == "sleep":
        slept = next((e for e in parsed if e.get("kind") == "CHIPLET_POWER" and e.get("state") == "2"), None)
        resumed = next((e for e in parsed if slept and e.get("kind") == "CHIPLET_POWER" and e.get("state") == "0" and int(e["cycle"]) > int(slept["cycle"])), None)
        if not resumed:
            errors.append("actual SLEEP-to-RUN transition missing")
        else:
            # Die B crypto may finish accepted work during SLEEP; Die A DMA
            # acceptance/return must remain gated until wake.
            asleep_traffic = [e for e in parsed if e.get("kind") in {"CHIPLET_IN", "CHIPLET_OUT"} and
                              int(slept["cycle"]) < int(e["cycle"]) < int(resumed["cycle"])]
            completed = next((e for e in parsed if e.get("kind") == "CHIPLET_EVT" and e.get("done") == "1" and
                              int(e["cycle"]) > int(resumed["cycle"])), None)
            if asleep_traffic or not completed:
                errors.append("chiplet must quiesce accepted traffic in SLEEP and complete only after resume")
            else:
                witnesses.extend(e["eid"] for e in (slept, resumed, completed))
    if mode.startswith("dual") or mode == "sleep":
        host = check_host_trace(trace)
        if host["status"] != "PASS":
            errors.append("independent AES/overlap check: " + str(host))
    return witnesses, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-only", action="store_true", help="recheck existing RTL traces without rerunning stimulus")
    args = parser.parse_args()
    rows = []
    coverage = []
    for mode in ("dma", *(f"dual_{i}" for i in range(8)), "sleep", "irq", "pressure"):
        env = dict(os.environ, PROTECTED_LIVE_M=mode)
        command = [sys.executable, str(SCRIPT), "--model"]
        if mode == "irq":
            command += ["--axi-b-delay", "9"]
        trace = ROOT / f"build/protected_offload/shared_firmware/live_m_{mode}/crossover.trace"
        if args.replay_only:
            replay = check(trace, strict_schema=True) if trace.exists() else {"status": "FAIL"}
            returncode = int(replay["status"] != "PASS")
            origin = ROOT / f"reports/compute_live_m_{mode}.csv"
            source_rows = list(csv.DictReader(origin.open())) if origin.exists() else []
            if not trace.exists() or len(source_rows) != 1 or source_rows[0].get("status") != "PASS" or source_rows[0].get("trace_sha256") != hashlib.sha256(trace.read_bytes()).hexdigest():
                returncode = 1
        else:
            returncode = subprocess.run(command, cwd=ROOT, env=env).returncode
        witnesses, errors = qualify(trace, mode) if trace.exists() else ([], ["trace missing"])
        if returncode:
            errors.append("simulation or independent trace replay failed")
        rows.append(dict(scenario=mode, status="FAIL" if errors else "PASS",
                         witness_event_ids=";".join(witnesses),
                         trace=str(trace.relative_to(ROOT)),
                         trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest() if trace.exists() else "MISSING",
                         errors=";".join(errors)))
        if mode in {"dma", "sleep", "pressure"} or mode.startswith("dual_"):
            parsed = events(trace)
            for opcode in ([int(mode[-1])] if mode.startswith("dual_") else range(8)):
                hits = [event for event in parsed if event.get("kind") == "RETIRE" and event.get("eid") in witnesses and
                        int(event.get("insn", "0"), 16) & 0xfe00007f == 0x02000033 and
                        (int(event.get("insn", "0"), 16) >> 12) & 7 == opcode]
                context = "dual" if mode.startswith("dual_") else mode
                coverage.append(dict(bin=f"{MANIFEST['opcodes'][opcode]}_x_{context}", status="PASS" if hits and not errors else "FAIL",
                                     hits=len(hits), test=mode, event_ids=";".join(event["eid"] for event in hits),
                                     trace=str(trace.relative_to(ROOT))))
    report = ROOT / "reports/compute_live_m_interactions.csv"
    with report.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (ROOT / "reports/compute_live_m_cross_coverage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=coverage[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(coverage)
    passed = sum(row["status"] == "PASS" for row in rows)
    print(f"Live M interactions: {passed}/{len(rows)} PASS")
    expected = {f"{opcode}_x_{context}" for opcode in MANIFEST["opcodes"] for context in MANIFEST["contexts"]}
    actual = {row["bin"] for row in coverage}
    return int(passed != len(rows) or actual != expected or len(coverage) != len(expected) or any(row["status"] != "PASS" for row in coverage))


if __name__ == "__main__":
    raise SystemExit(main())
