#!/usr/bin/env python3
"""Compile and run the chained two-layer PyTorch/RTL demonstration."""

from __future__ import annotations
import csv, shutil, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    build=ROOT/"build"/"mlp_sim"
    shutil.rmtree(build,ignore_errors=True); build.mkdir(parents=True)
    command=["verilator","--binary","--timing","--assert","-Wall","-Wno-fatal","-Wno-SYNCASYNCNET",
             "--top-module","tb_pytorch_mlp","--Mdir",str(build/"obj"),"-I"+str(ROOT/"build"),
             "rtl/int8_tensor_accel.sv","sim/int8_accel_assertions.sv","sim/tb_pytorch_mlp.sv"]
    compiled=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (build/"compile.log").write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode: print(compiled.stderr); return compiled.returncode
    simulated=subprocess.run([str(build/"obj"/"Vtb_pytorch_mlp")],cwd=ROOT,text=True,capture_output=True)
    log=simulated.stdout+simulated.stderr; (build/"simulation.log").write_text(log)
    passed=simulated.returncode==0 and "MLP_SUMMARY|status=PASS" in log
    row={"scenario":"two_layer_chained_rtl","samples":16,"intermediate_words":64,"final_words":64,
         "status":"PASS" if passed else "FAIL"}
    with (ROOT/"reports"/"pytorch_mlp_rtl_summary.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(row),lineterminator="\n"); writer.writeheader(); writer.writerow(row)
    print(f"Two-layer RTL chain: {row['status']}")
    return 0 if passed else 1
if __name__=="__main__": raise SystemExit(main())
