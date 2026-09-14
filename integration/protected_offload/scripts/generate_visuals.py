#!/usr/bin/env python3
from __future__ import annotations
import csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
IMG=ROOT/"docs/images"

def svg_start(title:str,width:int=1100,height:int=500)->list[str]:
  return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',f'<title>{title}</title>','<rect width="100%" height="100%" rx="20" fill="#071b2a"/>','<style>.h{font:700 24px Georgia,serif;fill:#f5f1e8}.t{font:15px Georgia,serif;fill:#d8e8e6}.s{font:13px Georgia,serif;fill:#a9cbc7}.axis{stroke:#8fb9b4;stroke-width:1}.bar{fill:#70d6c5}.bar2{fill:#f4c95d}</style>']

def performance()->None:
  rows=list(csv.DictReader((ROOT/"reports/protected_offload_performance.csv").open()))
  selected=[r for r in rows if r["path"]=="protected_dma" and r["batch"]=="16"]
  out=svg_start("Protected DMA device-cycle scaling",1000,480)
  out += ['<text class="h" x="48" y="45">Protected DMA: measured device cycles, batch 16</text>',
          '<line class="axis" x1="90" y1="400" x2="930" y2="400"/><line class="axis" x1="90" y1="85" x2="90" y2="400"/>']
  maximum=max(int(r["cycles"]) for r in selected)
  for i,row in enumerate(selected):
    x=130+i*155;h=270*int(row["cycles"])/maximum;y=400-h
    out += [f'<rect class="bar" x="{x}" y="{y:.1f}" width="90" height="{h:.1f}" rx="6"/>',
            f'<text class="t" x="{x+45}" y="425" text-anchor="middle">K={row["k"]}</text>',
            f'<text class="t" x="{x+45}" y="{y-10:.1f}" text-anchor="middle">{row["cycles"]}</text>']
  out += ['<text class="s" x="500" y="462" text-anchor="middle">Behavioral Verilator cycles from descriptor acceptance to completion</text>','</svg>']
  (IMG/"protected_offload_performance.svg").write_text("\n".join(out)+"\n")

def timeline()->None:
  trace=ROOT/"build/protected_offload/events/smoke.csv"
  events=list(csv.DictReader(trace.open())) if trace.exists() else []
  wanted=[]
  for kind in ("apb_write","submit","xlate","memory","command","chunk","result","completion"):
    match=next((r for r in events if r["event"]==kind),None)
    if match:wanted.append((kind,int(match["cycle"])))
  out=svg_start("Protected offload executable timeline",1100,420)
  out += ['<text class="h" x="48" y="45">One executable protected-offload job</text>','<line class="axis" x1="90" y1="210" x2="1010" y2="210"/>']
  if wanted:
    lo=min(c for _,c in wanted);hi=max(c for _,c in wanted);span=max(1,hi-lo)
    for idx,(name,cycle) in enumerate(wanted):
      x=100+880*(cycle-lo)/span;y=150 if idx%2==0 else 270
      out += [f'<line class="axis" x1="{x:.1f}" y1="200" x2="{x:.1f}" y2="{y+8 if y<210 else y-22}"/>',
              f'<circle class="bar2" cx="{x:.1f}" cy="210" r="7"/>',
              f'<text class="t" x="{x:.1f}" y="{y}" text-anchor="middle">{name}</text>',
              f'<text class="s" x="{x:.1f}" y="{y+19}" text-anchor="middle">cycle {cycle}</text>']
  out += ['<text class="s" x="550" y="390" text-anchor="middle">Normalized APB, translation, memory, stream, and completion events</text>','</svg>']
  (IMG/"protected_offload_timeline.svg").write_text("\n".join(out)+"\n")

def main()->int:
  IMG.mkdir(exist_ok=True);performance();timeline();print("PROTECTED_OFFLOAD_VISUALS|status=PASS|images=2");return 0
if __name__=="__main__":raise SystemExit(main())
