#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--authoritative-source", type=Path, help="also verify source-path entries against immutable Git bytes")
args = parser.parse_args()
lock = json.loads((ROOT / "provenance.lock.json").read_text())
failures = []
for source in lock["sources"]:
    path = ROOT / source["file"]
    if not path.is_file():
        failures.append(f"missing:{source['file']}")
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        failures.append(f"hash:{source['file']}")
    if args.authoritative_source and source.get("source_path"):
        try:
            immutable = subprocess.check_output(["git", "show", f"{source['commit']}:{source['source_path']}"], cwd=args.authoritative_source)
        except subprocess.CalledProcessError:
            failures.append(f"source_commit:{source['file']}")
        else:
            if immutable != path.read_bytes():
                failures.append(f"source_bytes:{source['file']}")
snapshot = lock.get("chiplet_snapshot", {})
for source in snapshot.get("files", []):
    path = ROOT / source["file"]
    if not path.is_file():
        failures.append(f"missing:{source['file']}")
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        failures.append(f"hash:{source['file']}")
count = len(lock["sources"]) + len(snapshot.get("files", []))
print(f"PROTECTED_OFFLOAD_PROVENANCE|status={'PASS' if not failures else 'FAIL'}|files={count}|failures={','.join(failures) or 'none'}")
raise SystemExit(bool(failures))
