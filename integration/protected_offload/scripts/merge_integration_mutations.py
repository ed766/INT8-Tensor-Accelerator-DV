#!/usr/bin/env python3
"""Merge only mutations qualified by activated stimulus and intended failure."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"

rows = []
with (REPORTS / "protected_offload_mutations.csv").open(newline="") as handle:
    for source in csv.DictReader(handle):
        rows.append({
            "mutation": source["mutation"], "macro": source["macro"],
            "status": source["status"], "activated": source.get("activated", "false"),
            "detection": source.get("detection", ""),
            "expected_failure": source.get("expected_failure", ""),
            "exit_code": source.get("exit_code", ""),
        })

additional = (
    ("false_maintenance_completion", "PROTECTED_MUT_FALSE_MAINTENANCE",
     "maintenance_fast_ack_without_command_and_firmware_detected",
     "firmware_rejects_false_maintenance_completion"),
    ("cached_response_corruption", "PROTECTED_MUT_CACHE_RESPONSE_CORRUPT",
     "cpu_observed_corrupt_cache_data", "firmware_readback_data_mismatch"),
)
for name, macro, expected_qualification, expected_failure in additional:
    source_path = REPORTS / f"integration_mutation_{macro.lower()}.csv"
    with source_path.open(newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    qualified = bool(source_rows) and all(
        row.get("status") == "PASS"
        and row.get("mutation_qualification") == expected_qualification
        and int(row.get("mutation_exit_code", "0")) != 0
        for row in source_rows
    )
    rows.append({
        "mutation": name, "macro": macro,
        "status": "DETECTED" if qualified else "MISSED",
        "activated": "true" if qualified else "false",
        "detection": expected_qualification if qualified else "unqualified_mutation_run",
        "expected_failure": expected_failure,
        "exit_code": next((r.get("mutation_exit_code", "") for r in source_rows), ""),
    })

path = REPORTS / "protected_offload_integration_mutations.csv"
with path.open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
detected = sum(row["status"] == "DETECTED" and row["activated"] == "true" for row in rows)
print(f"PROTECTED_INTEGRATION_MUTATIONS|status={'PASS' if detected == 12 else 'FAIL'}|qualified={detected}/12")
raise SystemExit(detected != 12)
