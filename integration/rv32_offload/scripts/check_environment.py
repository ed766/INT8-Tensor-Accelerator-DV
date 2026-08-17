#!/usr/bin/env python3
"""Validate the vendored RV32 snapshot and benchmark dependencies."""
from __future__ import annotations
import hashlib,importlib.util,subprocess
from pathlib import Path
from build_firmware import tool
ROOT=Path(__file__).resolve().parents[3];BASE=ROOT/"integration/rv32_offload";LOCK=BASE/"rv32_snapshot.lock"
def main()->int:
    entries={}
    for line in LOCK.read_text().splitlines():
      if line and not line.startswith("#"):key,value=line.split("=",1);entries[key]=value
    for name in ("rv32_core.sv","rv32_rom_feeder.sv"):
      actual=hashlib.sha256((BASE/"rv32"/name).read_bytes()).hexdigest()
      if actual!=entries[name]:raise SystemExit(f"vendored RV32 hash mismatch: {name}")
    if importlib.util.find_spec("torch") is None:raise SystemExit("PyTorch is unavailable in the selected Python environment")
    first=subprocess.run([tool("gcc"),"--version"],capture_output=True,text=True,check=True).stdout.splitlines()[0]
    print(f"RV32 benchmark environment PASS\nsource commit: {entries['source_commit']}\ncompiler: {first}")
    return 0
if __name__=="__main__":raise SystemExit(main())
