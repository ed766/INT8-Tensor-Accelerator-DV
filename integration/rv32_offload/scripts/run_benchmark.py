#!/usr/bin/env python3
"""Build, execute, and report the RV32I versus INT8 benchmark lane."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3];PYTHON=Path(sys.executable)
BUILD=ROOT/"build/rv32_benchmark";REPORTS=ROOT/"reports"
GEN=ROOT/"integration/rv32_offload/scripts/generate_benchmark.py";BUILDER=ROOT/"integration/rv32_offload/scripts/build_firmware.py"
SOURCES=["integration/rv32_offload/rv32/rv32_core.sv","integration/rv32_offload/rv32/rv32_rom_feeder.sv","rtl/int8_tensor_accel.sv","rtl/int8_accel_health_monitor.sv","rtl/int8_accel_axi_wrapper.sv","integration/rv32_offload/rtl/apb_to_axil_bridge.sv","integration/rv32_offload/rtl/apb_axis_mailbox.sv","integration/rv32_offload/rtl/rv32_int8_benchmark_top.sv","integration/rv32_offload/sim/tb_rv32_int8_benchmark.sv"]
RESULT=re.compile(r"BENCH_RESULT\|(?P<fields>.*)")

def compile_sim(name="nominal",define=""):
    obj=BUILD/f"obj_{name}";exe=obj/"Vtb_rv32_int8_benchmark"
    newest=max((ROOT/s).stat().st_mtime for s in SOURCES)
    if exe.exists() and exe.stat().st_mtime>=newest:return exe
    obj.mkdir(parents=True,exist_ok=True)
    cmd=["verilator","--binary","--timing","--assert","--trace-fst","-Wno-fatal","-Wno-SYNCASYNCNET","-Wno-UNUSEDSIGNAL","-Wno-PINCONNECTEMPTY","-Wno-TIMESCALEMOD","-Wno-VARHIDDEN","-Wno-BLKSEQ","--top-module","tb_rv32_int8_benchmark","--Mdir",str(obj)]
    if define:cmd.append("-D"+define)
    subprocess.run(cmd+SOURCES,cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    return exe

def parse(output:str):
    match=RESULT.search(output)
    if not match:return {}
    return {key:int(value,16) if key=="result" else int(value) for key,value in (item.split("=",1) for item in match.group("fields").split("|"))}

def run_case(k,batch,mode,pattern="random",seed=1,stall=0,mutation="",waveform=False):
    name=f"k{k}_b{batch}_{mode}_{pattern}_s{seed}_p{stall}";out=BUILD/"cases"/name;out.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(PYTHON),str(GEN),"--k",str(k),"--batch",str(batch),"--mode",mode,"--pattern",pattern,"--seed",str(seed),"--output-dir",str(out)],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    c_mut=mutation if mutation in ("scalar_round","corrupt_result") else ""
    subprocess.run([str(PYTHON),str(BUILDER),"--scenario-dir",str(out),"--mutation",c_mut],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    defines={"drop_chunk":"RV32_BENCH_MUT_DROP_CHUNK","dup_command":"RV32_BENCH_MUT_DUP_COMMAND","freeze_latency":"RV32_BENCH_MUT_FREEZE_LATENCY"}
    exe=compile_sim(mutation or "nominal",defines.get(mutation,""))
    command=[str(exe),f"+FIRMWARE_HEX={out/'benchmark.hex'}",f"+DATA_HEX={out/'benchmark.data.hex'}",f"+EXPECT_K={k}",f"+EXPECT_BATCH={batch}",f"+OUT_STALL_PERCENT={stall}"]
    if waveform:command.append(f"+WAVE_FILE={BUILD/'rv32_accel_benchmark.fst'}")
    proc=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    values=parse(proc.stdout+proc.stderr);passed=proc.returncode==0 and bool(values)
    row={"name":name,"k":k,"batch":batch,"mode":mode,"pattern":pattern,"seed":seed,"stall_percent":stall,"status":"PASS" if passed else "FAIL","failure_bucket":"" if passed else ("timeout_or_assertion" if not values else "numerical_or_accounting"),**values}
    if passed:
      overhead=values["counter_overhead"];instrumentation_writes=6*batch+(2 if mode=="cold" else 0)
      scalar=values["scalar_cycles"];accel=max(1,values["accel_cycles"]-overhead*instrumentation_writes)
      row.update({"scalar_adjusted_cycles":scalar,"accel_adjusted_cycles":accel,
        "configuration_adjusted_cycles":max(0,values["configuration_cycles"]-overhead),
        "stream_adjusted_cycles":max(0,values["stream_cycles"]-overhead*batch),
        "poll_adjusted_cycles":max(0,values["poll_cycles"]-overhead*batch),
        "output_read_adjusted_cycles":max(0,values["output_read_cycles"]-overhead*batch),
        "end_to_end_speedup":f"{scalar/accel:.4f}","compute_speedup":f"{scalar/max(1,values['active_cycles']):.4f}","throughput_outputs_per_cycle":f"{batch/max(1,accel):.8f}"})
    (out/"run.log").write_text(proc.stdout+proc.stderr)
    return row

def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for row in rows:
      for key in row:
        if key not in fields:fields.append(key)
    with path.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(rows)

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("lane",choices=("smoke","sweep","correctness","backpressure","mutations","all"));ap.add_argument("--waveform",action="store_true");args=ap.parse_args();REPORTS.mkdir(exist_ok=True)
    failures=0
    if args.lane=="smoke":
      row=run_case(4,1,"warm",waveform=args.waveform);write_csv(REPORTS/"rv32_accel_smoke.csv",[row]);failures+=row["status"]!="PASS"
    if args.lane in ("sweep","all"):
      rows=[run_case(k,b,m,seed=0x8000+k*100+b) for k in (4,8,16,32,64) for b in (1,4,16,64) for m in ("cold","warm")]
      write_csv(REPORTS/"rv32_accel_benchmark.csv",rows);failures+=sum(r["status"]!="PASS" for r in rows)
    if args.lane in ("correctness","all"):
      rows=[run_case(k,1,"warm",p,seed=0x9000+k) for k in (4,8,16,32,64) for p in ("random","zeros","sat_pos","sat_neg","alternating")]
      write_csv(REPORTS/"rv32_accel_correctness.csv",rows);failures+=sum(r["status"]!="PASS" for r in rows)
    if args.lane in ("backpressure","all"):
      rows=[run_case(k,16,"warm",seed=0xa000+k,stall=s) for k in (4,8,16,32,64) for s in (0,25,75)]
      write_csv(REPORTS/"rv32_accel_backpressure.csv",rows);failures+=sum(r["status"]!="PASS" for r in rows)
    if args.lane in ("mutations","all"):
      rows=[]
      for mutation in ("drop_chunk","dup_command","corrupt_result","scalar_round","freeze_latency"):
        pattern="zeros" if mutation=="scalar_round" else "random"
        row=run_case(4,1,"warm",pattern=pattern,mutation=mutation);detected=row["status"]=="FAIL";rows.append({"mutation":mutation,"expected":"FAIL","observed":row["status"],"status":"PASS" if detected else "FAIL","bucket":row["failure_bucket"]});failures+=not detected
      write_csv(REPORTS/"rv32_accel_mutations.csv",rows)
    print(f"RV32 accelerator {args.lane}: {'PASS' if failures==0 else 'FAIL'} ({failures} failures)")
    return 1 if failures else 0
if __name__=="__main__":raise SystemExit(main())
