"""Require two identical regenerations of normalized crossover evidence."""
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
ARTIFACTS=("README.md","integration/protected_offload/implementation_ledger.csv",
           "docs/compute_crossover_evidence_dashboard.md","reports/compute_crossover_evidence_dashboard.csv",
           "reports/compute_gap_cross_coverage.csv","reports/compute_gap_contention.csv")


def main():
    snapshots=[]
    for iteration in range(2):
        for script in ('report_gap_evidence.py','summarize_stateful_evidence.py','generate_crossover_dashboard.py'):
            subprocess.run([sys.executable,str(Path(__file__).with_name(script))],cwd=ROOT,check=True)
        snapshots.append({path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in ARTIFACTS})
    rows=[dict(artifact=path,status='PASS' if snapshots[0][path]==snapshots[1][path] else 'FAIL',
               first_sha256=snapshots[0][path],second_sha256=snapshots[1][path],regenerations=2) for path in ARTIFACTS]
    with (ROOT/'reports/compute_gap_reproducibility.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
    print(f"Gap normalized reproducibility: {sum(r['status']=='PASS' for r in rows)}/{len(rows)}")
    return int(any(r['status']!='PASS' for r in rows))


if __name__=='__main__':raise SystemExit(main())
