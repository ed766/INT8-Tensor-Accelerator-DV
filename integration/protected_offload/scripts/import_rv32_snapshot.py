#!/usr/bin/env python3
"""Import exact immutable authoritative RV32 bytes, never patched vendor RTL."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, default=ROOT.parents[2] / "ucie_chiplet_soc")
parser.add_argument("--commit", required=True)
args = parser.parse_args()
commit = subprocess.check_output(["git", "rev-parse", args.commit + "^{commit}"], cwd=args.source, text=True).strip()
paths = {
    "rv32_core.sv": "base_soc/rtl/pd1_rv32/rv32_core.sv",
    "rv32_muldiv.sv": "base_soc/rtl/pd1_rv32/rv32_muldiv.sv",
    "rv32_rom_feeder.sv": "chiplet_extension/rtl/firmware/rv32_rom_feeder.sv",
}
payloads = {}
for name, source_path in paths.items():
    data = subprocess.check_output(["git", "show", f"{commit}:{source_path}"], cwd=args.source)
    if data != (args.source / source_path).read_bytes():
        raise SystemExit(f"authoritative working file differs from commit: {source_path}")
    payloads[name] = data
lock_path = ROOT / "provenance.lock.json"
lock = json.loads(lock_path.read_text())
for source in lock["sources"]:
    name = Path(source["file"]).name
    if source["file"].startswith("vendor/rv32/") and name in payloads:
        data = payloads[name]
        (ROOT / source["file"]).write_bytes(data)
        source.update(commit=commit, source_path=paths[name],
                      sha256=hashlib.sha256(data).hexdigest(),
                      source_state="byte-identical immutable authoritative source including verification hooks")
lock_path.write_text(json.dumps(lock, indent=2) + "\n")
print(f"RV32 snapshot: {len(payloads)} exact source files at {commit}")
