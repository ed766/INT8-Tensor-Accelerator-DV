#!/usr/bin/env python3
from __future__ import annotations
import csv, re, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REQUIRED_COVERAGE = [
 "write_order_simultaneous", "write_order_aw_first", "write_order_w_first",
 "axis_output_backpressure", "counter_readback", "partial_strobe_slverr",
 "unmapped_write_slverr", "unaligned_read_slverr", "sticky_error_w1c",
 "decoder_config", "decoder_command", "decoder_activation", "decoder_stall",
 "decoder_expectation", "decoder_malformed", "decoder_end",
 "portable_end_to_end_replay",
]
TESTS={
 "axi_wrapper":(["rtl/int8_tensor_accel.sv","rtl/int8_accel_health_monitor.sv","rtl/int8_accel_axi_wrapper.sv","sim/tb_axi_wrapper.sv"],"tb_axi_wrapper","AXI_CHECK"),
 "record_decoder":(["rtl/int8_portable_record_decoder.sv","sim/tb_record_decoder.sv"],"tb_record_decoder","DECODER_CHECK"),
 "portable_accel_top":(["rtl/int8_tensor_accel.sv","rtl/int8_accel_health_monitor.sv","rtl/int8_portable_record_decoder.sv","rtl/int8_portable_accel_top.sv","sim/tb_portable_accel_top.sv"],"tb_portable_accel_top","PORTABLE_TOP_CHECK"),
}
def main()->int:
 rows=[]; observed=set()
 for name,(sources,top,prefix) in TESTS.items():
  build=ROOT/"build"/name
  if build.exists():shutil.rmtree(build)
  build.mkdir(parents=True,exist_ok=True)
  cmd=["verilator","--binary","--timing","--assert","-Wall","-Wno-fatal","-Wno-SYNCASYNCNET","-Wno-UNUSEDSIGNAL","-Wno-WIDTHEXPAND","-Wno-WIDTHTRUNC","--top-module",top,"--Mdir",str(build/"obj"),*sources]
  comp=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True);(build/"compile.log").write_text(comp.stdout+comp.stderr)
  if comp.returncode:print(comp.stderr);rows.append({"test":name,"status":"FAIL","checks":"0"});continue
  run_args=[str(build/"obj"/f"V{top}")]
  if name=="portable_accel_top":
   import json
   metadata=json.loads((ROOT/"portable"/"portable_vectors.json").read_text())
   run_args += [f"+VECTOR_FILE={ROOT/'portable'/'portable_vectors.mem'}",f"+VECTOR_COUNT={metadata['records']}"]
  run=subprocess.run(run_args,cwd=ROOT,text=True,capture_output=True,timeout=120);log=run.stdout+run.stderr;(build/"simulation.log").write_text(log)
  observed.update(re.findall(r"AXI_COVER\|point=([^\n\r]+)",log))
  checks=len(re.findall(rf"{prefix}\|[^\n]*status=PASS",log));status="PASS" if run.returncode==0 and checks else "FAIL";rows.append({"test":name,"status":status,"checks":str(checks)})
 with (ROOT/"reports"/"axi_stream_integration_summary.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(rows)
 coverage_rows=[{"point":point,"status":"COVERED" if point in observed else "MISSING"} for point in REQUIRED_COVERAGE]
 with (ROOT/"reports"/"axi_stream_integration_coverage.csv").open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=coverage_rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(coverage_rows)
 passed=all(r["status"]=="PASS" for r in rows) and all(r["status"]=="COVERED" for r in coverage_rows)
 print(f"AXI_INTEGRATION|status={'PASS' if passed else 'FAIL'}|tests={sum(r['status']=='PASS' for r in rows)}/{len(rows)}|checks={sum(int(r['checks']) for r in rows)}|coverage={sum(r['status']=='COVERED' for r in coverage_rows)}/{len(coverage_rows)}")
 return 0 if passed else 1
if __name__=="__main__":raise SystemExit(main())
