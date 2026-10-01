#!/usr/bin/env python3
"""Require deterministic regeneration of normalized crossover evidence."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMMANDS = (
    ("coverage", ROOT / "integration/protected_offload/scripts/generate_compute_crossover_coverage.py"),
    ("crosses", ROOT / "integration/protected_offload/scripts/generate_crossover_cross_coverage.py"),
    ("dashboard", ROOT / "integration/protected_offload/scripts/generate_crossover_dashboard.py"),
    ("metrics", ROOT / "scripts/generate_metrics.py"),
)
OUTPUTS = (
    ROOT / "reports/compute_crossover_coverage.csv",
    ROOT / "reports/compute_crossover_coverage_model_directed.csv",
    ROOT / "reports/compute_crossover_coverage_model_random.csv",
    ROOT / "reports/compute_crossover_coverage_model_cpu.csv",
    ROOT / "reports/compute_crossover_coverage_model_edges.csv",
    ROOT / "reports/compute_crossover_coverage_model_cache.csv",
    ROOT / "reports/compute_crossover_cross_coverage.csv",
    ROOT / "reports/compute_crossover_evidence_dashboard.csv",
    ROOT / "docs/compute_crossover_evidence_dashboard.md",
    ROOT / "reports/project_metrics.csv",
    ROOT / "docs/project_metrics.md",
    ROOT / "README.md",
)


def regenerate() -> dict[str, str]:
    for name, script in COMMANDS:
        run = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode:
            print(run.stdout, end="")
            raise SystemExit(f"reproducibility regeneration failed: {name}")
    missing = [str(path.relative_to(ROOT)) for path in OUTPUTS if not path.is_file()]
    if missing:
        raise SystemExit(f"reproducibility outputs missing: {', '.join(missing)}")
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in OUTPUTS}


def main() -> int:
    first = regenerate()
    second = regenerate()
    changed = [name for name in first if first[name] != second[name]]
    if changed:
        raise SystemExit("normalized report regeneration is nondeterministic: " + ", ".join(changed))
    print(f"CROSSOVER_REPRODUCIBILITY|status=PASS|artifacts={len(first)}|regenerations=2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
