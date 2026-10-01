#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, os, re, shutil, subprocess, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
csv.field_size_limit(20_000_000)
FORMAL=ROOT/"integration/protected_offload/formal"
REPORT=ROOT/"reports/protected_offload_formal.csv"
PROPERTIES=[
  ("request_response_accounting","response count never exceeds accepted count"),
  ("single_outstanding_bound","at most one DMA memory operation is active"),
  ("write_address_contract","AW is aligned and describes one 32-bit transfer"),
  ("byte_lane_mapping","32-bit writes select exactly one 64-bit data lane"),
  ("write_completion_order","DMA response follows accepted AW and W"),
  ("read_address_contract","AR is aligned and describes one 32-bit transfer"),
  ("read_completion_order","DMA response follows an accepted AR"),
  ("response_backpressure_stability","response payload remains stable while blocked"),
]
QUEUE_PROPERTIES=[
  ("queue_count_bounded","simultaneous and single-sided updates remain within depth"),
  ("simultaneous_push_pop_preserves_count","concurrent enqueue/dequeue has zero net occupancy change"),
]

def find_sby()->str|None:
  direct=shutil.which("sby")
  if direct:return direct
  roots=[Path(os.environ.get("OSS_CAD_SUITE","")),Path.home()/".cache/oss-cad-suite",
    Path.home()/"ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/oss-cad-suite/oss-cad-suite"]
  for root in roots:
    candidate=root/"bin/sby"
    if candidate.exists():return str(candidate)
  return None

def task_config(sby_file: Path, task: str) -> tuple[str, int]:
  """Read mode/depth from the actual task section rather than a report constant."""
  section = ""
  options = {}
  for raw in sby_file.read_text().splitlines():
    line = raw.strip()
    if line.startswith("[") and line.endswith("]"):
      section = line[1:-1]
      continue
    if section != "options" or ":" not in line:
      continue
    key, value = (part.strip() for part in line.split(":", 1))
    if key == task:
      option, _, option_value = value.partition(" ")
      if option and option_value:
        options[option] = option_value.strip()
  if options.get("mode") not in {"bmc", "prove", "cover", "live"} or not options.get("depth", "").isdigit():
    raise RuntimeError(f"missing {task} mode/depth in {sby_file}")
  return options["mode"], int(options["depth"])

def all_cover_goals_reached(source: Path, log: Path) -> tuple[bool, int, int]:
  source_lines = source.read_text().splitlines()
  goals = [line_no for line_no, line in enumerate(source_lines, 1)
           if re.search(r"\bcover(?:\s+property)?\s*\(", line)]
  log_text = log.read_text() if log.exists() else ""
  reached = {int(value) for value in re.findall(
      r"Reached cover statement .*?" + re.escape(source.name) + r":(\d+)\.", log_text)}
  return bool(goals) and set(goals) <= reached, len(set(goals) & reached), len(goals)

def main()->int:
  sby=find_sby();rows=[];start=time.monotonic()
  if not sby:
    _mode, adapter_depth = task_config(FORMAL/"protected_axi_adapter.sby", "prove")
    _cover_mode, adapter_cover_depth = task_config(FORMAL/"protected_axi_adapter.sby", "cover")
    for name,detail in PROPERTIES:rows.append({"property":name,"mode":"bounded_bmc_safety","depth":adapter_depth,"cover_depth":adapter_cover_depth,"status":"SKIP","cover":"SKIP","runtime_s":"0.00","detail":detail+"; sby unavailable"})
  else:
    env=os.environ.copy();env["PATH"]=f"{Path(sby).parent}:{env.get('PATH','')}"
    output_root=ROOT/"build/protected_offload/formal_tasks"
    output_root.mkdir(parents=True,exist_ok=True)
    def run_tasks(name):
      results=[]
      for task in ("prove","cover"):
        output=output_root/f"{name}_{task}"
        results.append(subprocess.run([sby,"-f","-d",str(output),f"{name}.sby",task],
          cwd=FORMAL,env=env,text=True,capture_output=True))
      return subprocess.CompletedProcess([name],max(result.returncode for result in results),
        "".join(result.stdout for result in results),"".join(result.stderr for result in results))
    run=run_tasks("protected_axi_adapter")
    queue_run=run_tasks("protected_queue_count")
    (ROOT/"build/protected_offload").mkdir(parents=True,exist_ok=True)
    (ROOT/"build/protected_offload/formal.log").write_text(run.stdout+run.stderr+queue_run.stdout+queue_run.stderr)
    prove=(output_root/"protected_axi_adapter_prove/status").read_text().startswith("PASS") if (output_root/"protected_axi_adapter_prove/status").exists() else False
    cover=(output_root/"protected_axi_adapter_cover/status").read_text().startswith("PASS") if (output_root/"protected_axi_adapter_cover/status").exists() else False
    # Wall time is host-load dependent; keep the checked-in normalized report deterministic.
    elapsed="NA"  # Measured, host-dependent task runtimes remain in the raw SBY logs.
    ax_mode, ax_depth = task_config(FORMAL/"protected_axi_adapter.sby", "prove")
    _ax_cover_mode, ax_cover_depth = task_config(FORMAL/"protected_axi_adapter.sby", "cover")
    ax_source = FORMAL/"protected_axi_adapter_formal.sv"
    ax_goals, ax_hit_count, ax_goal_count = all_cover_goals_reached(
        ax_source, output_root/"protected_axi_adapter_cover/logfile.txt")
    for name,detail in PROPERTIES:rows.append({"property":name,"mode":f"{ax_mode}_solver_safety","depth":ax_depth,"status":"PASS" if prove else "FAIL","cover":"REACHABLE" if cover and ax_goals else "FAIL","runtime_s":elapsed,"detail":detail+f"; adapter covers {ax_hit_count}/{ax_goal_count}"})
    queue_path=output_root/"protected_queue_count_prove/status";queue_cover_path=output_root/"protected_queue_count_cover/status"
    queue=queue_path.read_text().startswith("PASS") if queue_path.exists() else False
    queue_cover=queue_cover_path.read_text().startswith("PASS") if queue_cover_path.exists() else False
    queue_mode, queue_depth = task_config(FORMAL/"protected_queue_count.sby", "prove")
    _queue_cover_mode, queue_cover_depth = task_config(FORMAL/"protected_queue_count.sby", "cover")
    queue_goals, queue_hit_count, queue_goal_count = all_cover_goals_reached(
        FORMAL/"protected_queue_count_formal.sv", output_root/"protected_queue_count_cover/logfile.txt")
    for name,detail in QUEUE_PROPERTIES:rows.append({"property":name,"mode":f"{queue_mode}_solver_safety","depth":queue_depth,"status":"PASS" if queue else "FAIL","cover":"REACHABLE" if queue_cover and queue_goals else "FAIL","runtime_s":elapsed,"detail":detail+f"; queue covers {queue_hit_count}/{queue_goal_count}"})
    # The integrated crossover harness is intentionally reported separately
    # from leaf AXI/queue proofs. Its covers are parsed from the fresh SBY task
    # outputs, not inferred from compilation or the older bounded harnesses.
    crossover_run=run_tasks("protected_crossover_control")
    lifetime_results={}
    for task in ("prove","cover"):
      output=ROOT/"build/protected_offload"/f"lifetime_reset_{task}"
      shutil.rmtree(output, ignore_errors=True)
      result=subprocess.run([sby,"-f","-d",str(output),"protected_lifetime_reset.sby",task],cwd=FORMAL,env=env,text=True,capture_output=True)
      status=output/"status"
      lifetime_results[task]=result.returncode==0 and status.exists() and status.read_text().split()[0]=="PASS"
      with (ROOT/"build/protected_offload/formal.log").open("a") as fh:
        fh.write(result.stdout+result.stderr)
    lifetime_closed=all(lifetime_results.values())
    drain_run=run_tasks("protected_completion_drain")
    drain_prove_path=output_root/"protected_completion_drain_prove/status"
    drain_prove=drain_prove_path.exists() and drain_prove_path.read_text().startswith("PASS")
    drain_cover_path=output_root/"protected_completion_drain_cover/status"
    drain_cover_status=drain_cover_path.exists() and drain_cover_path.read_text().startswith("PASS")
    drain_cover_goals, drain_cover_hits, drain_cover_total = all_cover_goals_reached(
        FORMAL/"protected_completion_drain_formal.sv", output_root/"protected_completion_drain_cover/logfile.txt")
    drain_cover=drain_cover_status and drain_cover_goals
    prove_path=output_root/"protected_crossover_control_prove/status"
    cover_path=output_root/"protected_crossover_control_cover/status"
    xprove=prove_path.exists() and prove_path.read_text().startswith("PASS")
    xcover=cover_path.exists() and cover_path.read_text().startswith("PASS")
    cover_log_path=output_root/"protected_crossover_control_cover/logfile.txt"
    cover_log=cover_log_path.read_text() if cover_log_path.exists() else ""
    with (ROOT/"build/protected_offload/formal.log").open("a") as fh:
      fh.write(drain_run.stdout+drain_run.stderr)
    cover_source=(FORMAL/"protected_crossover_control_formal.sv").read_text().splitlines()
    def cover_reached(statement:str)->bool:
      lines=[i+1 for i,line in enumerate(cover_source) if statement in line]
      return bool(lines) and any(f"protected_crossover_control_formal.sv:{line}." in log_line and
        "cover statement" in log_line and "Unreached" not in log_line
        for line in lines for log_line in cover_log.splitlines())
    cross_path=ROOT/"reports/compute_crossover_cross_coverage.csv"
    completion_trace_witness=False
    if cross_path.exists():
      with cross_path.open(newline="") as fh:
        completion_trace_witness=any(row.get("cross_family")=="output_commit_x_completion_visibility" and
          row.get("status")=="PASS" and row.get("first_witness_event_ids") for row in csv.DictReader(fh))
    reset_path=ROOT/"reports/protected_reset_context.csv"
    reset_evidence=False
    if reset_path.exists():
      with reset_path.open(newline="") as fh:
        reset_rows=list(csv.DictReader(fh))
      reset_evidence=len(reset_rows)>=5 and all(row.get("status")=="PASS" and
        row.get("phase_reached")=="true" and int(row.get("epochs","0"))>=2 for row in reset_rows)
    xrows=[
      ("tag_lifetime","bounded_solver_safety","implemented DMA; two-entry queues and two tags; duplicate acceptance forbidden until completion consumption; legal one-cycle responders; safety depth 48, six shared covers within 64",lifetime_closed),
      ("configuration_reference_lifetime","bounded_solver_safety","busy/queued work retains a bank reference",xprove and cover_reached("cover(bank_referenced != 0);")),
      ("completion_after_write_drain","bounded_solver_safety_plus_rtl_trace",f"actual SBY BMC proof plus all completion-drain cover goals {drain_cover_hits}/{drain_cover_total} and a strict-replay committed-write witness",xprove and drain_prove and drain_cover and completion_trace_witness),
      ("invalidation_submission_arbitration","bounded_solver_safety","the real APB TLB-control RTL blocks DMA submits while invalidation is pending and pulses only after translation/service/queue drain",xprove and cover_reached("cover(inv_dut.pending && block_submissions && !submit_ready);") and cover_reached("cover(inv_valid);")),
      ("irq_set_dominates_ack","bounded_solver_safety","simultaneous event and W1C acknowledgement retains the event",xprove and cover_reached("cover((chiplet_dma_event || accelerator_event || device_fault_event) &&")),
      ("reset_cancels_owned_work","bounded_solver_safety","implemented DMA reset with arbitrary sampled reset epochs; all request/response ownership cleared; covers owned reset and subsequent fresh completion; safety depth 48, cover depth 64; analog reset timing not modeled",lifetime_closed),
    ]
    for name,mode,detail,closed in xrows:
      if name in {"tag_lifetime","reset_cancels_owned_work"}:
        status="PASS" if lifetime_results["prove"] else "FAIL"
        cover="REACHABLE" if lifetime_results["cover"] else "NOT_REACHED"
      elif name=="completion_after_write_drain":
        status="PASS" if closed else "FAIL"
        cover="REACHABLE" if drain_cover else "NOT_REACHED"
      elif name=="invalidation_submission_arbitration":
        status="PASS" if closed else "FAIL"
        cover="REACHABLE" if closed else "NOT_REACHED"
      else:
        status="PASS" if closed else ("PARTIAL" if xprove and name=="completion_after_write_drain" else "FAIL")
        cover="REACHABLE" if closed else "NOT_REACHED" if name=="completion_after_write_drain" else "FAIL"
      config_name=("protected_lifetime_reset.sby" if name in {"tag_lifetime","reset_cancels_owned_work"} else
                   "protected_completion_drain.sby" if name=="completion_after_write_drain" else
                   "protected_crossover_control.sby")
      _actual_mode, actual_depth=task_config(FORMAL/config_name,"prove")
      _actual_cover_mode, actual_cover_depth=task_config(FORMAL/config_name,"cover")
      rows.append({"property":name,"mode":mode,"depth":actual_depth,
                   "status":status,"cover":cover,"cover_depth":actual_cover_depth,"runtime_s":elapsed,"detail":detail})
    (ROOT/"build/protected_offload").mkdir(parents=True,exist_ok=True)
    with (ROOT/"build/protected_offload/formal.log").open("a") as fh:
      fh.write(crossover_run.stdout+crossover_run.stderr)
  REPORT.parent.mkdir(exist_ok=True)
  fingerprint=hashlib.sha256()
  for source in sorted(list(FORMAL.glob("*.sv"))+list(FORMAL.glob("*.sby"))+list((ROOT/"integration/protected_offload/rtl").glob("*.sv"))):
    fingerprint.update(str(source.relative_to(ROOT)).encode());fingerprint.update(source.read_bytes())
  for row in rows:
    row["source_harness_sha256"]=fingerprint.hexdigest()
    if "cover_depth" not in row:
      if row["property"] in {name for name,_ in PROPERTIES}:
        row["cover_depth"] = ax_cover_depth
      elif row["property"] in {name for name,_ in QUEUE_PROPERTIES}:
        row["cover_depth"] = queue_cover_depth
      else:
        row["cover_depth"] = row["depth"]
  with REPORT.open("w",newline="") as h:
    w=csv.DictWriter(h,fieldnames=rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(rows)
  passed=sum(r["status"]=="PASS" for r in rows);skipped=sum(r["status"]=="SKIP" for r in rows)
  crossover_rows=[r for r in rows if r["property"] in {"tag_lifetime","configuration_reference_lifetime","completion_after_write_drain","invalidation_submission_arbitration","irq_set_dominates_ack","reset_cancels_owned_work"}]
  crossover_pass=sum(r["status"]=="PASS" and r["cover"] in ("REACHABLE","RTL_TEST_REACHED","RTL_TRACE_REACHED") for r in crossover_rows)
  print(f"PROTECTED_OFFLOAD_FORMAL|status={'PASS' if passed==len(rows) else 'SKIP' if skipped==len(rows) else 'PARTIAL'}|properties={passed}/{len(rows)}|covers={sum(r['cover'] in ('REACHABLE','RTL_TRACE_REACHED') for r in rows)}/{len(rows)}|crossover={crossover_pass}/{len(crossover_rows)}")
  return 0 if passed==len(rows) and all(r["cover"]=="REACHABLE" for r in rows) else 1
if __name__=="__main__":raise SystemExit(main())
