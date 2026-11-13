#!/usr/bin/env python3
"""Real compiled RTL mutations qualified by named diagnostic and live control."""
import csv
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from run_stateful_crossover import ROOT
from check_crossover_trace import events, check_architecture

CASES = (
    ("stateful_reset_m_dma_middle", "RV32_BUG_M_STALE_RESET", "stale_muldiv_state_survived_reset_epoch"),
    ("stateful_both_bank_queue", "PROTECTED_MUT_BANK_REFERENCE_BYPASS", "a_referenced_generation_write_rejected"),
    ("stateful_m_corners_live", "RV32_BUG_M_HIGH_PRODUCT", "iss_high_product"),
    ("stateful_m_corners_live", "RV32_BUG_M_DIV_ROUND", "iss_signed_quotient"),
    ("stateful_m_corners_live", "RV32_BUG_M_REM_SIGN", "iss_remainder_sign"),
    ("stateful_m_corners_live", "RV32_BUG_M_DIV_ZERO", "iss_divide_zero"),
    ("stateful_m_corners_live", "RV32_BUG_M_DIV_OVERFLOW", "iss_signed_overflow"),
)

def arithmetic_witness(parsed, errors, bucket):
    """Require an ISS result mismatch on the intended, actually retired operand class."""
    for event in parsed:
        insn=int(event.get("insn","0"),16)
        if event.get("kind")!="RETIRE" or insn & 0xfe00007f != 0x02000033:
            continue
        op=(insn>>12)&7; lhs=int(event["rs1_data"],16);rhs=int(event["rs2_data"],16)
        activated={"iss_high_product":op in (1,2),
                   "iss_signed_quotient":op==4 and bool(lhs>>31) and rhs not in (0,0xffffffff),
                   "iss_remainder_sign":op==6 and bool(lhs>>31) and rhs not in (0,0xffffffff),
                   "iss_divide_zero":op in (4,5,6,7) and rhs==0,
                   "iss_signed_overflow":op in (4,6) and lhs==0x80000000 and rhs==0xffffffff}.get(bucket,False)
        prefix=f"order {event['retire_order']}: rd value "
        if activated and any(error.startswith(prefix) for error in errors):
            return event["eid"]
    return ""

def main():
    rows=[]
    script=Path(__file__).with_name("run_shared_firmware.py")
    for scenario,macro,expected in CASES:
        env=dict(os.environ, PROTECTED_STATEFUL=scenario, PROTECTED_ARTIFACT_PREFIX="stateful_mutations")
        control=subprocess.run([sys.executable,str(script),"--model"],cwd=ROOT,env=env,capture_output=True,text=True)
        report=ROOT/f"reports/compute_stateful_mutation_{macro.lower()}.csv"
        report.unlink(missing_ok=True)
        mutant=subprocess.run([sys.executable,str(script),"--define",macro],cwd=ROOT,env=env,capture_output=True,text=True)
        evidence=list(csv.DictReader(report.open())) if report.is_file() else []
        row=evidence[0] if len(evidence)==1 else {}
        trace=ROOT/row.get("trace","MISSING")
        compiled="CalledProcessError" not in mutant.stdout+mutant.stderr and bool(row)
        active=(row.get("mutation_qualification")==expected and row.get("mutation_exit_code") not in ("", "0")
                and trace.is_file() and hashlib.sha256(trace.read_bytes()).hexdigest()==row.get("trace_sha256"))
        witness=""
        if expected.startswith("iss_") and trace.is_file():
            parsed=events(trace)
            witness=arithmetic_witness(parsed,check_architecture(parsed,trace),expected)
            active=bool(witness) and row.get("mutation_exit_code") not in ("", "0") and hashlib.sha256(trace.read_bytes()).hexdigest()==row.get("trace_sha256")
        passed=control.returncode==0 and compiled and active
        rows.append(dict(mutation=macro,scenario=scenario,status="DETECTED" if passed else "MISSED",
                         nominal_control="PASS" if control.returncode==0 else "FAIL",compile_status="PASS" if compiled else "FAIL",
                         activating_event_and_diagnostic=str(active).lower(),expected_failure=expected,
                         detection=expected if active else row.get("mutation_qualification","MISSING"),
                         activating_event_id=witness,trace=row.get("trace","")))
    with (ROOT/"reports/compute_stateful_mutations.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=rows[0],lineterminator="\n");writer.writeheader();writer.writerows(rows)
    print(f"Stateful RTL mutations: {sum(r['status']=='DETECTED' for r in rows)}/{len(rows)}")
    return int(any(r["status"]!="DETECTED" for r in rows))

if __name__=="__main__":raise SystemExit(main())
