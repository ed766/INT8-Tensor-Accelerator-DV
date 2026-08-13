#!/usr/bin/env python3
"""Compare Yosys implementation proxies for 4x4 and 8x8 variants."""
from __future__ import annotations
import csv,re,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    yosys=shutil.which("yosys");rows=[];(ROOT/"build").mkdir(exist_ok=True)
    for name,lanes,outputs in (("baseline_4x4",4,4),("scaled_8x8",8,8)):
        if not yosys:
            rows.append({"variant":name,"lanes":lanes,"outputs":outputs,"status":"SKIP","cells":"NA","register_cells":"NA","multiplier_cells":"NA","warnings":"NA"});continue
        script=(f"read_verilog -sv rtl/int8_tensor_accel.sv; hierarchy -top int8_tensor_accel; "
                f"chparam -set LANES {lanes} -set OUTPUTS {outputs} int8_tensor_accel; proc; opt; memory; opt; stat")
        done=subprocess.run([yosys,"-p",script],cwd=ROOT,text=True,capture_output=True);log=done.stdout+done.stderr
        (ROOT/"build"/f"synthesis_{name}.log").write_text(log)
        cells=re.findall(r"Number of cells:\s+(\d+)",log);dff=sum(map(int,re.findall(r"\$(?:a?dff\w*)\s+(\d+)",log,re.I)))
        mul=sum(map(int,re.findall(r"\$mul\s+(\d+)",log)))
        rows.append({"variant":name,"lanes":lanes,"outputs":outputs,"status":"PASS" if done.returncode==0 and cells else "FAIL",
                     "cells":cells[-1] if cells else "NA","register_cells":dff,"multiplier_cells":mul,
                     "warnings":len(re.findall(r"^Warning:",log,re.M))})
    with (ROOT/"reports"/"synthesis_summary.csv").open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]),lineterminator="\n");w.writeheader();w.writerows(rows)
    lines=["# Synthesis Proxy","","| Variant | MAC array | Status | Generic cells | Registers | Multipliers | Warnings |","| --- | ---: | --- | ---: | ---: | ---: | ---: |"]
    for r in rows:lines.append(f"| {r['variant']} | {int(r['lanes'])*int(r['outputs'])} | {r['status']} | {r['cells']} | {r['register_cells']} | {r['multiplier_cells']} | {r['warnings']} |")
    lines += ["","Yosys statistics are open-source structural proxies. Array lowering warnings are retained and these values are not area, timing, power, or implementation signoff.",""]
    (ROOT/"docs"/"synthesis.md").write_text("\n".join(lines))
    print("Synthesis variants: "+", ".join(f"{r['variant']}={r['status']}" for r in rows))
    return 0 if all(r["status"] in ("PASS","SKIP") for r in rows) else 1
if __name__=="__main__":raise SystemExit(main())
