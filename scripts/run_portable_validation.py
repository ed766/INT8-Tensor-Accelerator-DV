#!/usr/bin/env python3
"""Run the packed portable-vector stream through RTL and summarize results."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    metadata = json.loads((ROOT / "portable" / "portable_vectors.json").read_text())
    build = ROOT / "build" / "portable"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    sources = [
        ROOT / "rtl" / "int8_tensor_accel.sv",
        ROOT / "rtl" / "int8_accel_health_monitor.sv",
        ROOT / "sim" / "tb_portable_vectors.sv",
    ]
    command = ["verilator", "--binary", "--timing", "--assert", "-Wall", "-Wno-fatal",
               "-Wno-SYNCASYNCNET", "-Wno-UNUSEDSIGNAL", "--top-module", "tb_portable_vectors",
               "--Mdir", str(build / "obj"), *map(str, sources)]
    compiled = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (build / "compile.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        print(compiled.stderr)
        return 1
    simulated = subprocess.run([
        str(build / "obj" / "Vtb_portable_vectors"),
        f"+VECTOR_FILE={ROOT / 'portable' / 'portable_vectors.mem'}",
        f"+VECTOR_COUNT={metadata['records']}",
    ], cwd=build, text=True, capture_output=True, timeout=120)
    log = simulated.stdout + simulated.stderr
    (build / "simulation.log").write_text(log)
    rows: list[dict[str, str]] = []
    for line in log.splitlines():
        if not line.startswith("PORTABLE_CHECK|"):
            continue
        fields = dict(field.split("=", 1) for field in line.split("|")[1:] if "=" in field)
        rows.append({key: fields.get(key, "") for key in
                     ("case", "status", "tag", "expected", "observed", "observed_tag")})
    with (ROOT / "reports" / "portable_validation_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys() if rows else ["case", "status"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    passed = simulated.returncode == 0 and len(rows) == metadata["cases"] and all(row["status"] == "PASS" for row in rows)
    print(f"PORTABLE_VALIDATION|status={'PASS' if passed else 'FAIL'}|cases={sum(r['status'] == 'PASS' for r in rows)}/{len(rows)}|sha256={metadata['sha256'][:12]}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
