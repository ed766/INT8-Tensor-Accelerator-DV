#!/usr/bin/env python3
"""Generate one deterministic PyTorch-backed RV32/accelerator benchmark."""
from __future__ import annotations
import argparse, csv, hashlib, json
from pathlib import Path
import torch

PATTERNS = ("random", "zeros", "sat_pos", "sat_neg", "alternating")

def rounded_shift(product: torch.Tensor, shift: torch.Tensor) -> torch.Tensor:
    mag = torch.abs(product)
    offset = torch.where(shift == 0, torch.zeros_like(shift), torch.ones_like(shift) << (shift - 1))
    value = (mag + offset) >> shift
    return torch.where(product < 0, -value, value)

def build(k: int, batch: int, pattern: str, seed: int):
    gen = torch.Generator().manual_seed(seed)
    x = torch.randint(-32, 33, (batch, k), generator=gen, dtype=torch.int32)
    w = torch.randint(-16, 17, (4, k), generator=gen, dtype=torch.int32)
    bias = torch.randint(-64, 65, (4,), generator=gen, dtype=torch.int32)
    mult = torch.tensor([1, 3, -5, 7], dtype=torch.int32)
    shift = torch.tensor([0, 1, 2, 3], dtype=torch.int32)
    input_zp = -3
    weight_zp = torch.tensor([-2, 0, 3, 5], dtype=torch.int32)
    output_zp = torch.tensor([-4, 0, 7, 11], dtype=torch.int32)
    relu_mask = 0b1010
    if pattern == "zeros": x.zero_(); w.zero_(); bias.zero_(); input_zp = 0; weight_zp.zero_()
    elif pattern == "sat_pos": x.fill_(127); w.fill_(127); bias.zero_(); input_zp = 0; weight_zp.zero_(); mult.fill_(7); shift.zero_()
    elif pattern == "sat_neg": x.fill_(-128); w.fill_(127); bias.zero_(); input_zp = 0; weight_zp.zero_(); mult.fill_(7); shift.zero_()
    elif pattern == "alternating":
        x[:] = torch.tensor([127 if i & 1 else -128 for i in range(k)], dtype=torch.int32)
        for o in range(4): w[o] = torch.tensor([(-127 if (i + o) & 1 else 127) for i in range(k)], dtype=torch.int32)
        input_zp = 0; weight_zp.zero_()
    acc = (x.to(torch.int64) - input_zp) @ (w.to(torch.int64) - weight_zp[:,None]).T + bias
    product = acc * mult
    scaled = rounded_shift(product, shift) + output_zp
    for o in range(4):
        if relu_mask & (1 << o): scaled[:,o] = torch.clamp(scaled[:,o], min=0)
    expected = torch.clamp(scaled, -128, 127).to(torch.int32)
    return x,w,bias,mult,shift,input_zp,weight_zp,output_zp,relu_mask,expected

def c_array(name: str, values, ctype: str, dims: str) -> str:
    def fmt(value):
        if isinstance(value, list): return "{" + ",".join(fmt(v) for v in value) + "}"
        return str(int(value))
    return f"static const {ctype} {name}{dims} = {fmt(values)};\n"

def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument("--k",type=int,required=True);ap.add_argument("--batch",type=int,required=True)
    ap.add_argument("--mode",choices=("cold","warm"),required=True);ap.add_argument("--pattern",choices=PATTERNS,default="random")
    ap.add_argument("--seed",type=int,default=1);ap.add_argument("--output-dir",type=Path,required=True);args=ap.parse_args()
    if args.k not in (4,8,16,32,64) or args.batch not in (1,4,16,64): raise SystemExit("illegal benchmark geometry")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    x,w,bias,mult,shift,izp,wzp,ozp,relu,expected=build(args.k,args.batch,args.pattern,args.seed)
    text = "#pragma once\n#include <stdint.h>\n" + f"#define BENCH_K {args.k}u\n#define BENCH_BATCH {args.batch}u\n#define BENCH_COLD {int(args.mode=='cold')}\n#define INPUT_ZERO ({izp})\n#define RELU_MASK {relu}u\n"
    text += c_array("inputs",x.tolist(),"int8_t",f"[{args.batch}][{args.k}]")
    text += c_array("weights",w.tolist(),"int8_t",f"[4][{args.k}]")
    text += c_array("biases",bias.tolist(),"int32_t","[4]") + c_array("multipliers",mult.tolist(),"int16_t","[4]")
    text += c_array("shifts",shift.tolist(),"uint8_t","[4]") + c_array("weight_zero",wzp.tolist(),"int8_t","[4]")
    text += c_array("output_zero",ozp.tolist(),"int8_t","[4]") + c_array("expected",expected.tolist(),"int8_t",f"[{args.batch}][4]")
    header=args.output_dir/"benchmark_data.h";header.write_text(text)
    manifest={"k":args.k,"batch":args.batch,"mode":args.mode,"pattern":args.pattern,"seed":args.seed,
      "header_sha256":hashlib.sha256(text.encode()).hexdigest(),"expected":expected.tolist(),"torch_version":torch.__version__.split('+')[0]}
    (args.output_dir/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    with (args.output_dir/"expected.csv").open("w",newline="") as h:
        wr=csv.writer(h,lineterminator="\n");wr.writerow(("sample","output","expected"))
        for s,row in enumerate(expected.tolist()):
            for o,value in enumerate(row):wr.writerow((s,o,value))
    print(f"generated K={args.k} batch={args.batch} {args.mode} {args.pattern}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
