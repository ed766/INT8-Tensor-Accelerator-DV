#!/usr/bin/env python3
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];R=ROOT/"reports"
rows=list(csv.DictReader((R/"protected_offload_mutations.csv").open()))
for name,macro in (("false_maintenance_completion","PROTECTED_MUT_FALSE_MAINTENANCE"),("cached_response_corruption","PROTECTED_MUT_CACHE_RESPONSE_CORRUPT")):
 src=list(csv.DictReader((R/("integration_mutation_"+macro.lower()+".csv")).open()))
 rows.append({"mutation":name,"macro":macro,"status":"DETECTED" if src and src[0]["status"]=="PASS" else "MISSED","detection":"firmware_cache_scoreboard","exit_code":"nonzero"})
with (R/"protected_offload_integration_mutations.csv").open("w",newline="") as h:
 w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
det=sum(r["status"]=="DETECTED" for r in rows)
print(f"PROTECTED_INTEGRATION_MUTATIONS|status={'PASS' if det==12 else 'FAIL'}|detected={det}/12")
raise SystemExit(det!=12)
