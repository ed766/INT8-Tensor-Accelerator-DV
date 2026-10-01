#!/usr/bin/env python3
"""Reject legacy mutation rows as a substitute for the crossover audit suite."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "reports/protected_offload_integration_mutations.csv"
REQUIRED = {
    "apb_setup_phase_retirement", "duplicate_mmio_side_effect",
    "irq_before_div_retirement", "stale_muldiv_completion_after_reset",
    "tag_reuse_before_completion_consumption", "queued_configuration_overwrite",
    "completion_before_final_write_response", "lost_simultaneous_irq_event",
    "stale_translation_after_invalidation", "wrong_partial_completion_count",
    "false_maintenance_completion", "wrong_owner_response_delivery",
}

def main() -> int:
    if not REPORT.exists():
        raise SystemExit(f"missing audit-specific mutation report: {REPORT}")
    with REPORT.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    names = {row.get("mutation") for row in rows}
    if names != REQUIRED or len(rows) != len(REQUIRED):
        missing = sorted(REQUIRED - names)
        extra = sorted(names - REQUIRED)
        print(f"CROSSOVER_MUTATIONS|status=INCOMPLETE|missing={';'.join(missing)}|legacy_or_extra={';'.join(extra)}")
        return 1
    bad = [row.get("mutation", "?") for row in rows if row.get("status") != "DETECTED" or
           row.get("activated") != "true" or row.get("compile_status") != "PASS" or
           row.get("nominal_control") != "PASS" or row.get("detection") in ("", "none", "generic") or
           row.get("detection") != row.get("expected_failure")]
    if bad:
        print(f"CROSSOVER_MUTATIONS|status=FAIL|unqualified={';'.join(bad)}")
        return 1
    print(f"CROSSOVER_MUTATIONS|status=PASS|qualified={len(rows)}/{len(REQUIRED)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
