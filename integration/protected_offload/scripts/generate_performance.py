#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"


def read(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    dma = read(REPORTS / "protected_offload_performance_summary.csv")
    benchmark = read(REPORTS / "rv32_accel_benchmark.csv")
    rows = []
    for dma_row in dma:
        k, batch = int(dma_row["k"]), int(dma_row["batch"])
        candidates = [row for row in benchmark if int(row["k"]) == k and
                      int(row["batch"]) == batch and row["mode"] == "warm" and row["status"] == "PASS"]
        if not candidates:
            raise SystemExit(f"Missing canonical RV32 benchmark row for K={k} batch={batch}")
        base = candidates[0]
        scalar = int(base["scalar_adjusted_cycles"])
        mmio = int(base["accel_adjusted_cycles"])
        dma_cycles = int(dma_row["job_cycles"])
        common = {"k": k, "batch": batch, "status": "PASS"}
        rows.extend([
            {**common, "path": "rv32_scalar", "cycles": scalar, "host_interface": "local_sram", "source": "rv32_accel_benchmark.csv"},
            {**common, "path": "mmio_stream", "cycles": mmio, "host_interface": "apb_stream_mailbox", "source": "rv32_accel_benchmark.csv"},
            {**common, "path": "protected_dma", "cycles": dma_cycles, "host_interface": "descriptor_memory", "source": dma_row["trace"]},
        ])
    with (REPORTS / "protected_offload_performance.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    lines = ["# Protected Offload Performance", "",
             "All values are behavioral Verilator cycles. The scalar and MMIO rows come from the existing passing RV32 benchmark; DMA rows execute the new descriptor path.", "",
             "| K | Batch | Scalar cycles | MMIO-stream cycles | DMA job cycles | DMA vs scalar |", "| ---: | ---: | ---: | ---: | ---: | ---: |"]
    for k in (4, 8, 16, 32, 64):
        for batch in (1, 16, 64):
            selected = {row["path"]: row for row in rows if row["k"] == k and row["batch"] == batch}
            scalar = int(selected["rv32_scalar"]["cycles"])
            mmio = int(selected["mmio_stream"]["cycles"])
            dma_cycles = int(selected["protected_dma"]["cycles"])
            lines.append(f"| {k} | {batch} | {scalar} | {mmio} | {dma_cycles} | {scalar/dma_cycles:.2f}x |")
    lines += ["", "These paths have different software boundaries; the table preserves raw cycles so reviewers can inspect the comparison.", ""]
    (ROOT / "docs/protected_offload_performance.md").write_text("\n".join(lines))
    print(f"PROTECTED_OFFLOAD_PERFORMANCE|status=PASS|rows={len(rows)}/45")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
