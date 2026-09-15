#!/usr/bin/env python3
from pathlib import Path
import argparse,hashlib,shutil,subprocess,csv
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/"build/protected_offload/shared_firmware";BUILD.mkdir(parents=True,exist_ok=True)
toolroot=ROOT.parent/"ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin"
def tool(n):
 p=shutil.which("riscv64-unknown-elf-"+n) or str(toolroot/("riscv64-unknown-elf-"+n));return p if Path(p).is_file() or shutil.which(p) else None
gcc,objcopy=tool("gcc"),tool("objcopy")
if not gcc or not objcopy:raise SystemExit("RISC-V GCC/binutils required")
base=ROOT/"integration/rv32_offload/firmware"
sources=[ROOT/"integration/protected_offload/vendor/rv32/rv32_muldiv.sv",ROOT/"integration/protected_offload/vendor/rv32/rv32_core.sv",ROOT/"integration/protected_offload/vendor/rv32/rv32_rom_feeder.sv",ROOT/"rtl/int8_tensor_accel.sv",ROOT/"integration/protected_offload/rtl/protected_queue_count_next.sv",ROOT/"integration/protected_offload/rtl/protected_offload_dma.sv",ROOT/"integration/protected_offload/rtl/protected_offload_apb_csr.sv",ROOT/"integration/protected_offload/vendor/axi/dma_iommu.sv",ROOT/"integration/protected_offload/vendor/axi/qos_arbiter.sv",ROOT/"integration/protected_offload/vendor/axi/axi4_qos_fabric.sv",ROOT/"integration/protected_offload/rtl/protected_dma_axi_adapter.sv",ROOT/"integration/protected_offload/rtl/protected_host_axi_bridge.sv",ROOT/"integration/protected_offload/rtl/protected_accel_apb_config.sv",ROOT/"integration/protected_offload/rtl/protected_irq_aggregator.sv",ROOT/"integration/protected_offload/rtl/protected_axi_sram.sv",ROOT/"integration/protected_offload/rtl/protected_offload_service.sv",ROOT/"integration/protected_offload/rtl/rv32_protected_shared_top.sv",ROOT/"integration/protected_offload/sim/tb_rv32_protected_shared.sv"]
obj=BUILD/"obj";subprocess.run(["verilator","--binary","--sv","--timing","--assert","-Wall","-Wno-fatal","-Wno-PINCONNECTEMPTY","-Wno-TIMESCALEMOD","-Wno-VARHIDDEN","-Wno-UNUSEDSIGNAL","-Wno-BLKSEQ","-Wno-SYNCASYNCNET","--top-module","tb_rv32_protected_shared","--Mdir",str(obj),*map(str,sources)],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
def build(name,k,batch,asid,qos,irq):
 case=BUILD/name;case.mkdir(parents=True,exist_ok=True);elf=case/"firmware.elf"
 cmd=[gcc,"-march=rv32i_zicsr","-mabi=ilp32","-O2",f"-frandom-seed={name}","-save-temps=obj","-ffreestanding","-nostdlib","-fno-builtin","-fno-pic","-fno-stack-protector","-msmall-data-limit=0","-mno-relax",f"-DTEST_K={k}",f"-DTEST_BATCH={batch}",f"-DTEST_ASID={asid}",f"-DTEST_QOS={qos}",f"-DTEST_IRQ={irq}",str(base/"crt0.S"),str(base/"runtime.c"),str(ROOT/"integration/protected_offload/firmware/shared_offload.c"),f"-T{base/'link.ld'}","-Wl,--build-id=none","-o",str(elf)]
 subprocess.run(cmd,cwd=case,check=True,stdout=subprocess.DEVNULL)
 for sec,stem,start in [(".text","firmware",0),(".rodata,.data","data",0x800)]:
  binary=case/(stem+".bin");args=[objcopy,"-O","binary"]
  for s in sec.split(','):args+=["--only-section="+s]
  subprocess.run(args+[str(elf),str(binary)],check=True);data=binary.read_bytes()+bytes((-binary.stat().st_size)%4)
  (case/(stem+".hex")).write_text((f"@{start:08x}\n" if start else "")+"\n".join(f"{int.from_bytes(data[i:i+4],'little'):08x}" for i in range(0,len(data),4))+"\n")
 return case,elf
def execute(spec):
 name,k,batch,asid,qos,irq=spec;case,elf=build(*spec)
 run=subprocess.run([str(obj/"Vtb_rv32_protected_shared"),f"+FIRMWARE_HEX={case/'firmware.hex'}",f"+DATA_HEX={case/'data.hex'}",f"+EXPECT_K={k}",f"+EXPECT_BATCH={batch}"],cwd=ROOT,text=True,capture_output=True)
 line=next((x for x in run.stdout.splitlines() if x.startswith("PROTECTED_SHARED|")),"");status="PASS" if run.returncode==0 and "status=PASS" in line else "FAIL"
 if status=="FAIL":print(run.stdout[-1200:]+run.stderr[-1200:])
 return {"scenario":name,"status":status,"k":k,"batch":batch,"asid":asid,"qos":qos,"completion_mode":"irq" if irq else "poll","elf_sha256":hashlib.sha256(elf.read_bytes()).hexdigest(),"evidence":line}
matrix=[(f"k{k}_b{b}_a{a}_q{q}",k,b,a,q,int(q==15)) for k in (4,8,16,32) for b in (1,4) for a in (1,17) for q in (0,15)]
parser=argparse.ArgumentParser();parser.add_argument("--matrix",action="store_true");ns=parser.parse_args();specs=matrix if ns.matrix else [matrix[0]]
rows=[execute(s) for s in specs];report=ROOT/"reports/protected_shared_firmware.csv"
with report.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
passed=sum(r["status"]=="PASS" for r in rows);print(f"Protected shared firmware: {passed} / {len(rows)} PASS");raise SystemExit(passed!=len(rows))
