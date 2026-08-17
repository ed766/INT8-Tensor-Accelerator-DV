#!/usr/bin/env python3
"""Create Markdown and SVG evidence from measured benchmark CSVs."""
from __future__ import annotations
import csv,html
from pathlib import Path
import statistics
ROOT=Path(__file__).resolve().parents[3];REPORTS=ROOT/"reports";IMAGES=ROOT/"docs/images"
def rows(name):return list(csv.DictReader((REPORTS/name).open()))
def svg_plot(path,title,series,ylabel):
    width,height=760,360;left,bottom,top,right=70,55,45,25;pw=width-left-right;ph=height-top-bottom
    values=[v for _,pts in series for _,v in pts];maximum=max(values) if values else 1
    colors=("#007c91","#d6532f","#486b35","#c28b16","#725a9b")
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">','<rect width="100%" height="100%" fill="#f7f3e8"/>',f'<text x="{width/2}" y="25" text-anchor="middle" font-family="DejaVu Sans" font-size="17" font-weight="bold">{html.escape(title)}</text>',f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#333"/><line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#333"/>']
    for index,(label,pts) in enumerate(series):
      points=[]
      for x,v in pts:
        px=left+(x-1)/63*pw;py=top+(1-v/maximum)*ph;points.append(f"{px:.1f},{py:.1f}");lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{colors[index%len(colors)]}"/>')
      lines.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[index%len(colors)]}" stroke-width="2"/>')
      lines.append(f'<text x="{left+index*130}" y="{height-12}" font-family="DejaVu Sans" font-size="12" fill="{colors[index%len(colors)]}">{html.escape(label)}</text>')
    for x in (1,4,16,64):lines.append(f'<text x="{left+(x-1)/63*pw:.1f}" y="{height-bottom+18}" text-anchor="middle" font-family="DejaVu Sans" font-size="11">{x}</text>')
    lines.append(f'<text x="{width/2}" y="{height-28}" text-anchor="middle" font-family="DejaVu Sans" font-size="12">Batch size</text><text transform="translate(18 {height/2}) rotate(-90)" text-anchor="middle" font-family="DejaVu Sans" font-size="12">{html.escape(ylabel)}</text></svg>')
    path.write_text("\n".join(lines)+"\n")
def main()->int:
    bench=rows("rv32_accel_benchmark.csv");correct=rows("rv32_accel_correctness.csv");bp=rows("rv32_accel_backpressure.csv");mut=rows("rv32_accel_mutations.csv")
    warm=[r for r in bench if r["mode"]=="warm"];cold=[r for r in bench if r["mode"]=="cold"]
    break_even={}
    for k in (4,8,16,32,64):
      passing=sorted((int(r["batch"]),float(r["end_to_end_speedup"])) for r in warm if int(r["k"])==k and float(r["end_to_end_speedup"])>1)
      break_even[k]=passing[0][0] if passing else "NA"
    series=[]
    for k in (4,8,16,32,64):series.append((f"K={k}",[(int(r["batch"]),float(r["end_to_end_speedup"])) for r in warm if int(r["k"])==k]))
    svg_plot(IMAGES/"rv32_accel_speedup.svg","Warm RV32I-to-accelerator cycle speedup",series,"Cycle speedup (x)")
    latency=[]
    for mode in ("cold","warm"):latency.append((mode,[(int(r["batch"]),float(r["accel_adjusted_cycles"])) for r in bench if int(r["k"])==64 and r["mode"]==mode]))
    svg_plot(IMAGES/"rv32_accel_latency.svg","K=64 accelerator end-to-end cycles",latency,"Simulated cycles")
    bars=[]
    for index,(k,value) in enumerate(break_even.items()):
      numeric=0 if value=="NA" else int(value);x=95+index*125;h=numeric/64*150
      bars.append(f'<rect x="{x}" y="{205-h:.1f}" width="62" height="{h:.1f}" fill="#007c91"/><text x="{x+31}" y="225" text-anchor="middle" font-family="DejaVu Sans" font-size="12">K={k}</text><text x="{x+31}" y="{195-h:.1f}" text-anchor="middle" font-family="DejaVu Sans" font-size="12">{value}</text>')
    (IMAGES/"rv32_accel_break_even.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="760" height="260" viewBox="0 0 760 260"><rect width="100%" height="100%" fill="#f7f3e8"/><text x="380" y="25" text-anchor="middle" font-family="DejaVu Sans" font-size="17" font-weight="bold">First measured warm batch above 1x</text><line x1="65" y1="205" x2="720" y2="205" stroke="#333"/>'+''.join(bars)+'<text x="18" y="130" transform="rotate(-90 18 130)" text-anchor="middle" font-family="DejaVu Sans" font-size="12">Batch size</text></svg>\n')
    phase_rows="".join(f"| {label} | {statistics.median(int(r[key]) for r in bench):.1f} |\n" for label,key in (("Configuration","configuration_adjusted_cycles"),("Command and streaming","stream_adjusted_cycles"),("Polling","poll_adjusted_cycles"),("Output read/pop","output_read_adjusted_cycles")))
    summary="# RV32I vs INT8 Accelerator Benchmark\n\nThese values are measured behavioral Verilator cycles at one shared clock. They are not simulator wall time, FPGA/silicon frequency, power, or physical implementation results.\n\n## Closure\n\n| Evidence | Result |\n| --- | ---: |\n"+f"| Cold/warm benchmark matrix | `{sum(r['status']=='PASS' for r in bench)} / {len(bench)}` |\n| Operand-pattern correctness | `{sum(r['status']=='PASS' for r in correct)} / {len(correct)}` |\n| Output-backpressure robustness | `{sum(r['status']=='PASS' for r in bp)} / {len(bp)}` |\n| Expected-fail mutations detected | `{sum(r['status']=='PASS' for r in mut)} / {len(mut)}` |\n\n## Warm Break-Even Batch\n\n| K | First measured batch above 1x |\n| ---: | ---: |\n"+"".join(f"| {k} | {v} |\n" for k,v in break_even.items())+"\n## Firmware/Transport Cycle Breakdown\n\n| Phase | Median cycles across matrix |\n| --- | ---: |\n"+phase_rows+"\nThe scalar path is GCC `-O2` RV32I/Zicsr software with explicit multiplication helpers. Cold measurements include configuration; warm measurements reuse configured parameters. Compute-only latency ends at first result validity, while end-to-end latency includes firmware streaming, polling, and result reads.\n\n![Measured speedup](../docs/images/rv32_accel_speedup.svg)\n\n![Measured latency](../docs/images/rv32_accel_latency.svg)\n"
    summary += "\n![Measured break-even batch](../docs/images/rv32_accel_break_even.svg)\n"
    (REPORTS/"rv32_accel_benchmark_summary.md").write_text(summary);print("generated RV32 accelerator benchmark report");return 0
if __name__=="__main__":raise SystemExit(main())
