#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build" / "protected_offload"
REPORTS = ROOT / "reports"
BINARY = BUILD / "obj" / "Vtb_protected_offload"
SOURCES = [
    ROOT / "rtl/int8_tensor_accel.sv",
    ROOT / "integration/protected_offload/rtl/protected_queue_count_next.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_dma.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_apb_csr.sv",
    ROOT / "integration/protected_offload/sim/tb_protected_offload.sv",
]


def compile_rtl() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    command = [
        "verilator", "--binary", "--sv", "--timing", "--assert", "-Wall",
        "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
        "--top-module", "tb_protected_offload", "--Mdir", str(BUILD / "obj"),
        *map(str, SOURCES),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def parse_result(output: str) -> dict[str, str]:
    line = next((line for line in output.splitlines() if line.startswith("PROTECTED_OFFLOAD|")), "")
    if not line:
        return {"status": "FAIL", "failure": "missing_result"}
    result = {}
    for field in line.split("|")[1:]:
        key, value = field.split("=", 1)
        result[key] = value.strip()
    result["failure"] = "" if result.get("status") == "PASS" else "rtl_failure"
    return result


def run_one(name: str, knobs: dict[str, int]) -> dict[str, str]:
    event_dir = BUILD / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    event_path = event_dir / f"{name}.csv"
    command = [str(BINARY), f"+EVENT_FILE={event_path}"]
    command.extend(f"+{key}={value}" for key, value in knobs.items())
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    result = parse_result(process.stdout + process.stderr)
    result.update({"name": name, **{key.lower(): str(value) for key, value in knobs.items()}})
    result["trace"] = str(event_path.relative_to(ROOT))
    if process.returncode != 0:
        result["status"] = "FAIL"
        result["failure"] = result.get("failure") or f"exit_{process.returncode}"
    return result


def directed_scenarios() -> list[tuple[str, dict[str, int]]]:
    scenarios: list[tuple[str, dict[str, int]]] = []
    for k in (4, 8, 16, 32, 64):
        scenarios.append((f"functional_k{k}_b1", {"K": k, "BATCH": 1, "BP_PCT": 0, "FAULT": 0, "PATTERN": (k//4)%5}))
        scenarios.append((f"functional_k{k}_b4", {"K": k, "BATCH": 4, "BP_PCT": 0, "FAULT": 0, "PATTERN": (k//8+1)%5}))
    for bp in (0, 25, 50, 75):
        scenarios.append((f"backpressure_k16_b4_p{bp}", {"K": 16, "BATCH": 4, "BP_PCT": bp, "FAULT": 0}))
        scenarios.append((f"backpressure_k64_b2_p{bp}", {"K": 64, "BATCH": 2, "BP_PCT": bp, "FAULT": 0}))
    fault_names = {1: "read_translation", 2: "write_translation", 3: "input_bus", 4: "output_bus"}
    for fault, label in fault_names.items():
        scenarios.append((f"fault_{label}_k4", {"K": 4, "BATCH": 1, "BP_PCT": 0, "FAULT": fault}))
        scenarios.append((f"fault_{label}_k64", {"K": 64, "BATCH": 1, "BP_PCT": 25, "FAULT": fault}))
    for stall in (1, 4, 16, 64):
        scenarios.append((f"completion_hold_{stall}", {"K": 16, "BATCH": 2, "BP_PCT": 25, "FAULT": 0, "COMP_STALL": stall}))
    for asid, qos in ((1, 0), (1, 15), (127, 4), (255, 12)):
        scenarios.append((f"context_asid{asid}_qos{qos}", {"K": 32, "BATCH": 2, "BP_PCT": 50, "FAULT": 0, "ASID": asid, "QOS": qos}))
    for batch in (1, 2, 8, 16, 32, 64):
        scenarios.append((f"batch_depth_{batch}", {"K": 8, "BATCH": batch, "BP_PCT": 25, "FAULT": 0}))
    assert len(scenarios) == 40
    return scenarios


def random_scenarios(count: int = 100) -> list[tuple[str, dict[str, int]]]:
    scenarios = []
    for index in range(count):
        rng = random.Random(0x51A70000 + index)
        fault = rng.choices([0, 1, 2, 3, 4], weights=[76, 6, 6, 6, 6])[0]
        knobs = {
            "K": rng.choice([4, 8, 16, 32, 64]),
            "BATCH": rng.choice([1, 2, 4, 8]),
            "BP_PCT": rng.choice([0, 25, 50, 75]),
            "FAULT": fault,
            "COMP_STALL": rng.choice([0, 0, 4, 16]),
            "ASID": rng.choice([0, 1, 17, 127, 255]),
            "QOS": rng.randrange(16),
            "PATTERN": rng.randrange(5),
        }
        scenarios.append((f"random_{index:03d}", knobs))
    return scenarios


def coverage_scenarios() -> list[tuple[str, dict[str, int]]]:
    scenarios: list[tuple[str, dict[str, int]]] = []
    for k in (4, 8, 16, 32, 64):
        for outcome in (0, 1):
            scenarios.append((f"cross_k{k}_outcome{outcome}",
                              {"K": k, "BATCH": 1, "BP_PCT": 0, "FAULT": outcome}))
    for bp in (0, 25, 50, 75):
        for outcome in (0, 3):
            scenarios.append((f"cross_bp{bp}_outcome{outcome}",
                              {"K": 16, "BATCH": 2, "BP_PCT": bp, "FAULT": outcome}))
    for asid_index, asid in enumerate((0, 1, 127, 255)):
        for qos_class, qos in enumerate((0, 5, 10, 15)):
            scenarios.append((f"cross_asid{asid_index}_qos{qos_class}",
                              {"K": 8, "BATCH": 2, "BP_PCT": 25, "FAULT": 0,
                               "ASID": asid, "QOS": qos}))
    for fault in range(5):
        for bp in (0, 25, 50, 75):
            scenarios.append((f"cross_fault{fault}_bp{bp}",
                              {"K": 32, "BATCH": 1, "BP_PCT": bp, "FAULT": fault}))
    for batch in (1, 2, 4, 8, 16):
        for hold in (0, 8):
            scenarios.append((f"cross_batch{batch}_hold{hold}",
                              {"K": 16, "BATCH": batch, "BP_PCT": 50,
                               "FAULT": 0, "COMP_STALL": hold}))
    assert len(scenarios) == 64
    return scenarios


def performance_scenarios() -> list[tuple[str, dict[str, int]]]:
    return [(f"performance_k{k}_b{batch}",
             {"K": k, "BATCH": batch, "BP_PCT": 0, "FAULT": 0})
            for k in (4, 8, 16, 32, 64) for batch in (1, 16, 64)]


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    keys = ["name", "status", "failure", "k", "batch", "bp_pct", "fault", "pattern",
            "comp_stall", "asid", "qos", "cycles", "job_cycles", "reads", "writes",
            "translations", "stalls", "irq_cycles", "trace"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_group(mode: str) -> int:
    compile_rtl()
    if mode == "directed":
        scenarios = directed_scenarios()
    elif mode == "coverage":
        scenarios = coverage_scenarios()
    elif mode == "performance":
        scenarios = performance_scenarios()
    else:
        scenarios = random_scenarios()
    if mode == "smoke":
        scenarios = [("smoke", {"K": 16, "BATCH": 2, "BP_PCT": 25, "FAULT": 0})]
    rows = [run_one(name, knobs) for name, knobs in scenarios]
    write_summary(REPORTS / f"protected_offload_{mode}_summary.csv", rows)
    passed = sum(row.get("status") == "PASS" for row in rows)
    print(f"PROTECTED_OFFLOAD_{mode.upper()}|status={'PASS' if passed == len(rows) else 'FAIL'}|passed={passed}/{len(rows)}")
    return 0 if passed == len(rows) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["smoke", "directed", "random", "coverage", "performance"])
    args = parser.parse_args()
    return run_group(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
