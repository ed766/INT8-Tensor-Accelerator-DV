#!/usr/bin/env python3
"""Build freestanding benchmark firmware and ROM/SRAM images."""
from __future__ import annotations
import argparse, os, shutil, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
FW=ROOT/"integration/rv32_offload/firmware"

def tool(name:str)->str:
    prefix=os.environ.get("RISCV_TOOLCHAIN_PREFIX","")
    candidates=[prefix+name if prefix else "",f"riscv64-unknown-elf-{name}",f"riscv32-unknown-elf-{name}",
      str(ROOT.parent/"ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin"/f"riscv64-unknown-elf-{name}")]
    for candidate in candidates:
        if candidate and (shutil.which(candidate) or Path(candidate).is_file()): return candidate
    raise SystemExit(f"missing RISC-V tool: {name}")

def words(binary:Path, output:Path, base:int|None=None):
    data=binary.read_bytes();data+=bytes((-len(data))%4);lines=[]
    if base is not None:lines.append(f"@{base//4:08x}")
    lines.extend(f"{int.from_bytes(data[i:i+4],'little'):08x}" for i in range(0,len(data),4));output.write_text("\n".join(lines)+"\n")

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--scenario-dir",type=Path,required=True);ap.add_argument("--mutation",default="");args=ap.parse_args()
    out=args.scenario_dir;gcc,objcopy,nm=(tool(x) for x in ("gcc","objcopy","nm"));elf=out/"benchmark.elf"
    command=[gcc,"-march=rv32i_zicsr","-mabi=ilp32","-O2","-g","-ffreestanding","-nostdlib","-fno-builtin","-fno-pic","-fno-stack-protector","-msmall-data-limit=0","-mno-relax",f"-I{out}",str(FW/"crt0.S"),str(FW/"runtime.c"),str(FW/"benchmark.c"),f"-T{FW/'link.ld'}","-Wl,--build-id=none","-Wl,-Map="+str(out/"benchmark.map"),"-o",str(elf)]
    if args.mutation=="scalar_round":command.insert(1,"-DRV32_BENCH_MUT_SCALAR_ROUND")
    if args.mutation=="corrupt_result":command.insert(1,"-DRV32_BENCH_MUT_CORRUPT_RESULT")
    subprocess.run(command,check=True)
    undefined=subprocess.run([nm,"-u",str(elf)],check=True,capture_output=True,text=True).stdout.strip()
    if undefined:raise SystemExit("unresolved runtime symbols:\n"+undefined)
    text_bin=out/"benchmark.text.bin";data_bin=out/"benchmark.data.bin"
    subprocess.run([objcopy,"-O","binary","--only-section=.text",str(elf),str(text_bin)],check=True)
    subprocess.run([objcopy,"-O","binary","--only-section=.rodata","--only-section=.data",str(elf),str(data_bin)],check=True)
    words(text_bin,out/"benchmark.hex");words(data_bin,out/"benchmark.data.hex",0x2000)
    print(elf)
    return 0
if __name__=="__main__":raise SystemExit(main())
