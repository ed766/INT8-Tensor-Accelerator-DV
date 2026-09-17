#!/usr/bin/env python3
"""Refresh the verified manifest for the imported chiplet RTL snapshot."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "vendor" / "chiplet"
SOURCE = Path("/home/esgha/ucie_chiplet_soc/chiplet_extension/rtl")
LOCK = ROOT / "provenance.lock.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not SOURCE.is_dir() or not SNAPSHOT.is_dir():
        raise SystemExit("chiplet source or snapshot is missing")
    files = []
    for path in sorted(SNAPSHOT.rglob("*.sv")):
        relative = path.relative_to(SNAPSHOT).as_posix()
        source_path = SOURCE / relative
        if not source_path.is_file() or digest(path) != digest(source_path):
            raise SystemExit(f"snapshot differs from authoritative source: {relative}")
        files.append({"file": f"vendor/chiplet/{relative}", "sha256": digest(path)})
    lock = json.loads(LOCK.read_text())
    commit = subprocess.check_output(
        ["git", "-C", str(SOURCE.parents[1]), "rev-parse", "HEAD"], text=True
    ).strip()
    lock["chiplet_snapshot"] = {
        "project": "ucie_chiplet_soc",
        "commit": commit,
        "source": "chiplet_extension/rtl",
        "files": files,
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"CHIPLET_SNAPSHOT|status=PASS|commit={commit}|files={len(files)}")


if __name__ == "__main__":
    main()
