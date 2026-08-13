#!/usr/bin/env python3
"""Summarize measured latency, active MAC rate, and double-buffer overlap."""
from __future__ import annotations
import csv, math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def percentile(values:list[int],p:float)->int:
    ordered=sorted(values);return ordered[max(0,math.ceil(p*len(ordered))-1)]
def main()->int:
    with (ROOT/"reports"/"rtl_vs_pytorch_summary.csv").open() as h: results=list(csv.DictReader(h))
    with (ROOT/"reports"/"scenario_manifest.csv").open() as h: manifests={r["name"]:r for r in csv.DictReader(h)}
    groups=defaultdict(list)
    for row in results:
        m=manifests[row["name"]];stall=int(m["sink_stall"]);bucket="0" if stall==0 else "1-3" if stall<=3 else "4-7"
        groups[(int(m["k"]),bucket)].append(int(row["latency"]))
    summary=[]
    for (k,bucket),values in sorted(groups.items()):
        chunks=k//4; config_writes=4*(k+3); sequential=config_writes+chunks+1
        overlapped=max(config_writes,chunks+1)
        summary.append({"k":k,"output_stall_cycles":bucket,"requests":len(values),
            "mean_latency_cycles":f"{sum(values)/len(values):.2f}","p50_cycles":percentile(values,.5),
            "p95_cycles":percentile(values,.95),"max_cycles":max(values),"active_macs_per_cycle":16,
            "macs_per_command":4*k,"sequential_config_compute_cycles":sequential,
            "double_buffered_overlap_cycles":overlapped,"overlap_savings_percent":f"{100*(sequential-overlapped)/sequential:.2f}"})
    with (ROOT/"reports"/"performance_summary.csv").open("w",newline="") as h:
        w=csv.DictWriter(h,fieldnames=list(summary[0]),lineterminator="\n");w.writeheader();w.writerows(summary)
    lines=["# Performance Characterization","","Behavioral Verilator measurements from command acceptance through result acceptance.","",
           "| K | Output stall | Requests | Mean | p50 | p95 | Max | MACs/command | Double-buffer overlap saving |",
           "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in summary:lines.append(f"| {r['k']} | {r['output_stall_cycles']} | {r['requests']} | {r['mean_latency_cycles']} | {r['p50_cycles']} | {r['p95_cycles']} | {r['max_cycles']} | {r['macs_per_command']} | {r['overlap_savings_percent']}% |")
    lines += ["","The datapath performs 16 signed MACs per active input-chunk cycle. Parameter bank B may be loaded while bank A executes, so configuration and compute can overlap. The overlap column is a cycle-count architectural model using measured command geometry, not silicon timing or power signoff.",""]
    (ROOT/"docs"/"performance.md").write_text("\n".join(lines))
    print(f"Performance report: {len(results)} requests across {len(summary)} K/pressure groups")
    return 0
if __name__=="__main__":raise SystemExit(main())
