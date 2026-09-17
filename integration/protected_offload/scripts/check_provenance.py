#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
