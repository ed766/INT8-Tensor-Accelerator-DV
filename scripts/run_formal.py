#!/usr/bin/env python3
"""Run reduced-geometry solver proofs and reachable covers."""
from __future__ import annotations
import csv, os, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def find_sby()->str|None:
    direct=shutil.which("sby")
    if direct:return direct
    candidates=[Path.home()/".cache"/"oss-cad-suite"/"bin"/"sby",
                Path.home()/"ucie_chiplet_soc"/"chiplet_extension"/"build"/"external_riscv_tools"/"oss-cad-suite"/"oss-cad-suite"/"bin"/"sby"]
    return str(next((p for p in candidates if p.exists()),"")) or None
def main()->int:
    sby=find_sby(); rows=[]
    if not sby:
        rows=[{"group":"control_safety","mode":"solver","status":"SKIP","depth":16,"detail":"sby unavailable"},
              {"group":"reachability","mode":"cover","status":"SKIP","depth":20,"detail":"sby unavailable"}]
    else:
        for task_dir in (ROOT/"formal"/"int8_control_prove",ROOT/"formal"/"int8_control_cover"):
            shutil.rmtree(task_dir,ignore_errors=True)
        env=os.environ.copy();suite=Path(sby).resolve().parent.parent
        env["PATH"]=f"{Path(sby).parent}:{env.get('PATH','')}"
        completed=subprocess.run([sby,"-f","int8_control.sby"],cwd=ROOT/"formal",env=env,text=True,capture_output=True)
        (ROOT/"build").mkdir(exist_ok=True);(ROOT/"build"/"formal.log").write_text(completed.stdout+completed.stderr)
        for task,mode,depth in (("prove","bounded_solver_safety",16),("cover","reachable_cover",20)):
            status_file=ROOT/"formal"/f"int8_control_{task}"/"status"
            passed=status_file.exists() and status_file.read_text().split()[0]=="PASS"
            rows.append({"group":"control_safety" if task=="prove" else "reachability","mode":mode,
                         "status":"PASS" if passed else "FAIL","depth":depth,
                         "detail":"six control/FIFO invariants" if task=="prove" else "FIFO-full/error/bank-swap covers"})
    with (ROOT/"reports"/"formal_summary.csv").open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]),lineterminator="\n");w.writeheader();w.writerows(rows)
    passed=sum(r["status"]=="PASS" for r in rows);skipped=sum(r["status"]=="SKIP" for r in rows)
    (ROOT/"docs"/"formal.md").write_text(
        "# Formal Evidence\n\nThe reduced `2x2`, `MAX_K=8`, two-entry configuration uses SymbiYosys to check "
        "FIFO bounds, command accounting, illegal-command containment, bank stability, and backpressure stability. "
        "Reachability covers require FIFO-full, command-error, and bank-swap states.\n\n"+
        "\n".join(f"- `{r['group']}`: **{r['status']}**, {r['mode']}, depth {r['depth']}" for r in rows)+
        "\n\nThis is reduced-geometry open-source solver evidence, not exhaustive accelerator or numerical correctness proof.\n")
    print(f"Formal: {passed} PASS, {skipped} SKIP, {len(rows)-passed-skipped} FAIL")
    return 0 if all(r["status"] in ("PASS","SKIP") for r in rows) else 1
if __name__=="__main__":raise SystemExit(main())
