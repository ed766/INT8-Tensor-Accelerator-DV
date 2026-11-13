#!/usr/bin/env python3
"""Independent-peer module tests and separate native coverage, not SoC closure."""
import csv
import hashlib
import subprocess
from pathlib import Path
from run_stateful_crossover import ROOT

BASE="integration/protected_offload/"
CASES=(
    ("dma_peers","tb_dma_peer_holes",["rtl/protected_queue_count_next.sv","rtl/protected_offload_dma.sv","sim/tb_dma_peer_holes.sv"],"DMA_PEER_HOLES_PASS"),
    ("held_results","tb_control_peer_holes",["rtl/protected_chiplet_apb_bridge.sv","vendor/rv32/rv32_muldiv.sv","sim/tb_control_peer_holes.sv"],"PEER_HOLES_PASS"),
    ("dma_response","tb_protected_dma_axi_adapter",["rtl/protected_dma_axi_adapter.sv","sim/tb_protected_dma_axi_adapter.sv"],"PROTECTED_AXI_ADAPTER_PASS"),
    ("host_select","tb_protected_host_axi_bridge",["rtl/protected_dma_axi_adapter.sv","rtl/protected_host_axi_bridge.sv","sim/tb_protected_host_axi_bridge.sv"],"PROTECTED_HOST_BRIDGE|status=PASS"),
)

def native_points(path):
    points={}
    for line in path.read_text().splitlines():
        if not line.startswith("C '"):continue
        body=line[3:line.rfind("'")];count=int(line[line.rfind("'")+1:].strip())
        meta=dict(field.split("\x02",1) for field in body.split("\x01") if "\x02" in field)
        kind=meta.get("page","").split("/",1)[0].removeprefix("v_")
        source=meta.get("f","")
        if kind not in ("line","branch") or not source or "/sim/" in source:continue
        source=str(Path(source).relative_to(ROOT)) if Path(source).is_absolute() else source
        key=(source,meta.get("l",""),kind,meta.get("o","") if kind=="branch" else "",meta.get("n","") if kind=="branch" else "")
        points[key]=max(points.get(key,0),count)
    return points

def main():
    # A failed rebuild must not leave the previous successful run as current evidence.
    for name in ("compute_peer_holes.csv","compute_peer_holes_coverage_points.csv","compute_peer_hole_closure.csv","compute_peer_holes_module_coverage.csv"):
        (ROOT/"reports"/name).unlink(missing_ok=True)
    version=subprocess.check_output(["verilator","--version"],text=True).strip()
    if "5.049" not in version:raise SystemExit("peer-hole native coverage requires pinned Verilator 5.049")
    build=ROOT/"build/protected_offload/peer_holes";build.mkdir(parents=True,exist_ok=True)
    results=[];details=[]
    for name,top,files,marker in CASES:
        sources=[ROOT/(BASE+p) for p in files]
        source_hash=hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest()
        for instrumented in (False,True):
            folder=build/(name+("_coverage" if instrumented else "_asserted"));folder.mkdir(exist_ok=True)
            cpp=folder/"main.cpp"
            cpp.write_text(f'#include "V{top}.h"\n#include "verilated.h"\n#include "verilated_cov.h"\nint main(int argc,char**argv){{VerilatedContext c;c.commandArgs(argc,argv);V{top} d(&c);while(!c.gotFinish()){{d.eval();c.timeInc(1);}}d.final();'+('VerilatedCov::write("coverage.dat");' if instrumented else '')+'return 0;}\n')
            cmd=["verilator","--cc","--exe","--build","--timing","--assert","-Wall","-Wno-fatal","--top-module",top,"--Mdir",str(folder)]
            if instrumented:cmd += ["--coverage","-DSYNTHESIS"]
            compilation=subprocess.run(cmd+list(map(str,sources))+[str(cpp)],cwd=ROOT,text=True,capture_output=True)
            (folder/"compile.log").write_text(compilation.stdout+compilation.stderr)
            if compilation.returncode:raise SystemExit(f"peer-hole compile failed: {name}; inspect generated compile.log")
            seeds=(11,29,97,211) if name=="dma_peers" else (11,)
            for seed in seeds:
                db=folder/"coverage.dat";db.unlink(missing_ok=True)
                run=subprocess.run([str(folder/f"V{top}"),f"+SEED={seed}"],cwd=folder,text=True,capture_output=True,timeout=60)
                log=folder/f"seed_{seed}.log";log.write_text(run.stdout+run.stderr)
                witnesses=[l for l in run.stdout.splitlines() if l.startswith("HOLE_EVT|")]
                passed=run.returncode==0 and marker in run.stdout and bool(witnesses)
                results.append(dict(test=name,seed=seed,lane="native_coverage" if instrumented else "asserted",status="PASS" if passed else "FAIL",witness_events=len(witnesses),source_sha256=source_hash,tool=version,log=str(log.relative_to(ROOT)),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
                if not passed:raise SystemExit(f"peer-hole test failed: {name}: {run.stdout[-2000:]} {run.stderr[-1000:]}")
                if instrumented:
                    for (source,line,kind,option,point),hits in native_points(db).items():
                        details.append(dict(test=name,seed=seed,rtl_file=source,line=line,point_type=kind,option=option,point=point,hit_count=hits))
    for filename,rows in (("compute_peer_holes.csv",results),("compute_peer_holes_coverage_points.csv",details)):
        with (ROOT/"reports"/filename).open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    union={}
    for p in details:
        key=(p['rtl_file'],p['line'],p['point_type'],p['option'],p['point'])
        union[key]=max(union.get(key,0),p['hit_count'])
    module_rows=[]
    for source in sorted({p['rtl_file'] for p in details}):
        row=dict(rtl_file=source,evidence_scope="independent_peer_component_source_union")
        for kind in ('line','branch'):
            selected=[count for key,count in union.items() if key[0]==source and key[2]==kind]
            row[kind+'_hit']=sum(c>0 for c in selected);row[kind+'_total']=len(selected)
            row[kind+'_percent']=f"{100*row[kind+'_hit']/len(selected):.2f}" if selected else "NA"
        module_rows.append(row)
    with (ROOT/'reports/compute_peer_holes_module_coverage.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=module_rows[0],lineterminator='\n');writer.writeheader();writer.writerows(module_rows)
    holes=list(csv.DictReader((ROOT/"reports/compute_stateful_coverage_hole_review.csv").open()))
    closure=[]
    for hole in holes:
        contributing=[p for p in details if p["rtl_file"]==hole["rtl_file"] and p["line"]==hole["line"] and p["point_type"]==hole["point_type"] and p["option"]==hole["option"] and p["hit_count"]>0]
        closure.append(dict(rtl_file=hole["rtl_file"],line=hole["line"],point_type=hole["point_type"],option=hole["option"],
                            status="COMPONENT_COVERED" if contributing else "NOT_COVERED_IN_COMPONENT_LANE",
                            contributing_tests=";".join(dict.fromkeys(p["test"] for p in contributing)),evidence_scope="independent_peer_module_not_firmware_integration"))
    with (ROOT/"reports/compute_peer_hole_closure.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=closure[0],lineterminator="\n");writer.writeheader();writer.writerows(closure)
    lines=["# Independent-Peer Coverage Tests","","Tests use public module interfaces with independently stalled peers. They do not force internal states, patch imported RTL or inflate firmware-integration percentages.","",
           f"Asserted and native runs: {sum(r['status']=='PASS' for r in results)}/{len(results)}. DMA tests use four deterministic stall seeds, 19 jobs each (13 success / 6 wrong-tag faults), including first/middle/last-vector errors with exact committed-prefix and fault-address checking, followed by clean recovery. Held-result tests execute all eight M opcodes, division corner cases and reset with an unconsumed result.","",
           "## Separate Component Coverage", "", "Native source-point union across these component benches only. Not baseline/integration coverage, and not independent closure for every instance/parameter setting.","",
           "| Module | Raw line | Raw branch |","|---|---:|---:|"]
    for row in module_rows:lines.append(f"| `{Path(row['rtl_file']).name}` | {row['line_hit']}/{row['line_total']} ({row['line_percent']}%) | {row['branch_hit']}/{row['branch_total']} ({row['branch_percent']}%) |")
    lines += ["","## Prior-Hole Witnesses","",
           "| Prior hole | Component test | Status |","|---|---|---|"]
    for row in closure:lines.append(f"| `{Path(row['rtl_file']).name}:{row['line']}` {row['option']} | {row['contributing_tests'] or 'None'} | {row['status']} |")
    lines += ["","[Run provenance](../reports/compute_peer_holes.csv), [native points](../reports/compute_peer_holes_coverage_points.csv), [hole mapping](../reports/compute_peer_hole_closure.csv). Wrong-tag tests model a faulty accelerator peer and require error containment without a destination write; they are not normal numerical-model runs. Defensive defaults and the magnitude helper's unreachable caller alternative remain raw holes.","",
              "The host test checks actual AW/AR handshake counts and a held-select, PENABLE-low bubble after completion. Its old eight-byte address-rounding expectation was corrected: a four-byte AXI transfer on a 64-bit bus retains address bit 2 and selects the upper data lanes. No DUT change was needed."]
    (ROOT/"docs/compute_peer_holes.md").write_text("\n".join(lines)+"\n")
    print(f"Peer holes: {len(results)}/{len(results)} PASS; {sum(r['status']=='COMPONENT_COVERED' for r in closure)} prior holes covered separately")
    return 0

if __name__=="__main__":raise SystemExit(main())
