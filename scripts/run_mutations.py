#!/usr/bin/env python3
"""Require each seeded RTL defect to be detected by comparison or assertions."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {
    "MUT_UNSIGNED_MAC": "signed MAC interpretation",
    "MUT_ZEROPOINT_BYPASS": "asymmetric input and weight zero points",
    "MUT_ROUND_TRUNCATE": "round-to-nearest requantization",
    "MUT_RELU_BYPASS": "negative ReLU clamp",
    "MUT_SATURATION_WRAP": "signed INT8 saturation",
    "MUT_TAG_CORRUPT": "transaction tag ordering",
    "MUT_BANK_ALIAS": "double-buffered parameter-bank selection",
    "MUT_OUTPUT_ORDER": "output-channel ordering",
    "MUT_K_LAST_EARLY": "multicycle K-boundary completion",
}


def main() -> int:
    rows = []
    for mutation, protected_behavior in MUTATIONS.items():
        completed = subprocess.run(
            ["python3", "scripts/run_regression.py", "--mutation", mutation, "--expect-fail"],
            cwd=ROOT, text=True, capture_output=True,
        )
        detected = completed.returncode == 0
        rows.append((mutation, protected_behavior, "DETECTED" if detected else "MISSED"))
        print(completed.stdout.strip())
    with (ROOT / "reports" / "mutation_summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["mutation", "protected_behavior", "status"])
        writer.writerows(rows)
    passed = sum(row[2] == "DETECTED" for row in rows)
    print(f"Mutation detection: {passed} / {len(rows)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
