#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
SPEC=ROOT/"integration/protected_offload/spec/address_map.json"
def main()->int:
  spec=json.loads(SPEC.read_text());regions=spec["regions"]
  sv=["package protected_offload_addr_pkg;"]
  ch=["#ifndef PROTECTED_OFFLOAD_ADDRESS_MAP_H","#define PROTECTED_OFFLOAD_ADDRESS_MAP_H",""]
  md=["# Protected Offload Address Map","","Generated from `integration/protected_offload/spec/address_map.json`.","","| Region | Base | Size | Use |","| --- | ---: | ---: | --- |"]
  for r in regions:
    name=r["name"];base=int(r["base"],16);size=int(r["size"],16)
    sv.append(f"  localparam logic [31:0] {name}_BASE = 32'h{base:08x};")
    sv.append(f"  localparam logic [31:0] {name}_SIZE = 32'h{size:08x};")
    ch.append(f"#define {name}_BASE 0x{base:08x}u")
    ch.append(f"#define {name}_SIZE 0x{size:08x}u")
    md.append(f"| `{name}` | `0x{base:08x}` | `0x{size:x}` | {r['use']} |")
  sv += ["endpackage",""];ch += ["","#endif",""];md.append("")
  (ROOT/"integration/protected_offload/rtl/protected_offload_addr_pkg.sv").write_text("\n".join(sv))
  (ROOT/"integration/protected_offload/firmware").mkdir(parents=True,exist_ok=True)
  (ROOT/"integration/protected_offload/firmware/protected_offload_address_map.h").write_text("\n".join(ch))
  (ROOT/"docs/protected_offload_address_map.md").write_text("\n".join(md))
  print(f"PROTECTED_OFFLOAD_ADDRESS_MAP|status=PASS|regions={len(regions)}")
  return 0
if __name__=="__main__":raise SystemExit(main())
