#!/usr/bin/env python3
from pathlib import Path
import argparse,hashlib,random,shutil,subprocess,csv,re
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/"build/protected_offload/shared_firmware";BUILD.mkdir(parents=True,exist_ok=True)
toolroot=ROOT.parent/"ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin"
def tool(n):
 p=shutil.which("riscv64-unknown-elf-"+n) or str(toolroot/("riscv64-unknown-elf-"+n));return p if Path(p).is_file() or shutil.which(p) else None
gcc,objcopy=tool("gcc"),tool("objcopy")
if not gcc or not objcopy:raise SystemExit("RISC-V GCC/binutils required")
base=ROOT/"integration/rv32_offload/firmware"
sources=[ROOT/"integration/protected_offload/vendor/rv32/rv32_muldiv.sv",ROOT/"integration/protected_offload/vendor/rv32/rv32_core.sv",ROOT/"integration/protected_offload/vendor/rv32/rv32_rom_feeder.sv",ROOT/"rtl/int8_tensor_accel.sv",ROOT/"integration/protected_offload/vendor/cache/dcache_pkg.sv",ROOT/"integration/protected_offload/vendor/cache/l1_dcache_top.sv",ROOT/"integration/protected_offload/rtl/protected_queue_count_next.sv",ROOT/"integration/protected_offload/rtl/protected_offload_dma.sv",ROOT/"integration/protected_offload/rtl/protected_offload_apb_csr.sv",ROOT/"integration/protected_offload/vendor/axi/dma_iommu.sv",ROOT/"integration/protected_offload/vendor/axi/qos_arbiter.sv",ROOT/"integration/protected_offload/vendor/axi/axi4_qos_fabric.sv",ROOT/"integration/protected_offload/rtl/protected_dma_axi_adapter.sv",ROOT/"integration/protected_offload/rtl/protected_host_axi_bridge.sv",ROOT/"integration/protected_offload/rtl/protected_apb_cache_bridge.sv",ROOT/"integration/protected_offload/rtl/protected_cache_maintenance_apb.sv",ROOT/"integration/protected_offload/rtl/protected_accel_apb_config.sv",ROOT/"integration/protected_offload/rtl/protected_irq_aggregator.sv",ROOT/"integration/protected_offload/rtl/protected_axi_sram.sv",ROOT/"integration/protected_offload/rtl/protected_offload_service.sv",ROOT/"integration/protected_offload/rtl/rv32_protected_shared_top.sv",ROOT/"integration/protected_offload/sim/tb_rv32_protected_shared.sv"]
def build(name,k,batch,asid,qos,irq,cache,negative,opt="O2",rv32m=0,seed=0,warm=0):
 case=BUILD/name;case.mkdir(parents=True,exist_ok=True);elf=case/"firmware.elf"
 isa="rv32im_zicsr" if rv32m else "rv32i_zicsr"
 cmd=[gcc,f"-march={isa}","-mabi=ilp32",f"-{opt}",f"-frandom-seed={seed or name}","-save-temps=obj","-ffreestanding","-nostdlib","-fno-builtin","-fno-pic","-fno-stack-protector","-msmall-data-limit=0","-mno-relax",f"-DTEST_K={k}",f"-DTEST_BATCH={batch}",f"-DTEST_ASID={asid}",f"-DTEST_QOS={qos}",f"-DTEST_IRQ={irq}",f"-DTEST_CACHE={cache}"]+([f"-D{negative}"] if negative else [])+(["-DTEST_WARM"] if warm else [])+[str(base/"crt0.S"),str(base/"runtime.c"),str(ROOT/"integration/protected_offload/firmware/shared_offload.c"),f"-T{base/'link.ld'}","-Wl,--build-id=none","-Wl,--no-undefined","-o",str(elf)]
 subprocess.run(cmd,cwd=case,check=True,stdout=subprocess.DEVNULL)
 for sec,stem,start in [(".text","firmware",0),(".rodata,.data","data",0x800)]:
  binary=case/(stem+".bin");args=[objcopy,"-O","binary"]
  for s in sec.split(','):args+=["--only-section="+s]
  subprocess.run(args+[str(elf),str(binary)],check=True);data=binary.read_bytes()+bytes((-binary.stat().st_size)%4)
  (case/(stem+".hex")).write_text((f"@{start:08x}\n" if start else "")+"\n".join(f"{int.from_bytes(data[i:i+4],'little'):08x}" for i in range(0,len(data),4))+"\n")
 return case,elf
compiled=set()
def execute(spec):
 name,k,batch,asid,qos,irq,cache,negative,*extra=spec;opt,rv32m,seed,warm=(extra+["O2",0,0,0])[:4];case,elf=build(name,k,batch,asid,qos,irq,cache,negative,opt,rv32m,seed,warm)
 define=getattr(ns,"define","");key=(cache,rv32m,define);obj=BUILD/(f"obj_c{cache}_m{rv32m}_{define or 'nominal'}")
 if key not in compiled:
  compile_cmd=["verilator","--binary","--sv","--timing","--assert","-Wall","-Wno-fatal","-Wno-PINCONNECTEMPTY","-Wno-TIMESCALEMOD","-Wno-VARHIDDEN","-Wno-UNUSEDSIGNAL","-Wno-BLKSEQ","-Wno-SYNCASYNCNET",f"-GUSE_CACHE=1'b{cache}",f"-GCPU_ENABLE_M=1'b{rv32m}","--top-module","tb_rv32_protected_shared","--Mdir",str(obj)]
  if define:compile_cmd.append("-D"+define)
  subprocess.run(compile_cmd+list(map(str,sources)),cwd=ROOT,check=True,stdout=subprocess.DEVNULL);compiled.add(key)
 run=subprocess.run([str(obj/"Vtb_rv32_protected_shared"),f"+FIRMWARE_HEX={case/'firmware.hex'}",f"+DATA_HEX={case/'data.hex'}",f"+EXPECT_K={k}",f"+EXPECT_BATCH={batch}"],cwd=ROOT,text=True,capture_output=True)
 text=run.stdout+run.stderr;line=next((x for x in run.stdout.splitlines() if x.startswith("PROTECTED_SHARED|")),"")
 expected=(run.returncode!=0) if define else ("OWNERSHIP_VIOLATION" in text) if negative=="NEG_ACCESS_DURING" else ("firmware result" in text) if negative else (run.returncode==0 and "status=PASS" in line)
 status="PASS" if expected else "FAIL"
 if status=="FAIL":print(text[-2400:])
 cycles=int(re.search(r"cycles=(\d+)",line).group(1)) if line and re.search(r"cycles=(\d+)",line) else 0
 measured=int(re.search(r"benchmark_cycles=(\d+)",line).group(1)) if line and re.search(r"benchmark_cycles=(\d+)",line) else 0
 return {"scenario":name,"status":status,"seed":seed,"optimizer":opt,"isa":"rv32im_zicsr" if rv32m else "rv32i_zicsr","k":k,"batch":batch,"mode":"warm" if warm else "cold","asid":asid,"qos":qos,"completion_mode":"irq" if irq else "poll","cache":cache,"cycles":cycles,"benchmark_cycles":measured,"expected_negative":negative or "none","elf_sha256":hashlib.sha256(elf.read_bytes()).hexdigest(),"evidence":line or ("detected:"+negative if expected else "")}
matrix=[(f"k{k}_b{b}_a{a}_q{q}",k,b,a,q,int(q==15),0,"") for k in (4,8,16,32) for b in (1,4) for a in (1,17) for q in (0,15)]
cached=[(f"cache_k{k}_b{b}_q{q}",k,b,1,q,int(q==15),1,"") for k in (4,16) for b in (1,4) for q in (0,15)]
negatives=[(n.lower(),4,1,1,0,0,1,n) for n in ("NEG_SKIP_FLUSH","NEG_SKIP_INVALIDATE","NEG_LATE_DIRTY","NEG_ACCESS_DURING")]
compiler=[(f"compiler_{opt}_{'m' if m else 'i'}_{i}",k,b,1,15 if i&1 else 0,i&1,0,"",opt,m,0) for opt in ("O0","O2","Os") for m in (0,1) for i,(k,b) in enumerate(((4,1),(8,4),(16,1),(32,4),(8,1),(16,4)))]
random_rows=[]
for seed in range(100):
 rng=random.Random(0x5A170000+seed);k=rng.choice((4,8,16,32));b=rng.choice((1,4));asid=rng.choice((1,17,31));qos=rng.randrange(16);irq=rng.randrange(2)
 random_rows.append((f"seed_{seed:03d}",k,b,asid,qos,irq,0,"","O2",seed&1,seed))
benchmark=[(f"bench_{'cache' if c else 'uncached'}_k{k}_b{b}_{'warm' if w else 'cold'}",k,b,1,8,0,c,"","O2",0,0,w) for c in (0,1) for k in (4,8,16,32,64) for b in (1,16,64) for w in (0,1)]
parser=argparse.ArgumentParser();parser.add_argument("--matrix",action="store_true");parser.add_argument("--cache",action="store_true");parser.add_argument("--negative",action="store_true");parser.add_argument("--compiler",action="store_true");parser.add_argument("--random",action="store_true");parser.add_argument("--benchmark",action="store_true");parser.add_argument("--define",default="");ns=parser.parse_args();specs=[cached[0]] if ns.define else negatives if ns.negative else cached if ns.cache else compiler if ns.compiler else random_rows if ns.random else benchmark if ns.benchmark else matrix if ns.matrix else [matrix[0]]
rows=[execute(s) for s in specs];report=ROOT/("reports/protected_cache_negative.csv" if ns.negative else "reports/protected_cache_ownership.csv" if ns.cache else "reports/protected_shared_firmware.csv")
if ns.compiler:report=ROOT/"reports/protected_shared_compiler_matrix.csv"
if ns.random:report=ROOT/"reports/protected_shared_random.csv"
if ns.benchmark:report=ROOT/"reports/protected_shared_benchmark.csv"
if ns.define:report=ROOT/("reports/integration_mutation_"+ns.define.lower()+".csv")
with report.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
passed=sum(r["status"]=="PASS" for r in rows);print(f"Protected shared firmware: {passed} / {len(rows)} PASS");raise SystemExit(passed!=len(rows))
