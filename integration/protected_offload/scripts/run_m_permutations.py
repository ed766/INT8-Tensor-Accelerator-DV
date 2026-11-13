#!/usr/bin/env python3
"""Execute/qualify finite live operand and actual device-IRQ timing crosses."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_crossover_trace import events
from check_compute_host_evidence import check_host_trace
from m_permutation_model import cases, CONTEXTS, OPS, PAIRS, TIMINGS, operand_class
from run_live_m_interactions import qualify as qualify_context

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "integration/protected_offload/spec/m_permutation_coverage.json"


def symbols(path):
    nm = shutil.which("riscv64-unknown-elf-nm")
    if not nm:
        candidate = ROOT.parent / "ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin/riscv64-unknown-elf-nm"
        if candidate.is_file(): nm = str(candidate)
    if not nm: raise RuntimeError("RISC-V nm is required")
    output = subprocess.check_output([nm, "-n", str(path)], text=True)
    found = {parts[-1]: int(parts[0], 16) for line in output.splitlines()
             if len(parts := line.split()) == 3 and parts[-1] in {"m_sweep_begin", "m_sweep_end"}}
    if len(found) != 2 or found["m_sweep_end"] <= found["m_sweep_begin"]:
        raise ValueError("missing/non-executable target M probe")
    return found["m_sweep_begin"], found["m_sweep_end"]


def timing_phase(irq, starts, retires, begin, end):
    cycle = int(irq["cycle"])
    if cycle < int(starts[0]["cycle"]): return "before"
    if cycle > int(retires[-1]["cycle"]): return "after"
    if begin <= int(irq.get("pc", "0"), 16) < end and irq.get("muldiv_busy") == "1":
        state, iteration = int(irq["state"]), int(irq["iteration"])
        if state == 1: return "early" if iteration < 8 else "middle" if iteration < 24 else "late"
        if state == 2: return "finalize"
        if state == 3: return "response"
    if any(abs(int(e["cycle"]) - cycle) <= 1 for e in retires): return "response"
    return "between"


def qualify(entry, trace):
    parsed = events(trace)
    begin, end = symbols(trace.parent / "firmware.elf")
    retires = [e for e in parsed if e.get("kind") == "RETIRE" and e.get("intr") != "1" and begin <= int(e["pc"], 16) < end]
    starts = [e for e in parsed if e.get("kind") == "MDIV_BUSY" and e.get("busy") == "1" and begin <= int(e["pc"], 16) < end]
    errors, witnesses, phase = [], [], ""
    if len(retires) != entry["repeats"] or len(starts) != entry["repeats"]:
        errors.append("probe_accept_retirement_count")
    for start, retirement in zip(starts, retires):
        if (start["pc"] != retirement["pc"] or start["epoch"] != retirement["epoch"] or
                not 0 < int(retirement["cycle"]) - int(start["cycle"]) <= 36):
            errors.append("probe_PC_epoch_or_bounded_retirement")
    for e in retires:
        insn = int(e["insn"], 16)
        if (insn & 0xfe00007f != 0x02000033 or (insn >> 12) & 7 != entry["opcode"] or
                int(e["rs1_data"], 16) != entry["lhs"] or int(e["rs2_data"], 16) != entry["rhs"] or
                int(e["rd_data"], 16) != entry["expected"] or e.get("trap") != "0" or
                int(e["mem_rmask"], 16) or int(e["mem_wmask"], 16)):
            errors.append("probe_operand_opcode_result_or_side_effect")
        witnesses.append(e["eid"])
    if entry["family"] == "operands":
        context = entry["context"]
        for start, retirement in zip(starts, retires):
            active = start.get("dma_busy") == "1"
            if context == "dual": active &= start.get("chip_busy") == "1"
            if context == "sleep": active &= start.get("chip_power") == "2"
            if context == "pressure": active &= start.get("comp_occ") == "4"
            if not active or start["epoch"] != retirement["epoch"]:
                errors.append("requested_service_window_not_reached")
            window = [e for e in parsed if int(start["cycle"]) < int(e["cycle"]) <= int(retirement["cycle"])]
            if any(e.get("kind") in {"DMA_ACTIVE_END", "RESET_ASSERT"} for e in window):
                errors.append("service_or_epoch_ended_before_M_retirement")
            if context == "sleep" and any(e.get("kind") == "CHIPLET_POWER" and e.get("state") != "2" for e in window):
                errors.append("SLEEP_ended_before_M_retirement")
            if context == "dual" and any(e.get("kind") == "CHIPLET_EVT" and e.get("busy") == "0" and
                                         int(start["cycle"]) < int(e["cycle"]) <= int(retirement["cycle"]) for e in parsed):
                errors.append("AES_finished_before_target_M_retirement")
            witnesses.append(start["eid"])
        if context in {"dual", "sleep"}:
            host = check_host_trace(trace)
            if host["status"] != "PASS": errors.append("independent_AES:" + host["first_failure"])
        if context == "sleep":
            _, additional = qualify_context(trace, "sleep")
            errors += additional
    else:
        irqs = [e for e in parsed if e.get("kind") == "IRQ_SET" and e.get("ext") == "1" and int(e.get("raw", "0")) & 2]
        handlers = [e for e in parsed if e.get("kind") == "RETIRE" and e.get("intr") == "1" and e.get("mcause") == "8000000b"]
        if len(irqs) != 1 or len(handlers) != 1 or not starts or not retires:
            errors.append("real_device_IRQ_or_handler_missing")
        else:
            irq, handler = irqs[0], handlers[0]
            phase = timing_phase(irq, starts, retires, begin, end)
            witnesses += [irq["eid"], handler["eid"]]
            if irq.get("muldiv_busy") == "1" and begin <= int(irq["pc"], 16) < end:
                retirement = next((e for e in retires if e["pc"] == irq["pc"] and int(e["cycle"]) >= int(irq["cycle"])), None)
                if not retirement or int(handler["cycle"]) <= int(retirement["cycle"]) or handler["mepc"] != retirement["next_pc"]:
                    errors.append("M_before_IRQ_or_precise_mepc")
    return witnesses, phase, errors


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("family", choices=("operands", "timing"))
    parser.add_argument("--replay-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="debug only; cannot satisfy full closure")
    args = parser.parse_args()
    selected = cases(args.family)
    manifest = json.loads(MANIFEST.read_text())
    if (manifest["schema"] != 1 or manifest["opcodes"] != list(OPS) or
            manifest["operand_contexts"] != list(CONTEXTS) or
            manifest["operand_classes"] != list(PAIRS) or
            manifest["timing_phases"] != list(TIMINGS) or
            manifest[f"{args.family[:-1] if args.family == 'operands' else args.family}_executions"] != len(selected)):
        raise ValueError("matrix does not match versioned manifest")
    if args.limit: selected = selected[:args.limit]
    if not args.replay_only:
        env = dict(os.environ, PROTECTED_M_SWEEP=args.family, PROTECTED_M_SWEEP_LIMIT=str(args.limit))
        run = subprocess.run([sys.executable, str(Path(__file__).with_name("run_shared_firmware.py")), "--model"], cwd=ROOT, env=env)
        if run.returncode: return run.returncode
    origin_path = ROOT / f"reports/compute_m_permutation_{args.family}_runs.csv"
    model_path = ROOT / f"reports/compute_m_permutation_{args.family}_model.csv"
    origin = {r["scenario"]: r for r in csv.DictReader(origin_path.open())}
    model = {Path(r["trace"]).parent.name: r for r in csv.DictReader(model_path.open())}
    rows, coverage = [], []
    for entry in selected:
        name = entry["name"]
        trace = ROOT / origin[name]["trace"]
        sha = hashlib.sha256(trace.read_bytes()).hexdigest()
        witnesses, phase, errors = qualify(entry, trace)
        replay = model.get(name, {})
        if origin[name]["status"] != "PASS" or replay.get("status") != "PASS" or sha != replay.get("trace_sha256") or sha != origin[name].get("trace_sha256"):
            errors.append("simulation_or_independent_replay_provenance")
        rows.append(dict(test=name, status="FAIL" if errors else "PASS", opcode=OPS[entry["opcode"]],
                         context=entry["context"], requested_class=entry["category"],
                         actual_class=operand_class(entry["lhs"], entry["rhs"]), sample=entry["sample"],
                         lhs=f"{entry['lhs']:08x}", rhs=f"{entry['rhs']:08x}", expected=f"{entry['expected']:08x}",
                         requested_b_delay=entry["delay"], observed_timing=phase,
                         event_ids=";".join(witnesses), trace=str(trace.relative_to(ROOT)), trace_sha256=sha,
                         manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), errors=";".join(errors)))
    if args.family == "operands":
        for context in CONTEXTS:
            for op in OPS:
                for category in PAIRS:
                    hits = [r for r in rows if r["context"] == context and r["opcode"] == op and r["actual_class"] == category and r["requested_class"] == category and r["status"] == "PASS"]
                    coverage.append(dict(bin=f"{op}_x_{category}_x_{context}", status="PASS" if {r["sample"] for r in hits} == {0,1} else "FAIL",
                                         hits=len(hits), tests=";".join(r["test"] for r in hits), event_ids=";".join(r["event_ids"] for r in hits)))
    else:
        for op in OPS:
            for phase in TIMINGS:
                hits = [r for r in rows if r["opcode"] == op and r["observed_timing"] == phase and r["status"] == "PASS"]
                coverage.append(dict(bin=f"{op}_x_IRQ_{phase}", status="PASS" if hits else "FAIL", hits=len(hits),
                                     tests=";".join(r["test"] for r in hits), event_ids=";".join(r["event_ids"] for r in hits)))
    write_csv(ROOT / f"reports/compute_m_permutation_{args.family}_summary.csv", rows)
    for point in coverage:
        point["first_test"] = point["tests"].split(";", 1)[0]
        point["evidence_source"] = "RTL observer events joined to strict ISS/device replay and arithmetic oracle"
    write_csv(ROOT / f"reports/compute_m_permutation_{args.family}_coverage.csv", coverage)
    passed = sum(r["status"] == "PASS" for r in rows)
    closed = sum(r["status"] == "PASS" for r in coverage)
    print(f"M {args.family}: {passed}/{len(rows)} executions; {closed}/{len(coverage)} crosses")
    return int(passed != len(rows) or closed != len(coverage))


if __name__ == "__main__":
    raise SystemExit(main())
