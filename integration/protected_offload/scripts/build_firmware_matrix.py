#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/"build/protected_offload/firmware";REPORT=ROOT/"reports/protected_offload_firmware.csv"
FW=ROOT/"integration/protected_offload/firmware";BASE=ROOT/"integration/rv32_offload/firmware"
def tool(name:str)->str|None:
  candidates=[f"riscv64-unknown-elf-{name}",f"riscv32-unknown-elf-{name}",str(ROOT.parent/"ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin"/f"riscv64-unknown-elf-{name}")]
  return next((c for c in candidates if shutil.which(c) or Path(c).is_file()),None)


def binary_to_word_hex(binary: Path, output: Path, start_word: int = 0) -> None:
  data = binary.read_bytes()
  if len(data) % 4:
    data += bytes(4 - (len(data) % 4))
  lines = [f"@{start_word:08x}"] if start_word else []
  lines.extend(f"{int.from_bytes(data[index:index + 4], 'little'):08x}"
               for index in range(0, len(data), 4))
  output.write_text("\n".join(lines) + "\n")
def main()->int:
  gcc=tool("gcc");objcopy=tool("objcopy");nm=tool("nm");rows=[];OUT.mkdir(parents=True,exist_ok=True)
  if not all((gcc,objcopy,nm)):
    for workflow in range(8):
      for opt in ("O0","O2","Os"):rows.append({"workflow":workflow,"optimizer":opt,"status":"SKIP","execution_status":"NOT_RUN","elf_sha256":"","instruction_bytes":"","detail":"RISC-V GCC/binutils unavailable"})
  else:
    for workflow in range(8):
      for opt in ("O0","O2","Os"):
        case=OUT/f"workflow_{workflow}_{opt}";case.mkdir(parents=True,exist_ok=True);elf=case/"firmware.elf"
        cmd=[gcc,"-march=rv32i_zicsr","-mabi=ilp32",f"-{opt}","-g","-ffreestanding","-nostdlib","-fno-builtin","-fno-pic","-fno-stack-protector","-msmall-data-limit=0","-mno-relax",f"-DWORKFLOW={workflow}",f"-I{FW}",str(BASE/"crt0.S"),str(BASE/"runtime.c"),str(FW/"protected_offload.c"),f"-T{BASE/'link.ld'}","-Wl,--build-id=none","-o",str(elf)]
        run=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
        status="PASS" if run.returncode==0 else "FAIL";detail="compiled freestanding RV32I/Zicsr firmware"
        if status=="PASS":
          undefined=subprocess.run([nm,"-u",str(elf)],capture_output=True,text=True).stdout.strip()
          if undefined:status="FAIL";detail="unresolved symbols: "+undefined.replace("\n",";")
        binary=case/"firmware.bin";data_binary=case/"data.bin"
        if status=="PASS":
          subprocess.run([objcopy,"-O","binary","--only-section=.text",str(elf),str(binary)],check=True)
          subprocess.run([objcopy,"-O","binary","--only-section=.rodata","--only-section=.data",str(elf),str(data_binary)],check=True)
          binary_to_word_hex(binary,case/"firmware.hex")
          binary_to_word_hex(data_binary,case/"data.hex",0x2000//4)
        rows.append({"workflow":workflow,"optimizer":opt,"status":status,"execution_status":"NOT_RUN","elf_sha256":hashlib.sha256(elf.read_bytes()).hexdigest() if elf.exists() else "","instruction_bytes":binary.stat().st_size if binary.exists() else "","detail":detail if status=="PASS" else run.stderr.strip()[-300:]})
  with REPORT.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0].keys(),lineterminator="\n");w.writeheader();w.writerows(rows)
  passed=sum(r["status"]=="PASS" for r in rows);skipped=sum(r["status"]=="SKIP" for r in rows)
  print(f"PROTECTED_OFFLOAD_FIRMWARE_BUILD|status={'PASS' if passed==24 else 'SKIP' if skipped==24 else 'FAIL'}|compiled={passed}/24|skipped={skipped}")
  return 0 if passed==24 or skipped==24 else 1
if __name__=="__main__":raise SystemExit(main())
