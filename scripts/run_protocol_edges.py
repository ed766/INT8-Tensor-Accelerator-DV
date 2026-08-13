#!/usr/bin/env python3
"""Run command, bank-isolation, FIFO-pressure, and reset edge checks."""
from __future__ import annotations
import csv, re, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    build=ROOT/"build"/"protocol_edges";shutil.rmtree(build,ignore_errors=True);build.mkdir(parents=True)
    cmd=["verilator","--binary","--timing","--assert","-Wall","-Wno-fatal","-Wno-SYNCASYNCNET",
         "--top-module","tb_protocol_edges","--Mdir",str(build/"obj"),"rtl/int8_tensor_accel.sv",
         "sim/int8_accel_assertions.sv","sim/tb_protocol_edges.sv"]
    comp=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);(build/"compile.log").write_text(comp.stdout+comp.stderr)
    if comp.returncode:print(comp.stderr);return comp.returncode
    sim=subprocess.run([str(build/"obj"/"Vtb_protocol_edges")],cwd=ROOT,text=True,capture_output=True)
    log=sim.stdout+sim.stderr;(build/"simulation.log").write_text(log)
    passed=sim.returncode==0 and "EDGE_SUMMARY|status=PASS" in log
    match=re.search(r"EDGE_SUMMARY\|status=PASS\|checks=(\d+)",log)
    row={"scenario":"protocol_edges","checks":match.group(1) if match else "0","status":"PASS" if passed else "FAIL"}
    with (ROOT/"reports"/"protocol_edge_summary.csv").open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(row),lineterminator="\n");w.writeheader();w.writerow(row)
    print(f"Protocol edges: {row['status']}, checks={row['checks']}")
    return 0 if passed else 1
if __name__=="__main__":raise SystemExit(main())
