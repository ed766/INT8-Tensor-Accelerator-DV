#!/usr/bin/env python3
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build/protected_offload"
FIRMWARE = BUILD / "firmware"
REPORT = ROOT / "reports/protected_offload_firmware.csv"
BINARY = BUILD / "firmware_exec_obj/Vtb_rv32_protected_offload"
SOURCES = [
    ROOT / "integration/protected_offload/vendor/rv32/rv32_core.sv",
    ROOT / "integration/protected_offload/vendor/rv32/rv32_rom_feeder.sv",
    ROOT / "rtl/int8_tensor_accel.sv",
    ROOT / "integration/protected_offload/rtl/protected_queue_count_next.sv",
    ROOT / "integration/protected_offload/vendor/axi/dma_iommu.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_dma.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_apb_csr.sv",
    ROOT / "integration/protected_offload/rtl/rv32_protected_offload_top.sv",
    ROOT / "integration/protected_offload/sim/tb_rv32_protected_offload.sv",
]


def compile_rtl() -> None:
    command = [
        "verilator", "--binary", "--sv", "--timing", "--assert", "-Wall",
        "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET", "-Wno-BLKSEQ",
        "-Wno-PINCONNECTEMPTY", "-Wno-TIMESCALEMOD", "-Wno-VARHIDDEN",
        "--top-module", "tb_rv32_protected_offload",
        "--Mdir", str(BUILD / "firmware_exec_obj"),
        *map(str, SOURCES),
    ]
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def parse_result(output: str) -> dict[str, str]:
    line = next((entry for entry in output.splitlines()
                 if entry.startswith("PROTECTED_FIRMWARE_EXEC|")), "")
    if not line:
        return {"execution_status": "FAIL", "execution_detail": "missing result marker"}
    parsed = {field.split("=", 1)[0]: field.split("=", 1)[1]
              for field in line.split("|")[1:]}
    return {
        "execution_status": parsed.get("status", "FAIL"),
        "execution_cycles": parsed.get("cycles", ""),
        "retired_instructions": parsed.get("commits", ""),
        "tlb_hits": parsed.get("tlb_hits", ""),
        "tlb_misses": parsed.get("tlb_misses", ""),
        "page_walk_reads": parsed.get("walks", ""),
        "execution_detail": "RV32 APB/DMA/accelerator/output-memory scoreboard",
    }


def main() -> int:
    subprocess.run(["python3", str(ROOT / "integration/protected_offload/scripts/build_firmware_matrix.py")],
                   cwd=ROOT, check=True)
    with REPORT.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if any(row["status"] != "PASS" for row in rows):
        print("PROTECTED_OFFLOAD_FIRMWARE_EXEC|status=SKIP|passed=0/24|reason=toolchain")
        return 0

    compile_rtl()
    for row in rows:
        case = FIRMWARE / f"workflow_{row['workflow']}_{row['optimizer']}"
        process = subprocess.run([
            str(BINARY),
            f"+FIRMWARE_HEX={case / 'firmware.hex'}",
            f"+DATA_HEX={case / 'data.hex'}",
            f"+WORKFLOW={row['workflow']}",
        ], cwd=ROOT, text=True, capture_output=True)
        parsed = parse_result(process.stdout + process.stderr)
        if process.returncode != 0:
            parsed["execution_status"] = "FAIL"
            parsed["execution_detail"] = (process.stdout + process.stderr).strip()[-500:]
        row.update(parsed)

    fields = [
        "workflow", "optimizer", "status", "execution_status", "elf_sha256",
        "instruction_bytes", "execution_cycles", "retired_instructions", "tlb_hits",
        "tlb_misses", "page_walk_reads", "detail", "execution_detail",
    ]
    with REPORT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    passed = sum(row.get("execution_status") == "PASS" for row in rows)
    print(f"PROTECTED_OFFLOAD_FIRMWARE_EXEC|status={'PASS' if passed == 24 else 'FAIL'}|passed={passed}/24")
    return 0 if passed == 24 else 1


if __name__ == "__main__":
    raise SystemExit(main())
