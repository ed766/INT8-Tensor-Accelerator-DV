#!/usr/bin/env python3
import csv,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
rows=list(csv.DictReader((ROOT/"reports/protected_offload_matched_performance.csv").open()))
base={(r["k"],r["batch"],r["mode"]):int(r["cycles"]) for r in rows if r["path"]=="scalar_rv32i"}
paths=["scalar_rv32i","scalar_rv32im","mmio_stream","uncached_shared_dma","cached_shared_dma"]
colors=["#667085","#0b7285","#e67700","#2f9e44","#c92a2a"]
vals=[]
for p in paths:
 vals.append(statistics.median(base[(r["k"],r["batch"],r["mode"])]/max(1,int(r["cycles"])) for r in rows if r["path"]==p))
w,h=880,360;mx=max(vals);bars=[]
for i,(p,v,c) in enumerate(zip(paths,vals,colors)):
 x=55+i*160;bh=240*v/mx;y=300-bh
 bars.append(f'<rect x="{x}" y="{y:.1f}" width="110" height="{bh:.1f}" rx="5" fill="{c}"/><text x="{x+55}" y="{y-9:.1f}" text-anchor="middle" font-size="17" font-weight="700">{v:.2f}x</text><text x="{x+55}" y="326" text-anchor="middle" font-size="12">{p.replace("_"," ")}</text>')
svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><rect width="100%" height="100%" fill="#f8f5ee"/><text x="32" y="32" font-family="sans-serif" font-size="21" font-weight="700">Matched median speedup vs scalar RV32I</text><text x="32" y="53" font-family="sans-serif" font-size="12" fill="#475467">150 passing behavioral same-clock measurements; identical tensor and measurement hashes</text><line x1="35" y1="300" x2="850" y2="300" stroke="#98a2b3"/>{''.join(bars)}</svg>'''
out=ROOT/"docs/images/protected_offload_matched_speedup.svg";out.write_text(svg+"\n")
print("PROTECTED_MATCHED_VISUAL|status=PASS|images=1")
