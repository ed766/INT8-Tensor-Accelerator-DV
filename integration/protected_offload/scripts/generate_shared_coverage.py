#!/usr/bin/env python3
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];R=ROOT/"reports"
def read(name):
 p=R/name
 if not p.exists():raise SystemExit(f"missing required evidence: {p.name}")
 return list(csv.DictReader(p.open()))
manifest=json.loads((ROOT/"integration/protected_offload/coverage/shared_integration_manifest.json").read_text())
normal=read("protected_shared_firmware.csv")+read("protected_shared_random.csv")+read("protected_shared_compiler_matrix.csv")+read("protected_cache_ownership.csv")
negative=read("protected_cache_negative.csv")
if any(r["status"]!="PASS" for r in normal+negative):raise SystemExit("shared integration contains a failing row")
def present(group,value):
 if group=="transport":
  token={"host_axi":"host=1","dma_axi":"dma=1","page_walk_axi":"ptw=1","qos_fabric":"fabric=1"}[value]
  return any(token in r["evidence"] for r in normal)
 if group=="completion":return any(r.get("completion_mode")==("irq" if value=="interrupt_wfi" else "poll") for r in normal)
 if group=="isa":return any(r.get("isa")==value for r in normal)
 if group=="optimizer":return any(r.get("optimizer")==value for r in normal)
 if group=="geometry_k":return any(r["k"]==value for r in normal)
 if group=="batch":return any(r["batch"]==value for r in normal)
 if group=="asid":return any(r["asid"]==value for r in normal)
 if group=="qos":
  ranges={"low":range(0,4),"mid":range(4,8),"high":range(8,12),"critical":range(12,16)}
  return any(int(r["qos"]) in ranges[value] for r in normal)
 if group=="cache_ownership":
  if value=="positive_handoff":return bool(read("protected_cache_ownership.csv"))
  key={"skip_flush_detected":"NEG_SKIP_FLUSH","skip_invalidate_detected":"NEG_SKIP_INVALIDATE","late_dirty_detected":"NEG_LATE_DIRTY","active_access_detected":"NEG_ACCESS_DURING"}[value]
  return any(r["expected_negative"]==key for r in negative)
 return False
points=[]
for group,values in manifest["points"].items():
 for value in values:points.append({"kind":"point","group":group,"name":value,"status":"COVERED" if present(group,value) else "UNCOVERED","evidence":"executable RTL report"})
crosses=[]
for group,values in manifest["crosses"].items():
 for value in values:
  a,b=value.split(":")
  if group=="isa_x_optimizer":hit=any(r.get("isa")==a and r.get("optimizer")==b for r in normal)
  elif group=="completion_x_cache":hit=any(r.get("completion_mode")==("irq" if a=="interrupt_wfi" else "poll") and r.get("cache")==("1" if b=="cached" else "0") for r in normal)
  elif group=="asid_x_translation":hit=any(r["asid"]==a and "ptw=1" in r["evidence"] for r in normal)
  else:hit=present("cache_ownership",a)
  crosses.append({"kind":"cross","group":group,"name":value,"status":"COVERED" if hit else "UNCOVERED","evidence":"same execution/window"})
rows=points+crosses
with (R/"protected_shared_integration_coverage.csv").open("w",newline="") as h:
 w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
hit=sum(r["status"]=="COVERED" for r in rows)
print(f"PROTECTED_SHARED_COVERAGE|status={'PASS' if hit==len(rows) else 'FAIL'}|covered={hit}/{len(rows)}|points={len(points)}|crosses={len(crosses)}")
raise SystemExit(hit!=len(rows))
