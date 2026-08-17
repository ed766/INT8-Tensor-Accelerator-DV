#!/usr/bin/env python3
"""Render an event-derived benchmark timeline from the deterministic smoke log."""
from __future__ import annotations
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
LOG=ROOT/"build/rv32_benchmark/cases/k4_b1_warm_random_s1_p0/run.log"
OUT=ROOT/"docs/images/rv32_accel_waveform.svg"
def main()->int:
    events=[]
    for line in LOG.read_text().splitlines():
      m=re.match(r"BENCH_EVENT\|cycle=(\d+)\|event=(\w+)",line)
      if m:events.append((int(m.group(1)),m.group(2)))
    if not events:raise SystemExit("no benchmark events in smoke log")
    # Focus on the first command through completion; configuration appears as the lead-in.
    first=next(i for i,e in enumerate(events) if e[1]=="command_aw");events=events[first:]
    lo,hi=events[0][0],events[-1][0];span=max(1,hi-lo);width,height=900,260;left,right=145,30;top=45
    lanes=["command_aw","input_chunk","result_valid","result_pop","firmware_done"]
    labels={"command_aw":"Command accepted","input_chunk":"Activation chunk","result_valid":"Accelerator result valid","result_pop":"Firmware result pop","firmware_done":"Firmware completion"}
    colors={"command_aw":"#d6532f","input_chunk":"#007c91","result_valid":"#486b35","result_pop":"#c28b16","firmware_done":"#725a9b"}
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">','<rect width="100%" height="100%" fill="#f7f3e8"/>','<text x="450" y="25" text-anchor="middle" font-family="DejaVu Sans" font-size="17" font-weight="bold">Measured RV32I firmware-to-accelerator event timeline</text>']
    for index,lane in enumerate(lanes):
      y=top+index*38;lines.append(f'<text x="{left-8}" y="{y+5}" text-anchor="end" font-family="DejaVu Sans" font-size="12">{labels[lane]}</text><line x1="{left}" y1="{y}" x2="{width-right}" y2="{y}" stroke="#bbb"/>')
      for cycle,event in events:
        if event!=lane:continue
        x=left+(cycle-lo)/span*(width-left-right);lines.append(f'<line x1="{x:.1f}" y1="{y-11}" x2="{x:.1f}" y2="{y+11}" stroke="{colors[lane]}" stroke-width="4"/><text x="{x:.1f}" y="{y-15}" text-anchor="middle" font-family="DejaVu Sans" font-size="9">{cycle}</text>')
    lines.append(f'<text x="{width/2}" y="{height-8}" text-anchor="middle" font-family="DejaVu Sans" font-size="11">Shared-clock cycle from deterministic GCC firmware smoke run</text></svg>')
    OUT.write_text("\n".join(lines)+"\n");print(OUT);return 0
if __name__=="__main__":raise SystemExit(main())
