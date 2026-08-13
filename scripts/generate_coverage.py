#!/usr/bin/env python3
"""Generate 64 feature bins and 48 same-workload interaction crosses."""

from __future__ import annotations
import csv, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main()->int:
    with (ROOT/"reports"/"scenario_manifest.csv").open() as handle:
        rows=list(csv.DictReader(handle))
    parsed=[]
    for row in rows:
        item=dict(row)
        for key in ("input","weights","bias","multiplier","shift","weight_zp","output_zp",
                    "accumulator","product","expected","result_classes"):
            item[key]=json.loads(row[key])
        parsed.append(item)

    bins=[]
    def add(name:str,predicate,source:str)->None:
        contributors=[str(r["name"]) for r in parsed if predicate(r)]
        bins.append((name,bool(contributors),";".join(contributors[:8]),source))
    add("family_directed",lambda r:r["family"]=="directed","manifest")
    add("family_random",lambda r:r["family"]=="random","manifest")
    for k in (4,8,16,32,64): add(f"k_{k}",lambda r,k=k:int(r["k"])==k,"command")
    for bank in (0,1): add(f"bank_{bank}",lambda r,bank=bank:int(r["bank"])==bank,"configuration")
    value_groups=("input","weights")
    predicates=(("zero",lambda v:v==0),("positive",lambda v:v>0),("negative",lambda v:v<0),
                ("int8_min",lambda v:v==-128),("int8_max",lambda v:v==127))
    for group in value_groups:
        for label,predicate in predicates:
            add(f"{group}_{label}",lambda r,g=group,p=predicate:any(p(v) for v in r[g]),group)
    for result in ("positive","negative","zero","sat_pos","sat_neg","relu_zero"):
        add(f"result_{result}",lambda r,result=result:result in r["result_classes"],"pytorch_result")
    add("relu_enabled",lambda r:int(r["relu_mask"])!=0,"configuration")
    add("relu_disabled",lambda r:int(r["relu_mask"])==0,"configuration")
    add("multiplier_positive",lambda r:any(v>0 for v in r["multiplier"]),"configuration")
    add("multiplier_negative",lambda r:any(v<0 for v in r["multiplier"]),"configuration")
    add("multiplier_unit",lambda r:any(v==1 for v in r["multiplier"]),"configuration")
    add("multiplier_nonunit",lambda r:any(abs(v)!=1 for v in r["multiplier"]),"configuration")
    add("shift_zero",lambda r:any(v==0 for v in r["shift"]),"configuration")
    add("shift_nonzero",lambda r:any(v>0 for v in r["shift"]),"configuration")
    add("shift_high",lambda r:any(v>=4 for v in r["shift"]),"configuration")
    for label,predicate in (("zero",lambda v:v==0),("positive",lambda v:v>0),("negative",lambda v:v<0)):
        add(f"bias_{label}",lambda r,p=predicate:any(p(v) for v in r["bias"]),"configuration")
        add(f"input_zp_{label}",lambda r,p=predicate:p(int(r["input_zp"])),"configuration")
        add(f"weight_zp_{label}",lambda r,p=predicate:any(p(v) for v in r["weight_zp"]),"configuration")
        add(f"output_zp_{label}",lambda r,p=predicate:any(p(v) for v in r["output_zp"]),"configuration")
    add("source_gap_none",lambda r:int(r["source_gap"])==0,"source_protocol")
    add("source_gap_present",lambda r:int(r["source_gap"])>0,"source_protocol")
    add("sink_stall_none",lambda r:int(r["sink_stall"])==0,"sink_protocol")
    add("sink_stall_low",lambda r:1<=int(r["sink_stall"])<=3,"sink_protocol")
    add("sink_stall_high",lambda r:int(r["sink_stall"])>=4,"sink_protocol")
    add("bank_swap_absent",lambda r:int(r["bank_swap"])==0,"bank_sequence")
    add("bank_swap_present",lambda r:int(r["bank_swap"])==1,"bank_sequence")
    add("accumulator_small",lambda r:any(abs(v)<=127 for v in r["accumulator"]),"pytorch_accumulator")
    add("accumulator_medium",lambda r:any(127<abs(v)<=32767 for v in r["accumulator"]),"pytorch_accumulator")
    add("accumulator_large",lambda r:any(abs(v)>32767 for v in r["accumulator"]),"pytorch_accumulator")
    add("product_positive",lambda r:any(v>0 for v in r["product"]),"pytorch_product")
    add("product_negative",lambda r:any(v<0 for v in r["product"]),"pytorch_product")
    add("round_exact",lambda r:any(s==0 or (abs(p)%(1<<s))==0 for p,s in zip(r["product"],r["shift"])),"requantization")
    add("round_nonzero_remainder",lambda r:any(s>0 and (abs(p)%(1<<s))!=0 for p,s in zip(r["product"],r["shift"])),"requantization")
    add("per_channel_quantization",lambda r:len(set(r["multiplier"]))>1 or len(set(r["weight_zp"]))>1,"configuration")
    add("short_command",lambda r:int(r["k"])<=8,"command")
    add("long_command",lambda r:int(r["k"])>=32,"command")
    add("all_output_channels_active",lambda r:all(v!="zero" for v in r["result_classes"]),"pytorch_result")
    assert len(bins)==64, len(bins)

    crosses=[]
    def cross(name:str,predicate)->None:
        contributors=[str(r["name"]) for r in parsed if predicate(r)]
        crosses.append((name,bool(contributors),";".join(contributors[:8])))
    for channel in range(4):
        for result in ("positive","negative","zero","sat_pos","sat_neg","relu_zero"):
            cross(f"channel_{channel}_x_{result}",lambda r,c=channel,v=result:r["result_classes"][c]==v)
    for bank in (0,1):
        for k in (4,8,16,32,64):
            cross(f"bank_{bank}_x_k_{k}",lambda r,b=bank,k=k:int(r["bank"])==b and int(r["k"])==k)
    for asymmetric in (0,1):
        for relu in (0,1):
            for saturated in (0,1):
                cross(f"asym_{asymmetric}_x_relu_{relu}_x_sat_{saturated}",lambda r,a=asymmetric,re=relu,s=saturated:
                      (int(int(r["input_zp"])!=0 or any(r["weight_zp"]) or any(r["output_zp"]))==a) and
                      (int(int(r["relu_mask"])!=0)==re) and
                      (int(any(v in ("sat_pos","sat_neg") for v in r["result_classes"]))==s))
    pressure=lambda r:0 if int(r["sink_stall"])==0 else 1 if int(r["sink_stall"])<=3 else 2
    for bucket in (0,1,2):
        for swap in (0,1):
            cross(f"pressure_{bucket}_x_bank_swap_{swap}",lambda r,b=bucket,s=swap:pressure(r)==b and int(r["bank_swap"])==s)
    assert len(crosses)==48

    with (ROOT/"reports"/"functional_coverage.csv").open("w",newline="") as handle:
        writer=csv.writer(handle,lineterminator="\n"); writer.writerow(["bin","status","first_contributors","evidence"])
        writer.writerows((n,"COVERED" if h else "MISSING",c,s) for n,h,c,s in bins)
    with (ROOT/"reports"/"cross_coverage.csv").open("w",newline="") as handle:
        writer=csv.writer(handle,lineterminator="\n"); writer.writerow(["cross_bin","status","contributing_tests"])
        writer.writerows((n,"COVERED" if h else "MISSING",c) for n,h,c in crosses)
    fh=sum(h for _,h,_,_ in bins); ch=sum(h for _,h,_ in crosses)
    (ROOT/"docs"/"coverage.md").write_text(
        f"# Coverage\n\n- Architectural feature coverage: **{fh} / {len(bins)}**\n"
        f"- Same-workload interaction crosses: **{ch} / {len(crosses)}**\n"
        "- Coverage is derived from PyTorch manifests that also execute against RTL.\n\n"
        "The cross model correlates channel result classes, K and parameter bank, asymmetric quantization, "
        "ReLU/saturation, output pressure, and bank swaps. These are project-defined metrics, not commercial signoff.\n")
    print(f"Functional coverage: {fh} / {len(bins)}; crosses: {ch} / {len(crosses)}")
    return 0 if fh==len(bins) and ch==len(crosses) else 1
if __name__=="__main__": raise SystemExit(main())
