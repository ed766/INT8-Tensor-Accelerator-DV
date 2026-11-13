#!/usr/bin/env python3
from pathlib import Path
import argparse,hashlib,random,shutil,subprocess,csv,re,os,json,fcntl
from coverage_provenance import write_manifest
from reset_evidence import phase_reached
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/"build/protected_offload/shared_firmware";BUILD.mkdir(parents=True,exist_ok=True)
toolroot=ROOT.parent/"ucie_chiplet_soc/chiplet_extension/build/rv32_toolchain/root/usr/bin"
def tool(n):
 p=shutil.which("riscv64-unknown-elf-"+n) or str(toolroot/("riscv64-unknown-elf-"+n));return p if Path(p).is_file() or shutil.which(p) else None
gcc,objcopy,nm=tool("gcc"),tool("objcopy"),tool("nm")
if not gcc or not objcopy or not nm:raise SystemExit("RISC-V GCC/binutils (gcc, objcopy, nm) required")
base=ROOT/"integration/rv32_offload/firmware"
FIRMWARE_IMPLEMENTATION=os.environ.get("PROTECTED_FIRMWARE_IMPLEMENTATION","shared")
if FIRMWARE_IMPLEMENTATION not in {"shared","independent"}:
 raise SystemExit("PROTECTED_FIRMWARE_IMPLEMENTATION must be shared or independent")
FIRMWARE_SOURCE=ROOT/"integration/protected_offload/firmware"/("independent_offload.c" if FIRMWARE_IMPLEMENTATION=="independent" else "shared_offload.c")
from shared_rtl_sources import sources
chiplet_sources=[p for p in sorted((ROOT/"integration/protected_offload/vendor/chiplet").rglob("*.sv")) if "firmware" not in p.parts and p.name not in ("soc_chiplet_rv32_top.sv","soc_chiplet_async_top.sv")]
SCENARIO_DEFINES = {
 "independent_driver_publish_pop": ("TEST_INDEPENDENT_PUBLISH_POP",),
 "reset_transport__case_4": ("TEST_RESET_COMPLETION_IRQ",),
 "translation_recovery__input_bus_error": ("TEST_REMAP_INVALIDATION",),
 "translation_recovery__fault_4": ("TEST_ASID_ISOLATION",),
 "translation_recovery__fault_3": ("TEST_CACHED_PERMISSION_TRANSITIONS",),
 "queues_configuration__case_1": ("TEST_SUBMIT_FIFO_PRESSURE",),
 "apb_axi__case_4": ("TEST_REGION_BOUNDARIES",),
 "apb_axi__case_5": ("TEST_ACCESS_LEGALITY",),
 "queues_configuration__case_2": ("TEST_COMPLETION_FIFO_PRESSURE",),
 "queues_configuration__case_4": ("TEST_DUPLICATE_UNREAD_TAG",),
 "queues_configuration__case_5": ("TEST_REFERENCED_BANK",),
 "queues_configuration__case_3": ("TEST_COMPLETION_PUBLISH_POP",),
 "queues_configuration__case_6": ("TEST_INACTIVE_BANK_ROLLOVER",),
 "combined_services__case_5": ("TEST_CHIPLET_SLEEP_DURING",),
 "combined_services__case_3": ("TEST_CHIPLET_PARITY_FAULT",),
 "interrupts__case_1": ("TEST_IRQ_PENDING_ENABLE",),
 "interrupts__case_2": ("TEST_COMPLETION_PUBLISH_POP", "TEST_IRQ_ACK_COLLISION"),
 "interrupts__case_3": ("TEST_IRQ_BOTH_SOURCES",),
 "interrupts__case_4": ("TEST_TIMER_DEVICE_PRIORITY",),
 "interrupts__case_5": ("TEST_IRQ_WFI",),
 "interrupts__case_6": ("TEST_IRQ_DELAY_M",),
 "cache_ownership__case_4": ("TEST_CACHE_BOUNDARY",),
 "cache_ownership__case_5": ("TEST_MAINT_ERROR_RECOVERY",),
 "cache_ownership__case_6": ("TEST_UNRELATED_ACCESS_DURING",),
 "neg_access_during": ("TEST_CACHE_BOUNDARY",),
 "seed_097": ("TEST_DUPLICATE_TAG",),
 "seed_098": ("TEST_UNRELATED_ACCESS_DURING",),
 "seed_099": ("TEST_COMPLETION_PUBLISH_POP",),
 "coverage_apb_edges": ("TEST_COVERAGE_EDGES",),
}
def build(name,k,batch,asid,qos,irq,cache,negative,opt="O2",rv32m=0,seed=0,warm=0,combined=0,fault="",cpu_stream_seed=None,artifact_name=None,scenario_id=0):
 case=BUILD/(artifact_name or name);case.mkdir(parents=True,exist_ok=True);elf=case/"firmware.elf"
 cpu_stream_hash="";cpu_stream_range=None;scenario_program_hash="";scenario_program_range=None;scenario_activation_address=None;extra_sources=[]
 if cpu_stream_seed is not None:
  from gen_crossover_cpu_stream import generate
  stream_source=case/f"cpu_stream_{cpu_stream_seed}.S"
  cpu_stream_hash=generate(cpu_stream_seed,stream_source)
  extra_sources=[str(stream_source)]
 if scenario_id:
  from gen_crossover_scenario_program import generate
  scenario_source=case/"crossover_scenario.S"
  scenario_program_hash=generate(name,scenario_id,scenario_source)
  extra_sources.append(str(scenario_source))
 isa="rv32im_zicsr" if rv32m else "rv32i_zicsr"
 scenario_define = ["-D"+macro for macro in SCENARIO_DEFINES.get(name, ())]
 if name in stateful_rows:
  entry=stateful_rows[name]
  scenario_define += [f"-DTEST_STATEFUL_CASE={entry['code']}"] + ["-D"+macro for macro in entry["extra"]]
 if name in m_permutation_rows:
  from m_permutation_model import assembly
  entry=m_permutation_rows[name]
  asm=case/"m_sweep.S";asm.write_text(assembly(entry));extra_sources.append(str(asm))
  context=("dma","dual","sleep","pressure","timing").index(entry["context"])
  scenario_define += ["-DTEST_M_SWEEP",f"-DTEST_M_SWEEP_CONTEXT={context}"]
  if context==2:scenario_define.append("-DTEST_CHIPLET_SLEEP_DURING")
  if context==3:scenario_define.append("-DTEST_COMPLETION_FIFO_PRESSURE")
 firmware_timing_define = []
 if name == "queues_configuration__case_3":
  firmware_timing_define.append("-DTEST_COMPLETION_POP_DELAY=4")
 elif name == "queues_configuration__case_4":
  firmware_timing_define.append("-DTEST_COMPLETION_POP_DELAY=9")
 cmd=[gcc,f"-march={isa}","-mabi=ilp32",f"-{opt}",f"-frandom-seed={seed or name}","-save-temps=obj","-ffreestanding","-nostdlib","-fno-builtin","-fno-pic","-fno-stack-protector","-msmall-data-limit=0","-mno-relax",f"-DTEST_K={k}",f"-DTEST_BATCH={batch}",f"-DTEST_ASID={asid}",f"-DTEST_QOS={qos}",f"-DTEST_IRQ={irq}",f"-DTEST_CACHE={cache}",f"-DTEST_SCENARIO_ID={scenario_id}"]+scenario_define+firmware_timing_define+(["-DTEST_M_DEPENDENCY"] if rv32m else [])+(["-DTEST_CPU_STREAM"] if cpu_stream_seed is not None else [])+([f"-D{negative}"] if negative else [])+([f"-D{fault}"] if fault else [])+(["-DTEST_WARM"] if warm else [])+(["-DTEST_COMBINED_HOST"] if combined else [])+[str(base/"crt0.S"),str(base/"runtime.c"),str(ROOT/"integration/protected_offload/firmware/shared_offload.c"),*extra_sources,f"-T{base/'link.ld'}","-Wl,--build-id=none","-Wl,--no-relax","-Wl,--no-undefined","-o",str(elf)]
 cmd[cmd.index(str(ROOT/"integration/protected_offload/firmware/shared_offload.c"))]=str(FIRMWARE_SOURCE)
 subprocess.run(cmd,cwd=case,check=True,stdout=subprocess.DEVNULL)
 if cpu_stream_seed is not None or scenario_id:
  sym=subprocess.run([nm,"-n",str(elf)],check=True,text=True,capture_output=True).stdout
  symbols={}
  for line in sym.splitlines():
   match=re.match(r"([0-9a-fA-F]+)\s+\w\s+(generated_cpu_stream(?:_end)?)$",line)
   if match:symbols[match.group(2)]=int(match.group(1),16)
   match=re.match(r"([0-9a-fA-F]+)\s+\w\s+(crossover_scenario_program(?:_end)?)$",line)
   if match:symbols[match.group(2)]=int(match.group(1),16)
   match=re.match(r"([0-9a-fA-F]+)\s+[bBdD]\s+scenario_activation$",line)
   if match:symbols["scenario_activation"]=int(match.group(1),16)
  if cpu_stream_seed is not None:
   if not {"generated_cpu_stream","generated_cpu_stream_end"}.issubset(symbols) or symbols["generated_cpu_stream_end"]<=symbols["generated_cpu_stream"]:
    raise RuntimeError(f"generated stream symbols missing/invalid in {elf}: {symbols}")
   cpu_stream_range=(symbols["generated_cpu_stream"],symbols["generated_cpu_stream_end"])
  if scenario_id:
   if not {"crossover_scenario_program","crossover_scenario_program_end"}.issubset(symbols) or symbols["crossover_scenario_program_end"]<=symbols["crossover_scenario_program"]:
    raise RuntimeError(f"scenario program symbols missing/invalid in {elf}: {symbols}")
   scenario_program_range=(symbols["crossover_scenario_program"],symbols["crossover_scenario_program_end"])
   if "scenario_activation" not in symbols:
    raise RuntimeError(f"scenario activation symbol missing in {elf}: {symbols}")
   scenario_activation_address=symbols["scenario_activation"]
 for sec,stem,start in [(".text","firmware",0),(".rodata,.data","data",0x800)]:
  binary=case/(stem+".bin");args=[objcopy,"-O","binary"]
  for s in sec.split(','):args+=["--only-section="+s]
  subprocess.run(args+[str(elf),str(binary)],check=True);data=binary.read_bytes()+bytes((-binary.stat().st_size)%4)
  (case/(stem+".hex")).write_text((f"@{start:08x}\n" if start else "")+"\n".join(f"{int.from_bytes(data[i:i+4],'little'):08x}" for i in range(0,len(data),4))+"\n")
 return case,elf,cpu_stream_hash,cpu_stream_range,scenario_program_hash,scenario_program_range,scenario_activation_address
compiled=set()
def source_build_fingerprint(elf, include_chiplet):
 digest=hashlib.sha256()
 for path in sources+(chiplet_sources if include_chiplet else []):
  digest.update(str(path.relative_to(ROOT)).encode())
  digest.update(path.read_bytes())
 digest.update(elf.read_bytes())
 return digest.hexdigest()
def execute(spec):
 simulator_version=subprocess.run(["verilator","--version"],check=True,text=True,capture_output=True).stdout.strip()
 if ns.code_coverage and "5.049" not in simulator_version:
  raise SystemExit(f"integration coverage requires pinned Verilator 5.049, found {simulator_version}")
 name,k,batch,asid,qos,irq,cache,negative,*extra=spec
 defaults=["O2",0,0,0,0,-1,""]
 extra=list(extra)+defaults[len(extra):]
 opt,rv32m,seed,warm,combined,reset_at,fault=extra[:7]
 reset_phase=extra[7] if len(extra)>7 else "none"
 if ns.reset_phase_override:
  reset_phase=ns.reset_phase_override
 cpu_stream_seed=extra[8] if len(extra)>8 else None
 # Combined-service rows are dedicated executable overlap witnesses. Keep
 # their transport schedule deterministic so the short AES busy window is
 # not accidentally shifted out of phase by unrelated IRQ/backpressure
 # randomization. The remaining rows retain the full stall/IRQ sweep.
 stall_pct=0 if combined else (0,25,50,75)[seed%4]
 if name in stateful_rows:stall_pct=stateful_rows[name]["stall"]
 if name=="interrupts__case_6":stall_pct=0
 # This seeded input-memory fault is intentionally contained before normal
 # downstream payload traffic, so backpressure would be a requested-but-
 # unreachable knob rather than meaningful activity.
 if name in {"seed_014", "seed_034"}:
  stall_pct=0
 if name == "seed_099":
  # Keep the two short jobs unbackpressured so publication can meet the
  # completion-pop boundary; other random rows cover the stall sweep.
  stall_pct=0
 if name in {"queues_configuration__case_2", "queues_configuration__case_3"}:
  stall_pct=50
 if name == "seed_099":
  stall_pct=50
 artifact_name=f"{name}__mut_{define.lower()}" if (define:=getattr(ns,"define","")) else name
 artifact_prefix=os.environ.get("PROTECTED_ARTIFACT_PREFIX", "")
 if artifact_prefix:
  prefix=Path(artifact_prefix)
  if prefix.is_absolute() or ".." in prefix.parts:
   raise SystemExit("PROTECTED_ARTIFACT_PREFIX must stay inside the run artifact directory")
  artifact_name=str(prefix/artifact_name)
 if ns.code_coverage:artifact_name="coverage/"+artifact_name
 scenario_id=(next((index for index,row in enumerate(crossover_rows,1) if row[0]==name),0)
              if ns.crossover or ns.scenario else 0)
 case,elf,cpu_stream_hash,cpu_stream_range,scenario_program_hash,scenario_program_range,scenario_activation_address=build(name,k,batch,asid,qos,irq,cache,negative,opt,rv32m,seed,warm,combined,fault,cpu_stream_seed,artifact_name,scenario_id)
 build_id=source_build_fingerprint(elf, combined)
 scenario_macros=dict(SCENARIO_DEFINES)
 if name in stateful_rows:
  scenario_macros[name]=(*scenario_macros.get(name,()),*(macro for macro in stateful_rows[name]["extra"] if macro=="TEST_FABRIC_CONTENDER"))
 scenario_define="_".join(scenario_macros.get(name,()))
 rtl_sources=sources+(chiplet_sources if combined else [])
 rtl_fingerprint=hashlib.sha256(simulator_version.encode()+b"".join(path.read_bytes() for path in rtl_sources)).hexdigest()
 setup_pready_high=ns.setup_pready_high or name=="apb_axi__case_1"
 completion_pop_wait=(5 if name=="seed_099" else
                      4 if name=="queues_configuration__case_3" else 0)
 if name in stateful_rows:completion_pop_wait=stateful_rows[name].get("pop_wait",0)
 key=(cache,rv32m,define,scenario_define,combined,completion_pop_wait,ns.code_coverage,setup_pready_high,rtl_fingerprint)
 obj=BUILD/(f"obj_c{cache}_m{rv32m}_{define or scenario_define or 'nominal'}_h{combined}_popwait{completion_pop_wait}_cov{int(ns.code_coverage)}_p{int(ns.setup_pready_high)}_{rtl_fingerprint[:10]}")
 if key not in compiled:
  obj.mkdir(parents=True,exist_ok=True)
  # Keep architectural traps enabled in every firmware lane.  Disabling
  # traps also disables architectural CSR/MRET/WFI behavior, making the run
  # unsuitable for strict ISS comparison.  The referenced-bank error is
  # handled by the firmware's installed precise trap handler.
  traps = 1
  compile_cmd=["verilator"]+(["--cc","--exe","--build"] if ns.code_coverage else ["--binary"])+["--sv","--timing","--assert"]+( ["--coverage"] if ns.code_coverage else [])+["-Wall","-Wno-fatal","-Wno-PINCONNECTEMPTY","-Wno-TIMESCALEMOD","-Wno-VARHIDDEN","-Wno-UNUSEDSIGNAL","-Wno-BLKSEQ","-Wno-SYNCASYNCNET",f"-GUSE_CACHE=1'b{cache}",f"-GCPU_ENABLE_M=1'b{rv32m}",f"-GCPU_ENABLE_TRAPS=1'b{traps}",f"-GENABLE_CHIPLET=1'b{combined}",f"-GCOMPLETION_POP_WAIT_CYCLES={completion_pop_wait}","--top-module","tb_rv32_protected_shared","--Mdir",str(obj)]
  # Assertions are exercised by the functional lane. The coverage-only build
  # disables assertion elaboration because the pinned newer Verilator parser
  # rejects two legal SVA expressions in imported blocks.
  if ns.code_coverage:
   # All RTL assertions are guarded by SYNTHESIS; exclude them from design
   # statement coverage (they are run in the non-coverage regression). This
   # also avoids a known internal error in Verilator's --no-assert SVA pass.
   compile_cmd.append("-DSYNTHESIS")
   # Re-enable executable ownership checking in cache-ownership coverage
   # runs. This is plain simulation logic, not SVA, and exercises the PTE
   # shadow helpers that would otherwise be counted as uncovered RTL.
   compile_cmd.append("-DPROTECTED_COVERAGE")
  if define:compile_cmd.append("-D"+define)
  if setup_pready_high or define=="RV32_BUG_APB_SETUP_RETIRE":compile_cmd.append("-DTB_SETUP_PREADY_HIGH")
  if scenario_define:
   for scenario_macro in scenario_macros.get(name,()):compile_cmd.append("-D"+scenario_macro)
  extra_main=[]
  if ns.code_coverage:
   main_cpp=obj/"coverage_main.cpp"
   main_cpp.write_text("\n".join(["#include <cstdlib>", '#include "verilated.h"', '#include "verilated_cov.h"', '#include "Vtb_rv32_protected_shared.h"', "int main(int argc,char** argv){", "VerilatedContext context; context.commandArgs(argc,argv);", "Vtb_rv32_protected_shared dut(&context);", "while(!context.gotFinish()){dut.eval();context.timeInc(1);}", "dut.final();const char* p=std::getenv(\"VERILATOR_COVERAGE_FILENAME\");VerilatedCov::write(p?p:\"coverage.dat\");return 0;", "}", ""]))
   extra_main=[str(main_cpp)]
  # Independent regression lanes may elaborate the same parameter tuple.
  # Serialize generation/build so one Verilator process cannot replace PCH
  # or C++ files while another make invocation is reading them.
  with (obj/"build.lock").open("w") as build_lock:
   fcntl.flock(build_lock,fcntl.LOCK_EX)
   subprocess.run(compile_cmd+list(map(str,rtl_sources))+extra_main,cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
  compiled.add(key)
 partial_retry = fault == "TEST_PARTIAL_OUTPUT_RETRY"
 trace=case/"crossover.trace"
 stall_seed=ns.stall_seed if ns.stall_seed is not None else seed+1
 if name == "queues_configuration__case_3" and ns.stall_seed is None:
  # Independent second witness for same-edge completion publish/pop. This
  # fixed schedule is part of the scenario definition, not a claimed random
  # coverage point.
  stall_seed=1022
 run_args=[str(obj/"Vtb_rv32_protected_shared"),f"+RUN_ID={name}",f"+SOURCE_BUILD_ID={build_id}",f"+FIRMWARE_HEX={case/'firmware.hex'}",f"+DATA_HEX={case/'data.hex'}",f"+EXPECT_K={k}",f"+EXPECT_BATCH={batch}",f"+AXI_STALL_PCT={stall_pct}",f"+AXI_STALL_SEED={stall_seed}",f"+CROSS_TRACE={trace}"]+( ["+EXPECT_DOUBLE_SUBMIT=1"] if "TEST_COMPLETION_PUBLISH_POP" in scenario_define else [])+( ["+CROSS_TRACE_FLUSH"] if define or name in stateful_rows else [])
 if name in m_permutation_rows and m_permutation_rows[name]["context"]=="timing":
  run_args.append(f"+AXI_B_DELAY={m_permutation_rows[name]['delay']}")
 if name in stateful_rows:
  entry=stateful_rows[name]
  run_args += [f"+AXI_B_DELAY={entry['b_delay']}",f"+AXI_R_DELAY={entry['r_delay']}"]
  if entry["code"]==41:run_args += ["+AXI_FAIL_WRITE_ADDR=10006000","+AXI_FAIL_WRITE_COUNT=1"]
 if reset_phase=="host_w_wait":
  run_args.append("+AXI_W_READY_DELAY=64")
 if reset_phase=="prolonged_backpressure":run_args.append("+AXI_W_READY_DELAY=256")
 if reset_phase=="accepted_output_write":
  run_args += ["+AXI_W_READY_DELAY=64", "+AXI_B_DELAY=64"]
 if name == "apb_axi__case_4":
  # Request-channel stalls alone do not exercise the bridge's response-wait
  # branches. Delay both response channels in this existing read/write case.
  run_args += ["+AXI_B_DELAY=3", "+AXI_R_DELAY=3"]
 if ns.axi_b_delay is not None:
  run_args.append(f"+AXI_B_DELAY={ns.axi_b_delay}")
 if name in {"cpu_rv32m__case_1", "cpu_rv32m__case_2", "cpu_rv32m__case_3", "cpu_rv32m__case_4", "cpu_rv32m__case_6"}:
  run_args += ["+AXI_R_DELAY=64"]
 if name=="interrupts__case_2":run_args += ["+AXI_R_DELAY=16"]
 if name=="queues_configuration__case_1":run_args += ["+AXI_R_DELAY=512"]
 if name=="cache_ownership__case_5":run_args += ["+AXI_FAIL_WRITE_ADDR=10001000","+AXI_FAIL_WRITE_COUNT=1"]
 if name in {"cache_ownership__case_4","neg_access_during"}:run_args += ["+BUFFER_OFFSET=28","+AXI_R_DELAY=32"]
 env=os.environ.copy()
 if ns.code_coverage:env["VERILATOR_COVERAGE_FILENAME"]=str(case/"integration_coverage.dat")
 if ns.code_coverage:
  (case/"integration_coverage.dat").unlink(missing_ok=True)
  (case/"coverage_provenance.json").unlink(missing_ok=True)
 if define=="RV32_BUG_M_STALE_RESET":reset_phase="mdiv_busy"
 run=subprocess.run(run_args+([f"+RESET_AT={reset_at}"] if reset_at>=0 else [])+([f"+RESET_PHASE={reset_phase}"] if reset_phase!="none" else [])+( ["+EXPECT_FAULT=1"] if fault and not partial_retry else [])+( ["+EXPECT_PARTIAL_RETRY=1"] if partial_retry else []),cwd=ROOT,env=env,text=True,capture_output=True)
 text=run.stdout+run.stderr;line=next((x for x in run.stdout.splitlines() if x.startswith("PROTECTED_SHARED|")),"")
 if ns.code_coverage and (case/"integration_coverage.dat").is_file() and trace.is_file():
  write_manifest(ROOT,case,rtl_sources,simulator_version,build_id,name,run.returncode)
 if define or negative=="NEG_STALE_OWNERSHIP":
  (case/"simulation.log").write_text(text)
 expected=(run.returncode!=0) if define else ("OWNERSHIP_VIOLATION" in text) if negative in ("NEG_ACCESS_DURING","NEG_STALE_OWNERSHIP") else ("firmware result" in text) if negative else (run.returncode==0 and "status=PASS" in line)
 mutation_qualification="not_applicable"
 if define:
  try:
   from check_crossover_trace import events as parse_events
   trace_events=parse_events(trace)
  except (OSError,ValueError):
   trace_events=[]
  if define in ("PROTECTED_MUT_RETIRE_REFERENCE_RELEASE","CACHE_BUG_DIRTY_SKIP") or (define=="PROTECTED_MUT_STALE_TRANSLATION" and name=="stateful_read_permission_downgrade"):
   from run_gap_mutations import diagnose
   witnesses,diagnostics=diagnose(trace_events,define)
   qualified=bool(witnesses and diagnostics)
   mutation_qualification=diagnostics[0].split(":",1)[0] if qualified else "unqualified"
  elif define=="PROTECTED_MUT_FALSE_MAINTENANCE":
   bypass=[e for e in trace_events if e.get("kind")=="APB" and e.get("write")=="1" and e.get("addr")=="40002104" and e.get("wait_cycles")=="0"]
   starts=[e for e in trace_events if e.get("kind")=="MAINT_START"]
   qualified=run.returncode!=0 and "firmware result" in text and len(bypass)>=2 and not starts
   mutation_qualification="maintenance_fast_ack_without_command_and_firmware_detected" if qualified else "unqualified"
  elif define=="PROTECTED_MUT_CACHE_RESPONSE_CORRUPT":
   reads=[e for e in trace_events if e.get("kind")=="APB" and e.get("write")=="0" and e.get("addr")=="10004000"]
   corrupt=[e for e in trace_events if e.get("kind")=="RETIRE" and e.get("mem_addr")=="10004000" and e.get("mem_rmask") not in (None,"0") and e.get("rd_data")=="04040405"]
   qualified=run.returncode!=0 and "firmware result" in text and reads and corrupt
   mutation_qualification="cpu_observed_corrupt_cache_data" if qualified else "unqualified"
  elif define=="RV32_BUG_APB_SETUP_RETIRE":
   setup=[e for e in trace_events if e.get("kind")=="APB_SETUP"]
   premature=[r for r in trace_events if r.get("kind")=="RETIRE" and
              any(abs(int(r.get("cycle","0"))-int(s.get("cycle","0")))<=1 and
                  r.get("mem_addr")==s.get("addr") for s in setup)]
   qualified=run.returncode!=0 and bool(setup) and bool(premature)
   mutation_qualification="setup_phase_retirement_on_setup_pready" if qualified else "unqualified"
  elif define=="RV32_BUG_IRQ_BEFORE_M_RETIRE":
   irq_events=[e for e in trace_events if e.get("kind")=="IRQ_SET" and e.get("muldiv_busy")=="1"]
   premature=[e for e in trace_events if e.get("kind")=="RETIRE" and e.get("intr")=="1" and
              any(int(i.get("cycle","-1"))<=int(e.get("cycle","-2"))<=int(i.get("cycle","-1"))+2 for i in irq_events)]
   # The assertion can stop simulation on the first bad sample, before the
   # observer gets a later clock to serialize the interrupt pseudo-retire.
   # Require the IRQ-during-M event plus this specific assertion diagnostic
   # in that case; a generic abort is not sufficient mutation evidence.
   asserted="a_interrupt_after_muldiv_retire" in text
   qualified=run.returncode!=0 and bool(irq_events) and (bool(premature) or asserted)
   mutation_qualification="interrupt_retired_while_muldiv_active" if qualified else "unqualified"
  elif define=="RV32_BUG_M_STALE_RESET":
   reset=next((e for e in trace_events if e.get("kind")=="RESET_ASSERT" and e.get("muldiv_busy")=="1"),None)
   released=[e for e in trace_events if e.get("kind")=="RESET_RELEASE" and reset and int(e.get("epoch","0"))==int(reset.get("epoch","-1"))]
   qualified=run.returncode!=0 and reset is not None and "a_no_stale_muldiv_result_after_reset" in text
   mutation_qualification="stale_muldiv_state_survived_reset_epoch" if qualified else "unqualified"
  elif define=="RV32_BUG_DUP_APB_COMPLETION":
   retires=[e for e in trace_events if e.get("kind")=="RETIRE" and
            (int(e.get("insn","0"),16)&0x7f) in (0x03,0x23) and int(e.get("mem_addr","0"),16)>=0x40000000]
   setup=[e for e in trace_events if e.get("kind")=="APB_SETUP" and int(e.get("addr","0"),16)>=0x30000000]
   # The assertion detects the second retirement attempt before the duplicate
   # can create a second APB side effect. Require both the intended assertion
   # and an observed MMIO setup so a generic abort cannot qualify this mutant.
   qualified=run.returncode!=0 and bool(setup) and "a_mmio_retire_requires_access" in text
   mutation_qualification="duplicate_mmio_blocked_by_a_mmio_retire_requires_access" if qualified else "unqualified"
  elif define=="PROTECTED_MUT_BANK_REFERENCE_BYPASS":
   qualified=run.returncode!=0 and "a_referenced_generation_write_rejected" in text
   mutation_qualification="a_referenced_generation_write_rejected" if qualified else "unqualified"
  elif define in {"PROTECTED_MUT_TAG_REUSE", "PROTECTED_MUT_STALE_BANK_GENERATION",
                  "PROTECTED_MUT_EARLY_COMPLETION", "PROTECTED_MUT_LOST_IRQ",
                  "PROTECTED_MUT_STALE_TRANSLATION", "PROTECTED_MUT_WRONG_VECTOR_COUNT",
                  "PROTECTED_MUT_WRONG_RESPONSE_TAG"}:
   diagnostics={
    "PROTECTED_MUT_TAG_REUSE":"tag_lifetime_checker",
    "PROTECTED_MUT_STALE_BANK_GENERATION":"bank_generation_guard",
    "PROTECTED_MUT_EARLY_COMPLETION":"output_data_mismatch",
    "PROTECTED_MUT_LOST_IRQ":"a_irq_tracks_completion",
    "PROTECTED_MUT_STALE_TRANSLATION":"stale_tlb_entry_survived_invalidation",
    "PROTECTED_MUT_WRONG_VECTOR_COUNT":"completion_accounting",
    "PROTECTED_MUT_WRONG_RESPONSE_TAG":"response_identity",
   }
   expected_diag=diagnostics[define]
   if define in {"PROTECTED_MUT_EARLY_COMPLETION", "PROTECTED_MUT_WRONG_VECTOR_COUNT"}:
    successful=[e for e in trace_events if e.get("kind")=="COMPLETE_PUBLISH" and e.get("status")=="0"]
    committed=[e for e in trace_events if e.get("kind")=="MEM_RSP" and e.get("write")=="1" and e.get("committed")=="1" and e.get("error")=="0"]
    if define=="PROTECTED_MUT_EARLY_COMPLETION":
     qualified=run.returncode!=0 and any(not any(w.get("epoch")==p.get("epoch") and w.get("tag")==p.get("tag") and int(w.get("cycle","0"))<int(p.get("cycle","0")) for w in committed) for p in successful)
     expected_diag="success_published_before_output_commit"
    else:
     # The injected partial-output scenario has one committed vector before
     # its deliberate second-vector fault. Check the error completion's
     # architectural prefix, not only the later retry's successful count.
     partial_errors=[e for e in trace_events if e.get("kind")=="COMPLETE" and e.get("status")!="0"]
     qualified=(run.returncode!=0 and "firmware result dead5000" in text and
                any(int(p.get("vectors_done","0"))!=1 for p in partial_errors))
     expected_diag="completion_vector_count_mismatch"
   elif define=="PROTECTED_MUT_WRONG_RESPONSE_TAG":
    submitted={e.get("tag") for e in trace_events if e.get("kind")=="SUBMIT"}
    observed=[e for e in trace_events if e.get("kind")=="COMPLETE" and e.get("tag") not in submitted]
    qualified=run.returncode!=0 and bool(submitted) and bool(observed)
    expected_diag="completion_response_owner_mismatch"
   elif define=="PROTECTED_MUT_STALE_TRANSLATION":
    # The mutant suppresses TLB invalidation. Require a stale output mapping
    # to be used as a TLB hit after invalidation, then an error completion for
    # the retried one-vector suffix. A generic timeout is not enough.
    invalidates=[e for e in trace_events if e.get("kind")=="TLB_INVALIDATE"]
    post_invalidate=[e for e in trace_events if e.get("kind")=="XLATE_RSP" and
                     e.get("iova")=="80005000" and e.get("write")=="1" and
                     e.get("tlb_hit")=="1" and e.get("paddr")=="20000000" and
                     invalidates and int(e.get("cycle","0"))>int(invalidates[-1].get("cycle","0"))]
    failed_retry=[e for e in trace_events if e.get("kind")=="COMPLETE" and
                  e.get("status")=="5" and e.get("vectors_done")=="1" and invalidates and
                  int(e.get("cycle","0"))>int(invalidates[-1].get("cycle","0"))]
    qualified=run.returncode!=0 and bool(invalidates) and bool(post_invalidate) and bool(failed_retry)
    expected_diag="stale_tlb_entry_survived_invalidation"
   elif expected_diag=="output_data_mismatch":
    qualified=run.returncode!=0 and "OUTPUT_MISMATCH|" in text
   else:
    qualified=run.returncode!=0 and expected_diag in text
   mutation_qualification=expected_diag if qualified else "unqualified"
  else:
   qualified=False;mutation_qualification="unknown_mutation"
  expected=bool(qualified)
 status="PASS" if expected else "FAIL"
 realized_axi_waits=0
 trace_events=[]
 try:
  from check_crossover_trace import events as parse_trace
  trace_events=parse_trace(trace)
  realized_axi_waits=sum(event.get("kind")=="AXI_WAIT" for event in trace_events)
 except (OSError,ValueError):
  pass
 scenario_activation_value=f"{0x43520000|scenario_id:08x}" if scenario_id else ""
 scenario_activation_address=f"{scenario_activation_address:08x}" if scenario_activation_address is not None else ""
 scenario_activation_events=[event for event in trace_events
   if event.get("kind")=="RETIRE" and event.get("mem_addr")==scenario_activation_address
   and event.get("mem_wdata")==scenario_activation_value
   and int(event.get("mem_wmask","0"),16)!=0] if scenario_id else []
 reset_releases=[event for event in trace_events if event.get("kind")=="RESET_RELEASE"]
 required_activation_events=(scenario_activation_events if reset_phase=="none" else
   [event for event in scenario_activation_events if reset_releases and
    int(event.get("cycle","0"))>int(reset_releases[-1].get("cycle","0"))])
 scenario_activation_event_id=(required_activation_events[-1].get("eid","")
   or required_activation_events[-1].get("retire_order","")) if required_activation_events else ""
 if scenario_id and (not required_activation_events or
                     (reset_phase=="none" and len(required_activation_events)!=1) or
                     not scenario_activation_event_id):
  status="FAIL"
 if stall_pct and realized_axi_waits==0 and not define:
  status="FAIL"
 realized_irq_events=sum(event.get("kind")=="IRQ_SET" for event in trace_events)
 realized_interrupt_retires=sum(event.get("kind")=="RETIRE" and event.get("intr")=="1" for event in trace_events)
 realized_m_retires=sum(event.get("kind")=="RETIRE" and
    (int(event.get("insn","0"),16)&0x7f)==0x33 and
    ((int(event.get("insn","0"),16)>>25)&0x7f)==1 for event in trace_events)
 stream_retires=[];stream_opcode_counts=[0]*8
 stream_branch_taken=stream_branch_not_taken=0
 stream_m_nonzero_operands=0
 stream_shift_0=stream_shift_1=stream_shift_31=0
 if cpu_stream_range:
  stream_start,stream_end=cpu_stream_range
  stream_retires=[event for event in trace_events if event.get("kind")=="RETIRE" and
      stream_start<=int(event.get("pc","0"),16)<stream_end]
  for event in stream_retires:
   insn=int(event.get("insn","0"),16)
   if (insn&0x7f)==0x33 and ((insn>>25)&0x7f)==1:
    stream_opcode_counts[(insn>>12)&7]+=1
    if int(event.get("rs1_data","0"),16)!=0 and int(event.get("rs2_data","0"),16)!=0:
     stream_m_nonzero_operands+=1
   opcode=insn&0x7f
   if opcode==0x63:
    imm=(((insn>>31)&1)<<12)|(((insn>>7)&1)<<11)|(((insn>>25)&0x3f)<<5)|(((insn>>8)&0xf)<<1)
    if imm&(1<<12):imm-=1<<13
    target=(int(event.get("pc","0"),16)+imm)&0xffffffff
    taken=int(event.get("next_pc","0"),16)==target
    if taken:stream_branch_taken+=1
    else:stream_branch_not_taken+=1
   if opcode in (0x13,0x33) and ((insn>>12)&7) in (1,5):
    shift=(int(event.get("rs2_data","0"),16)&31) if opcode==0x33 else ((insn>>20)&31)
    if shift==0:stream_shift_0+=1
    elif shift==1:stream_shift_1+=1
    elif shift==31:stream_shift_31+=1
 scenario_retires=[];scenario_program_trace_hash="";scenario_program_event_ids="";scenario_program_rw_count=0
 if scenario_program_range:
  act_epoch=required_activation_events[-1].get("epoch","") if required_activation_events else ""
  lo,hi=scenario_program_range
  scenario_retires=[event for event in trace_events if event.get("kind")=="RETIRE" and
      event.get("epoch")==act_epoch and lo<=int(event.get("pc","0"),16)<hi and
      int(event.get("cycle","0"))<int(required_activation_events[-1].get("cycle","0"))]
  scenario_program_trace_hash=hashlib.sha256("\n".join(event.get("insn","") for event in scenario_retires).encode()).hexdigest() if scenario_retires else ""
  rw_events=[event for event in scenario_retires if int(event.get("mem_wmask","0"),16)!=0 or int(event.get("mem_rmask","0"),16)!=0]
  scenario_program_rw_count=len(rw_events)
  scenario_program_event_ids=";".join(event.get("eid","") for event in rw_events)
  if (len(scenario_retires)<12 or scenario_program_rw_count<3 or
      not scenario_program_trace_hash or not scenario_program_event_ids):
   status="FAIL"
 dma_starts=[event for event in trace_events if event.get("kind")=="DMA_ACTIVE_START"]
 dma_ends=[event for event in trace_events if event.get("kind")=="DMA_ACTIVE_END"]
 stream_m_dma_overlap=sum(any(start.get("epoch")==event.get("epoch")==end.get("epoch") and
  start.get("tag")==end.get("tag") and int(start.get("cycle","0"))<int(event.get("cycle","-1"))<int(end.get("cycle","-1"))
  for start in dma_starts for end in dma_ends)
  for event in stream_retires if (int(event.get("insn","0"),16)&0x7f)==0x33 and
  ((int(event.get("insn","0"),16)>>25)&0x7f)==1)
 realized_faults=sum(event.get("kind")=="XLATE_RSP" and int(event.get("fault","0"),0)!=0 for event in trace_events)
 cpu_stream_abi_status="NOT_APPLICABLE"
 cpu_stream_abi_address=""
 if cpu_stream_seed is not None:
  symbol_table=subprocess.run([nm,"-n",str(elf)],check=True,text=True,capture_output=True).stdout
  symbol=next((parts for line in symbol_table.splitlines()
               if (parts:=line.split()) and parts[-1]=="cpu_stream_signature"),None)
  if symbol and re.fullmatch(r"[0-9a-fA-F]+",symbol[0]):
   cpu_stream_abi_address=f"{int(symbol[0],16):08x}"
   stores=[event for event in trace_events if event.get("kind")=="RETIRE" and
           event.get("mem_addr")==cpu_stream_abi_address and int(event.get("mem_wmask","0"),16)!=0]
   cpu_stream_abi_status="PASS" if len(stores)==1 and stores[0].get("mem_wdata")=="00000001" else "FAIL"
  else:
   cpu_stream_abi_status="FAIL"
  if cpu_stream_abi_status!="PASS":status="FAIL"
 input_bus_error_evidence="not_applicable"
 if fault=="TEST_INPUT_BUS_ERROR":
  error_reads=[event for event in trace_events if event.get("kind")=="MEM_RSP" and
               event.get("write")=="0" and event.get("error")=="1" and
               event.get("addr")=="20001000"]
  bad_output_writes=[event for event in trace_events if event.get("kind")=="MEM_RSP" and
                     event.get("write")=="1" and event.get("committed")=="1" and
                     event.get("addr","").startswith("10004")]
  failed_completions=[event for event in trace_events if event.get("kind")=="COMPLETE" and
                      event.get("status")=="4" and event.get("fault_iova")=="80001000" and
                      event.get("fault_stage")=="2" and event.get("vectors_done")=="0"]
  if not error_reads or bad_output_writes or not failed_completions:
   status="FAIL"
   input_bus_error_evidence="missing_exact_read_error_or_clean_containment"
  else:
   input_bus_error_evidence="error_target_read_rejected_precise_completion_no_output_commit"
 realized_reset_epochs=len({event.get("epoch") for event in trace_events if event.get("kind")=="RESET_RELEASE"})
 chip_intervals=[];chip_start=None
 for event in trace_events:
  if event.get("kind")=="CHIPLET_EVT":
   if int(event.get("busy","0")) and chip_start is None:chip_start=int(event.get("cycle","0"))
   elif not int(event.get("busy","0")) and chip_start is not None:
    chip_intervals.append((chip_start,int(event.get("cycle","0"))));chip_start=None
 realized_service_overlap=sum(any(start<=int(event.get("cycle","-1"))<=end for start,end in chip_intervals)
  for event in trace_events if event.get("kind") in ("ACCEL_CMD","ACCEL_IN","ACCEL_OUT"))
 pop_apb_events=[event for event in trace_events if event.get("kind")=="APB" and
                 event.get("addr")=="4000002c" and event.get("write")=="1"]
 pop_wait_realized=max((int(event.get("wait_cycles","0")) for event in pop_apb_events),default=0)
 if name=="seed_099":
  publish_cycles={event.get("cycle") for event in trace_events if event.get("kind")=="COMPLETE_PUBLISH"}
  pop_cycles={event.get("cycle") for event in trace_events if event.get("kind")=="COMPLETE"}
  if (pop_wait_realized!=completion_pop_wait or not pop_apb_events or
      not (publish_cycles & pop_cycles)):
   status="FAIL"
 if ns.random and rv32m and realized_m_retires==0:
  status="FAIL"
 if cpu_stream_seed is not None and (len(stream_retires)<200 or not all(stream_opcode_counts) or
     stream_m_dma_overlap==0 or stream_m_nonzero_operands < 20 or
     stream_branch_taken == 0 or stream_branch_not_taken == 0 or
     stream_shift_0 == 0 or stream_shift_1 == 0 or stream_shift_31 == 0):
  status="FAIL"
 if ns.random and irq and (realized_irq_events==0 or realized_interrupt_retires==0):
  status="FAIL"
 if combined and realized_service_overlap==0:
  status="FAIL"
 if combined and not define and run.returncode==0:
  from check_compute_host_evidence import check_host_trace
  host_result=check_host_trace(trace,name)
  if host_result["status"]!="PASS":
   status="FAIL"
   print("COMPUTE_HOST_CHECK_FAIL|"+str(host_result["first_failure"]))
 if status=="FAIL":print(text[-2400:])
 cycles=int(re.search(r"cycles=(\d+)",line).group(1)) if line and re.search(r"cycles=(\d+)",line) else 0
 measured=int(re.search(r"benchmark_cycles=(\d+)",line).group(1)) if line and re.search(r"benchmark_cycles=(\d+)",line) else 0
 reset_evidence="none"
 if reset_phase!="none":
  reset_evidence="event:"+reset_phase
  try:
   from check_crossover_trace import events as parse_events
   evs=parse_events(trace)
   reached=phase_reached(evs,reset_phase)
  except (OSError,StopIteration,KeyError,ValueError):
   reached=False
  if not reached:
   status="FAIL";reset_evidence="not_reached:"+reset_phase
 schedule_class=("fault_recovery" if fault else "reset_injection" if reset_phase!="none" else "combined_service" if combined else "cache_ownership" if cache else "backpressure_irq_mixed")
 stimulus_origin = ("generated_cpu_instruction_stream" if cpu_stream_seed is not None else
                    "directed_scenario_program" if scenario_id else
                    "seeded_firmware_schedule" if ns.random else "fixed_firmware_matrix")
 stimulus_generator = (ROOT / "integration/protected_offload/scripts/gen_crossover_cpu_stream.py"
                       if cpu_stream_seed is not None else
                       ROOT / "integration/protected_offload/scripts/gen_crossover_scenario_program.py"
                       if scenario_id else Path(__file__))
 if FIRMWARE_IMPLEMENTATION=="independent":
  stimulus_origin="independent_firmware_driver"
  stimulus_generator=FIRMWARE_SOURCE
 if name in stateful_rows:
  stimulus_origin="seeded_multi_job_firmware" if stateful_rows[name]["code"]==80 else "stateful_directed_firmware"
  stimulus_generator=ROOT/"integration/protected_offload/scripts/stateful_cases.py"
 stimulus_instance = json.dumps({"origin": stimulus_origin, "seed": seed,
     "cpu_stream_seed": cpu_stream_seed, "scenario_id": scenario_id,
     "k": k, "batch": batch, "asid": asid, "qos": qos, "irq": irq,
     "cache": cache, "combined": combined, "stall_pct": stall_pct,
     "fault": fault or "none", "reset_phase": reset_phase,
     "stateful_knobs": stateful_rows.get(name, {})}, sort_keys=True)
 return {"scenario":name,"family":name.split("__",1)[0],"status":status,"seed":seed,"axi_stall_seed":stall_seed,"optimizer":opt,"isa":"rv32im_zicsr" if rv32m else "rv32i_zicsr","k":k,"batch":batch,"mode":"warm" if warm else "cold","asid":asid,"qos":qos,"completion_mode":"irq" if irq else "poll","cache":cache,"combined_host":combined,"schedule_class":schedule_class,"stimulus_origin":stimulus_origin,"stimulus_generator_sha256":hashlib.sha256(stimulus_generator.read_bytes()).hexdigest(),"stimulus_instance_sha256":hashlib.sha256(stimulus_instance.encode()).hexdigest(),"stimulus_abi_status":"PASS" if cpu_stream_seed is not None and status=="PASS" else "FAIL" if cpu_stream_seed is not None else "NOT_APPLICABLE","reset_at":reset_at,"requested_reset_phase":reset_phase,"reset_phase":reset_evidence,"requested_fault_mode":fault or "none","fault_mode":fault or "none","expected_negative":negative or "none","mutation_qualification":mutation_qualification,"mutation_exit_code":run.returncode if define else "","requested_axi_stall_percent":stall_pct,"requested_completion_pop_wait_cycles":completion_pop_wait,"realized_completion_pop_wait_cycles":pop_wait_realized,"realized_axi_wait_events":realized_axi_waits,"realized_irq_events":realized_irq_events,"realized_interrupt_retires":realized_interrupt_retires,"realized_m_retires":realized_m_retires,"realized_translation_faults":realized_faults,"realized_reset_epochs":realized_reset_epochs,"realized_ptw_reads":sum(event.get("kind")=="PTW_REQ" for event in trace_events),"realized_memory_writes":sum(event.get("kind")=="MEM_RSP" and event.get("write")=="1" and event.get("committed")=="1" for event in trace_events),"realized_error_responses":sum((event.get("kind")=="MEM_RSP" and event.get("error")=="1") or (event.get("kind")=="XLATE_RSP" and event.get("fault","0")!="0") for event in trace_events),"realized_completion_events":sum(event.get("kind")=="COMPLETE" for event in trace_events),"realized_service_overlap_events":realized_service_overlap,"cpu_stream_seed":cpu_stream_seed if cpu_stream_seed is not None else "","cpu_stream_source_sha256":cpu_stream_hash,"cpu_stream_start_pc":f"{cpu_stream_range[0]:08x}" if cpu_stream_range else "","cpu_stream_end_pc":f"{cpu_stream_range[1]:08x}" if cpu_stream_range else "","realized_cpu_stream_retirements":len(stream_retires),"realized_m_dma_overlap_events":stream_m_dma_overlap,"realized_m_nonzero_operand_ops":stream_m_nonzero_operands,"realized_branch_taken":stream_branch_taken,"realized_branch_not_taken":stream_branch_not_taken,"realized_shift_0":stream_shift_0,"realized_shift_1":stream_shift_1,"realized_shift_31":stream_shift_31,"mul_retirements":stream_opcode_counts[0],"mulh_retirements":stream_opcode_counts[1],"mulhsu_retirements":stream_opcode_counts[2],"mulhu_retirements":stream_opcode_counts[3],"div_retirements":stream_opcode_counts[4],"divu_retirements":stream_opcode_counts[5],"rem_retirements":stream_opcode_counts[6],"remu_retirements":stream_opcode_counts[7],"scenario_program_source_sha256":scenario_program_hash,"scenario_program_trace_sha256":scenario_program_trace_hash,"scenario_program_start_pc":f"{scenario_program_range[0]:08x}" if scenario_program_range else "","scenario_program_end_pc":f"{scenario_program_range[1]:08x}" if scenario_program_range else "","scenario_program_retirements":len(scenario_retires),"scenario_program_rw_event_count":scenario_program_rw_count,"scenario_program_witness_event_ids":scenario_program_event_ids,"scenario_activation_address":scenario_activation_address,"cycles":cycles,"benchmark_cycles":measured,"elf_sha256":hashlib.sha256(elf.read_bytes()).hexdigest(),"source_build_id":build_id,"trace":str(trace.relative_to(ROOT)),"trace_sha256":hashlib.sha256(trace.read_bytes()).hexdigest() if trace.is_file() else "","evidence":line or ("detected:"+negative if expected else "")}
matrix=[(f"k{k}_b{b}_a{a}_q{q}",k,b,a,q,int(q==15),0,"") for k in (4,8,16,32) for b in (1,4) for a in (1,17) for q in (0,15)]
cached=[(f"cache_k{k}_b{b}_q{q}",k,b,1,q,int(q==15),1,"") for k in (4,16) for b in (1,4) for q in (0,15)]
negatives=[(n.lower(),4,1,1,0,0,1,n) for n in ("NEG_SKIP_FLUSH","NEG_SKIP_INVALIDATE","NEG_LATE_DIRTY","NEG_ACCESS_DURING")]
compiler=[(f"compiler_{opt}_{'m' if m else 'i'}_{i}",k,b,1,15 if i&1 else 0,i&1,0,"",opt,m,0) for opt in ("O0","O2","Os") for m in (0,1) for i,(k,b) in enumerate(((4,1),(8,4),(16,1),(32,4),(8,1),(16,4)))]
random_rows=[]
for seed in range(100):
 rng=random.Random(0x5A170000+seed);k=rng.choice((4,8,16,32));b=rng.choice((1,4));asid=rng.choice((1,17,31));qos=rng.randrange(16);irq=rng.randrange(2)
 # Guarantee joint M/IRQ schedules while retaining M-only, IRQ-only, and
 # baseline cases across the reproducible seed family.
 m_enabled=int(bool(irq) or bool(seed&1))
 cache=int(seed%11==0)
 combined=int(seed%17==0)
 scenario_name=f"seed_{seed:03d}"
 if seed==97:
  k,b,irq,cache,combined,m_enabled=8,1,0,0,0,1
 elif seed==98:
  k,b,irq,cache,combined=4,1,0,1,0
 elif seed==99:
  # Mirror the queue depth/timing envelope of the directed publish/pop
  # stimulus while remaining a separate seeded-firmware construction path.
  k,b,asid,qos,irq,cache,combined,m_enabled=32,1,17,8,0,0,0,0
 if combined:
  # The combined lane uses a matched longer-K case so service overlap remains
  # observable after translation and input collection, not just configured.
  # It is a deterministic concurrency witness; randomized IRQ and backpressure
  # remain covered by the other seeded rows and named combined scenarios.
  k,b,irq,qos=16,4,0,8
 fault=""
 reset_phase="none"
 reset_at=-1
 # These rows are runtime crossover schedules, not merely parameter rows.
 # Fault and reset schedules are deterministic functions of the seed and are
 # mutually exclusive so every result has one unambiguous terminal oracle.
 if seed%25==9:
  fault=("TEST_INPUT_PTE_FAULT","TEST_OUTPUT_PTE_FAULT",
         "TEST_OUTPUT_PERMISSION_FAULT","TEST_PARTIAL_OUTPUT_RETRY")[(seed//25)%4]
  k,b,irq=16,2,0
 elif seed%20==7:
  reset_phase=("ptw_req","mem_req","mem_rsp","apb_wait","completion","host_w_wait")[(seed//20)%6]
  if seed==87:
   # A distinct seeded schedule exercises reset at the RV32M result boundary,
   # supplementing the directed CPU/RV32M reset case with another construction path.
   reset_phase="mdiv_result"
  elif seed==67:
   reset_phase="completion"
  elif seed==47:
   reset_phase="host_w_wait"
 if seed==14:
  # Add a seeded output page-fault containment execution.
  fault="TEST_OUTPUT_PTE_FAULT"
  k,b,irq,combined=16,2,0,0
 if seed==34:
  # Add a seeded input-memory bus-error execution, distinct from the directed
  # translation and partial-output recovery fault programs.
  fault="TEST_INPUT_BUS_ERROR"
  combined=0
 if seed==77:
  # Exercise reset while a payload response is owned but not yet retired.
  reset_phase="mem_rsp"
 random_rows.append((scenario_name,k,b,asid,qos,irq,cache,"","O2",m_enabled,seed,0,combined,reset_at,fault,reset_phase))
benchmark=[(f"bench_{'cache' if c else 'uncached'}_k{k}_b{b}_{'warm' if w else 'cold'}",k,b,1,8,0,c,"","O2",0,0,w) for c in (0,1) for k in (4,8,16,32,64) for b in (1,16,64) for w in (0,1)]
combined=[(f"combined_k{k}_b{b}",k,b,1,8,0,0,"","O2",0,0,0,1) for k,b in ((4,1),(16,4))]
reset_rows=[(f"reset_shared_on_{phase}",16,4,1,8,0,0,"","O2",0,0,0,0,-1,"",phase) for phase in ("ptw_req","mem_req","mem_rsp","apb_wait","completion","host_w_wait")]
fault_rows=[("input_pte_fault",16,2,1,8,0,0,"","O2",0,0,0,0,-1,"TEST_INPUT_PTE_FAULT"),("output_pte_fault",16,2,1,8,0,0,"","O2",0,0,0,0,-1,"TEST_OUTPUT_PTE_FAULT"),("output_permission_fault",16,2,1,8,0,0,"","O2",0,0,0,0,-1,"TEST_OUTPUT_PERMISSION_FAULT"),("partial_output_repair_retry",16,2,1,8,0,0,"","O2",0,0,0,0,-1,"TEST_PARTIAL_OUTPUT_RETRY")]
# The directed crossover lane is intentionally named by risk family.  Each
# row is an executable GCC firmware configuration, not a scenario-name proxy;
# the trace checker rejects runs that never reach the observed transaction path.
crossover_rows=[]
families=("cpu_rv32m","apb_axi","queues_configuration","translation_recovery","interrupts","cache_ownership","combined_services","reset_transport")
for family_index,family in enumerate(families):
 for item in range(6):
  k=(4,8,16,32,16,8)[item]; batch=(1,1,4,4,1,4)[item]
  if family == "cpu_rv32m" and item == 4:
   # Keep the device request active across the instruction and IRQ window.
   # The former K=4 case completed one cycle before the IRQ, which exercised
   # IRQ-during-DIV but did not prove simultaneous DMA/M execution.
   k,batch=64,1
  if family == "queues_configuration" and item == 4:
   # Keep the accepted descriptor active through the deliberate generation
   # rewrite probe later in firmware.
   k,batch=64,1
  # All CPU/RV32M rows, including the interrupt-timing cases, execute with
  # the M-capable core.  The dispatch fix prevents an IRQ from orphaning an
  # accepted multiply/divide operation.
  # Keep M enabled in selected IRQ crossover cases so the integration tests
  # the actual M-operation/interrupt dispatch boundary.
  m_case = int(family=="cpu_rv32m" or (family=="interrupts" and item in (1,4)))
  irq_case = 0 if family == "queues_configuration" and item in (1,4) else int(item in (1,4) or (family=="interrupts" and item==0))
  if family=="interrupts" and item==1:k,batch,irq_case,m_case=64,1,0,0
  if family=="interrupts" and item==2:k,batch,irq_case,m_case=16,4,1,0
  if family=="interrupts" and item==3:k,batch,irq_case,m_case=16,1,1,0
  if family=="interrupts" and item==5:k,batch,irq_case,m_case=64,1,1,1
  if family=="cache_ownership" and item==4:irq_case=0
  if family=="apb_axi" and item in (3,4):irq_case=0
  if family == "combined_services":
   # This family is for service interaction, not IRQ timing (covered by the
   # dedicated interrupts family). Use the measured overlap workload so each
   # row reaches actual simultaneous service activity; case 5 additionally
   # exercises the existing chiplet SLEEP path.
   k,batch,qos,irq_case=16,4,8,0
  if family == "queues_configuration" and item == 1:
   # A short first job followed by a full-K second job leaves one queued
   # completion while the next output is still in flight.
   k,batch,irq_case=4,1,0
  if family == "queues_configuration" and item == 0:
   k,batch,irq_case=4,1,0
  if family == "queues_configuration" and item == 2:
   k,batch,irq_case=32,1,0
  if family == "queues_configuration" and item == 3:
   # The alternate staging order reaches the first pop later; a 64-element
   # second job aligns its publish with that APB completion without relying
   # on a manually forced observer event.
   k,batch,irq_case=64,1,0
  if family == "queues_configuration" and item == 5:
   k,batch,irq_case=64,4,0
  reset_phase=("ptw_req","mem_req","accepted_output_write","completion_irq","maintenance_invalidation","prolonged_backpressure")[item] if family=="reset_transport" else "none"
  if family=="reset_transport" and item==3:irq_case=0
  if family=="combined_services" and item==5:reset_phase="combined_busy"
  if family=="cpu_rv32m" and item==5:reset_phase="mdiv_result"
  schedule_seed=1021 if family=="queues_configuration" and item==3 else 1000+family_index*10+item
  crossover_rows.append((f"{family}__case_{item+1}",k,batch,(1,17,31)[item%3],(0,8,15)[item%3],irq_case,int(family=="cache_ownership" or (family=="reset_transport" and item==4)),"","O2",m_case,schedule_seed,0,int(family=="combined_services" or (family=="interrupts" and item==2)),-1,"",reset_phase))
# Replace four translation rows with actual fault/recovery firmware paths.
for item,fault in enumerate(("TEST_READ_PERMISSION_DENIAL","TEST_WRITE_PERMISSION_DENIAL","TEST_OUTPUT_PERMISSION_FAULT","TEST_PARTIAL_OUTPUT_RETRY")):
 crossover_rows[3*6+item]=(f"translation_recovery__fault_{item+1}",16,2,1,8,0,0,"","O2",0,1300+item,0,0,-1,fault)
crossover_rows[3*6+4]=("translation_recovery__input_bus_error",4,1,1,8,0,0,"","O2",0,1310,0,0,-1,"")
crossover_rows[3*6+5]=("translation_recovery__case_6",16,2,1,8,0,0,"","O2",0,1311,0,0,-1,"TEST_PARTIAL_OUTPUT_RETRY")
crossover_rows[3*6+2]=("translation_recovery__fault_3",4,1,1,8,0,0,"","O2",0,1302,0,0,-1,"")
crossover_rows[3*6+3]=("translation_recovery__fault_4",4,1,1,8,0,0,"","O2",0,1303,0,0,-1,"")
# Fault the accelerator output translation after its command/input activity
# overlaps AES; the chiplet job must still finish independently.
crossover_rows[6*6+3]=("combined_services__case_4",16,4,1,8,0,0,"","O2",0,1063,0,1,-1,"TEST_OUTPUT_PTE_FAULT","none")
# The final APB/AXI case is a real split-channel reset: accept AW, hold W
# READY low, then assert reset from the event-triggered reset driver.
crossover_rows[1*6+5]=(*crossover_rows[1*6+5][:15],"host_w_wait")
parser=argparse.ArgumentParser();parser.add_argument("--matrix",action="store_true");parser.add_argument("--cache",action="store_true");parser.add_argument("--negative",action="store_true");parser.add_argument("--compiler",action="store_true");parser.add_argument("--random",action="store_true");parser.add_argument("--cpu-random",action="store_true",help="run generated RV32IM streams during active DMA");parser.add_argument("--count",type=int,default=100);parser.add_argument("--seed",type=int,action="append",default=[],help="restrict --random to selected seed(s), for focused schedule debug");parser.add_argument("--stall-seed",type=int,default=None,help="override deterministic AXI target backpressure seed for a focused schedule debug");parser.add_argument("--axi-b-delay",type=int,default=None,help="override target B-response delay for focused timing debug");parser.add_argument("--benchmark",action="store_true");parser.add_argument("--combined",action="store_true");parser.add_argument("--error-reset",action="store_true");parser.add_argument("--error",action="store_true");parser.add_argument("--crossover",action="store_true");parser.add_argument("--scenario",default="",help="run one named directed crossover scenario");parser.add_argument("--schema3-smoke",action="store_true",help="run a unique uncached observer/replay smoke without overwriting canonical reports");parser.add_argument("--schema3-cache-smoke",action="store_true",help="run a unique cache-enabled observer/replay smoke without overwriting canonical reports");parser.add_argument("--coverage-edges",action="store_true",help="run APB decoder/error branches intended for code coverage");parser.add_argument("--model",action="store_true");parser.add_argument("--code-coverage",action="store_true",help="instrument the integrated top and dump Verilator coverage");parser.add_argument("--define",default="");parser.add_argument("--reset-phase-override",default="",help="event-triggered reset phase override for focused mutation tests");parser.add_argument("--setup-pready-high",action="store_true",help="make the integration target advertise PREADY in APB setup for protocol stress");ns=parser.parse_args()
live_m = os.environ.get("PROTECTED_LIVE_M", "")
m_permutation_family=os.environ.get("PROTECTED_M_SWEEP","")
m_permutation_rows={}
stateful_family=os.environ.get("PROTECTED_STATEFUL","")
stateful_rows={}
if stateful_family:
 from stateful_cases import cases as stateful_cases,random_cases,ownership_negative_case
 selected=[ownership_negative_case(stateful_family)] if stateful_family in ("stateful_stale_mapping_owned_page","stateful_alias_owned_line","stateful_handler_owned_line") else random_cases() if stateful_family=="random" or stateful_family.startswith("stateful_random_") else stateful_cases()
 if stateful_family!="all":selected=[r for r in selected if r["family"]==stateful_family or r["name"]==stateful_family]
 if not selected:raise SystemExit("unknown stateful family/test")
 stateful_rows={r["name"]:r for r in selected};specs=[r["spec"] for r in selected]
elif m_permutation_family:
 from m_permutation_model import cases
 selected=cases(m_permutation_family)
 limit=int(os.environ.get("PROTECTED_M_SWEEP_LIMIT","0"))
 if limit:selected=selected[:limit]
 m_permutation_rows={row["name"]:row for row in selected}
 specs=[row["spec"] for row in selected]
elif live_m:
 if live_m not in {"dual", "sleep", "irq", "dma", "pressure", *(f"dual_{i}" for i in range(8))}:
  raise SystemExit("PROTECTED_LIVE_M must be dual, sleep, irq, or dma")
 specs=[("live_m_"+live_m,64,4,1,8,int(live_m=="irq"),0,"","O2",1,9100,0,int(live_m in {"dual","sleep"} or live_m.startswith("dual_")),-1,"","none")]
 if live_m.startswith("dual_"):SCENARIO_DEFINES["live_m_"+live_m]=(f"TEST_LIVE_M_OPCODE={live_m[-1]}",)
 if live_m=="sleep":SCENARIO_DEFINES["live_m_sleep"]=("TEST_CHIPLET_SLEEP_DURING","TEST_LIVE_M_POWER")
 if live_m=="irq":SCENARIO_DEFINES["live_m_irq"]=("TEST_LIVE_M_IRQ",)
 if live_m=="pressure":
  specs=[("live_m_pressure",4,1,1,8,0,0,"","O2",1,9100,0,0,-1,"","none")]
  SCENARIO_DEFINES["live_m_pressure"]=("TEST_COMPLETION_FIFO_PRESSURE",)
elif ns.scenario:
 specs=[row for row in crossover_rows if row[0]==ns.scenario or row[0].split("__",1)[0]==ns.scenario]
 if not specs:raise SystemExit(f"unknown crossover scenario: {ns.scenario}")
elif ns.schema3_smoke:
 specs=[("schema3_observer_smoke",4,1,1,0,0,0,"","O2",0,990001,0,0,-1,"","none")]
elif ns.schema3_cache_smoke:
 specs=[("schema3_cache_observer_smoke",4,1,1,0,0,1,"","O2",0,990002,0,0,-1,"","none")]
elif getattr(ns,"coverage_edges",False):
 specs=[("coverage_apb_edges",4,1,1,0,0,0,"","O2",0,990004,0,0,-1,"","none")]
elif ns.cpu_random:
 if ns.count<1 or ns.count>1000:raise SystemExit("--count must be in 1..1000")
 specs=[]
 for index in range(ns.count):
  stream_seed=0xC0DE0000+index
  specs.append((f"rv32m_cpu_stream_{index:03d}",16,4,(1,17,31)[index%3],(0,8,15)[index%3],0,0,"","O2",1,stream_seed,0,0,-1,"","none",stream_seed))
else:
 specs=[cached[0]] if ns.define else crossover_rows if ns.crossover else fault_rows if ns.error else reset_rows if ns.error_reset else combined if ns.combined else negatives if ns.negative else cached if ns.cache else compiler if ns.compiler else random_rows if ns.random else benchmark if ns.benchmark else matrix if ns.matrix else [matrix[0]]
if FIRMWARE_IMPLEMENTATION=="independent":
 independent_specs=[]
 for index,(label,irq,cache,fault) in enumerate((
     ("poll",0,0,""),("irq",1,0,""),("cache",0,1,""),
     ("input_page",0,0,"TEST_INPUT_PTE_FAULT"),
     ("read_permission",0,0,"TEST_READ_PERMISSION_DENIAL"),
     ("output_page",0,0,"TEST_OUTPUT_PTE_FAULT"),
     ("write_permission",0,0,"TEST_OUTPUT_PERMISSION_FAULT"),
     ("input_bus",0,0,"TEST_INPUT_BUS_ERROR"))):
  independent_specs.append(("independent_driver_"+label,4,1,1,8,irq,cache,"","O2",0,8000+index,0,0,-1,fault,"none"))
 independent_specs.append(("independent_driver_partial_retry",16,2,1,8,0,0,"","O2",0,8100,0,0,-1,"TEST_PARTIAL_OUTPUT_RETRY","none"))
 independent_specs.append(("independent_driver_m_active",64,1,1,8,0,0,"","O2",1,8101,0,0,-1,"","none"))
 independent_specs.append(("independent_driver_m_irq",64,1,1,8,1,0,"","O2",1,8102,0,0,-1,"","none"))
 independent_specs.append(("independent_driver_publish_pop",64,1,1,8,0,0,"","O2",0,8103,0,0,-1,"","none"))
 for index,phase in enumerate(("ptw_req","mem_req","mem_rsp","apb_wait","completion","host_w_wait","mdiv_result")):
  independent_specs.append(("independent_driver_reset_"+phase,16,2,1,8,0,0,"","O2",int(phase=="mdiv_result"),8200+index,0,0,-1,"",phase))
 specs=independent_specs[:1] if ns.schema3_smoke else independent_specs
if ns.random and ns.seed:
 specs=[row for row in specs if row[10] in ns.seed]
 if not specs:raise SystemExit("no random rows matched the requested seed(s)")
coverage_lane=("directed" if ns.crossover else "random" if ns.random else "cpu" if ns.cpu_random
               else "edges" if ns.coverage_edges else "cache" if ns.cache else "focused")
rows=[execute(s) for s in specs]
if ns.cpu_random:
 for row in rows:
  elf=ROOT/Path(row["trace"]).parent/"firmware.elf"
  symbols=subprocess.run([nm,"-n",str(elf)],check=True,text=True,capture_output=True).stdout
  symbol=next((parts for line in symbols.splitlines()
               if (parts:=line.split()) and parts[-1]=="cpu_stream_signature"),None)
  address=f"{int(symbol[0],16):08x}" if symbol and re.fullmatch(r"[0-9a-fA-F]+",symbol[0]) else ""
  stream_trace=ROOT/row["trace"]
  stream_events=[]
  for line in stream_trace.read_text().splitlines():
   fields=dict(part.split("=",1) for part in line.split("|")[1:] if "=" in part)
   if fields.get("kind")=="RETIRE" and fields.get("mem_addr")==address and int(fields.get("mem_wmask","0"),16):
    stream_events.append(fields)
  row["cpu_stream_abi_address"]=address
  row["stimulus_abi_status"]=("PASS" if len(stream_events)==1 and
                              stream_events[0].get("mem_wdata")=="00000001" else "FAIL")
  if row["stimulus_abi_status"]!="PASS":row["status"]="FAIL"
from check_cpu_crossover_intents import qualify as qualify_cpu_intent
from check_crossover_scenario_intents import qualify as qualify_scenario_intent
from check_crossover_trace import events as intent_events
for row in rows:
 row.update({"scenario_intent":"not_evaluated","scenario_intent_status":"NOT_RUN",
             "scenario_intent_event_ids":"","scenario_active_dma_event_ids":"",
             "scenario_intent_reason":"not_a_directed_scenario"})
 if (ns.crossover or ns.scenario) and not ns.define:
  trace_events=intent_events(ROOT/row["trace"])
  if row["family"]=="cpu_rv32m":
   intent=qualify_cpu_intent(row["scenario"],trace_events)
   intent["scenario_intent_reason"]=("observed" if intent["scenario_intent_status"]=="PASS"
                                     else "architectural_dependency_or_dma_overlap_missing")
  else:
   intent=qualify_scenario_intent(row["scenario"],row,trace_events)
  row.update(intent)
  active_pair=next(((start,end) for start in trace_events for end in trace_events
                    if start.get("kind")=="DMA_ACTIVE_START" and end.get("kind")=="DMA_ACTIVE_END" and
                    start.get("epoch")==end.get("epoch") and start.get("tag")==end.get("tag") and
                    int(start.get("cycle","0"))<int(end.get("cycle","0"))),None)
  if active_pair and not row.get("scenario_active_dma_event_ids"):
   row["scenario_active_dma_event_ids"]=";".join(e.get("eid","") for e in active_pair)
  if row["scenario_intent_status"]!="PASS":row["status"]="FAIL"
if ns.crossover or ns.scenario:
 scenario_ids={row[0]:index for index,row in enumerate(crossover_rows,1)}
 from check_crossover_trace import events as parse_trace
 for row in rows:
  scenario_id=scenario_ids[row["scenario"]]
  expected=f"{0x43520000|scenario_id:08x}"
  trace_events=parse_trace(ROOT/row["trace"])
  activations=[event for event in trace_events if event.get("kind")=="RETIRE" and
               event.get("mem_addr")==row.get("scenario_activation_address") and
               event.get("mem_wdata")==expected and int(event.get("mem_wmask","0"),16)!=0]
  releases=[event for event in trace_events if event.get("kind")=="RESET_RELEASE"]
  required_activations=(activations if row.get("requested_reset_phase")=="none" else
      [event for event in activations if releases and
       int(event.get("cycle","0"))>int(releases[-1].get("cycle","0"))])
  row["scenario_program_id"]=scenario_id
  row["scenario_activation_value"]=expected
  row["scenario_activation_event_id"]=(required_activations[-1].get("eid","") or
                                         required_activations[-1].get("retire_order","")) if required_activations else ""
  row["scenario_activation_count"]=len(activations)
  row["scenario_activation_post_reset"]=str(bool(required_activations and
      row.get("requested_reset_phase")!="none")).lower()
  if not required_activations or (row.get("requested_reset_phase")=="none" and len(activations)!=1) or not row["scenario_activation_event_id"]:
   row["status"]="FAIL"
  row["input_bus_error_evidence"]="not_applicable"
  if row.get("requested_fault_mode")=="TEST_INPUT_BUS_ERROR":
   error_reads=[event for event in trace_events if event.get("kind")=="MEM_RSP" and
                event.get("write")=="0" and event.get("error")=="1" and event.get("addr")=="20001000"]
   bad_output_writes=[event for event in trace_events if event.get("kind")=="MEM_RSP" and
                      event.get("write")=="1" and event.get("committed")=="1" and
                      event.get("addr","").startswith("10004")]
   failed=[event for event in trace_events if event.get("kind")=="COMPLETE" and
           event.get("status")=="4" and event.get("fault_iova")=="80001000" and
           event.get("fault_stage")=="2" and event.get("vectors_done")=="0"]
   row["input_bus_error_evidence"]=("precise_error_and_no_output_commit" if error_reads and
      not bad_output_writes and failed else "missing_or_inaccurate_error_containment")
   if row["input_bus_error_evidence"]!="precise_error_and_no_output_commit":
    row["status"]="FAIL"
report=ROOT/("reports/protected_cache_negative.csv" if ns.negative else "reports/protected_cache_ownership.csv" if ns.cache else "reports/protected_shared_firmware.csv")
if ns.compiler:report=ROOT/"reports/protected_shared_compiler_matrix.csv"
if ns.random:
 report=ROOT/("reports/protected_shared_random_debug.csv" if ns.seed else "reports/protected_shared_random.csv")
if ns.cpu_random:report=ROOT/"reports/rv32m_instruction_stream_random.csv"
if ns.benchmark:report=ROOT/"reports/protected_shared_benchmark.csv"
if ns.combined:report=ROOT/"reports/compute_host_summary.csv"
if ns.error_reset:report=ROOT/"reports/protected_error_reset_summary.csv"
if ns.error:report=ROOT/"reports/protected_error_summary.csv"
if ns.crossover:report=ROOT/"reports/compute_crossover_directed.csv"
if ns.scenario:report=ROOT/"reports/compute_crossover_scenario.csv"
if ns.schema3_smoke:report=ROOT/"reports/compute_crossover_schema3_smoke.csv"
if ns.schema3_cache_smoke:report=ROOT/"reports/compute_crossover_schema3_cache_smoke.csv"
if ns.define:report=ROOT/("reports/integration_mutation_"+ns.define.lower()+".csv")
if FIRMWARE_IMPLEMENTATION=="independent":report=ROOT/"reports/compute_crossover_independent.csv"
if ns.code_coverage:report=ROOT/"reports/compute_crossover_code_coverage_runs.csv"
if live_m:report=ROOT/f"reports/compute_live_m_{live_m}.csv"
if m_permutation_family:report=ROOT/f"reports/compute_m_permutation_{m_permutation_family}_runs.csv"
if stateful_family:report=ROOT/f"reports/compute_stateful_{stateful_family}_runs.csv"
if stateful_family and ns.code_coverage:report=ROOT/f"reports/compute_stateful_{stateful_family}_coverage_runs.csv"
if stateful_family and ns.define:report=ROOT/f"reports/compute_stateful_mutation_{ns.define.lower()}.csv"
with report.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
if ns.code_coverage:
 lane_report=ROOT/f"reports/compute_stateful_{stateful_family}_coverage_runs.csv" if stateful_family else ROOT/f"reports/compute_crossover_coverage_runs_{coverage_lane}.csv"
 with lane_report.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
if ns.code_coverage and ns.coverage_edges:
 edge_report=ROOT/"reports/compute_crossover_apb_edge_coverage_run.csv"
 with edge_report.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
if ns.code_coverage and ns.scenario=="queues_configuration__case_6":
 scenario_cov=ROOT/"reports/compute_crossover_queue_case6_coverage_run.csv"
 with scenario_cov.open("w",newline="") as h:w=csv.DictWriter(h,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
passed=sum(r["status"]=="PASS" for r in rows)
if ns.model:
 model_report=ROOT/("reports/rv32m_instruction_stream_random_model.csv" if ns.cpu_random else "reports/compute_crossover_model.csv" if ns.crossover else "reports/compute_crossover_scenario_model.csv" if ns.scenario else "reports/compute_crossover_schema3_smoke_model.csv" if ns.schema3_smoke else "reports/compute_crossover_schema3_cache_smoke_model.csv" if ns.schema3_cache_smoke else "reports/compute_crossover_random_debug_model.csv" if ns.random and ns.seed else "reports/compute_crossover_random_model.csv" if ns.random else "reports/protected_shared_model.csv")
 if ns.code_coverage:model_report=ROOT/f"reports/compute_crossover_coverage_model_{coverage_lane}.csv"
 if FIRMWARE_IMPLEMENTATION=="independent":model_report=ROOT/"reports/compute_crossover_independent_model.csv"
 if live_m:model_report=ROOT/f"reports/compute_live_m_{live_m}_model.csv"
 if m_permutation_family:model_report=ROOT/f"reports/compute_m_permutation_{m_permutation_family}_model.csv"
 if stateful_family:model_report=ROOT/f"reports/compute_stateful_{stateful_family}_model.csv"
 model_cmd=["python3",str(ROOT/"integration/protected_offload/scripts/check_crossover_trace.py"),"--strict-schema","--report",str(model_report)]+[str(ROOT/r["trace"]) for r in rows]
 model_result=subprocess.run(model_cmd,cwd=ROOT,check=False)
 # Bind replay results to the exact simulation row.  The trace checker owns
 # functional correctness; this join owns stimulus provenance and realized
 # knob accounting.  A replay row without its originating run metadata cannot
 # satisfy seeded-closure requirements.
 if ns.model and (ns.crossover or ns.scenario or ns.schema3_smoke or ns.schema3_cache_smoke or ns.random or ns.cpu_random or stateful_family or live_m or m_permutation_family or FIRMWARE_IMPLEMENTATION=="independent"):
  with model_report.open(newline="") as handle:
   replay_rows=list(csv.DictReader(handle))
  # The model report stores paths relative to each case directory while the
  # run report stores paths relative to the repository root. Join by the
  # unique case directory, not by their differently rooted path strings.
  by_trace={Path(row["trace"]).parent.name:row for row in rows}
  provenance_fields=("scenario","family","scenario_intent","scenario_intent_status","scenario_intent_event_ids","scenario_active_dma_event_ids","scenario_intent_reason","scenario_program_id","scenario_activation_value","scenario_activation_address","scenario_activation_event_id","scenario_activation_count","scenario_activation_post_reset","stimulus_origin","stimulus_generator_sha256","stimulus_instance_sha256","stimulus_abi_status","realized_m_nonzero_operand_ops","realized_branch_taken","realized_branch_not_taken","realized_shift_0","realized_shift_1","realized_shift_31","seed","optimizer","isa","k","batch","mode","asid","qos","cpu_stream_seed","cpu_stream_source_sha256","cpu_stream_start_pc","cpu_stream_end_pc","realized_cpu_stream_retirements","realized_m_dma_overlap_events","mul_retirements","mulh_retirements","mulhsu_retirements","mulhu_retirements","div_retirements","divu_retirements","rem_retirements","remu_retirements",
                     "completion_mode","cache","combined_host","schedule_class","fault_mode","requested_fault_mode",
                     "reset_phase","requested_reset_phase","requested_axi_stall_percent",
                     "realized_axi_wait_events","realized_irq_events","realized_interrupt_retires",
                     "realized_m_retires","realized_translation_faults","realized_reset_epochs",
                     "realized_ptw_reads","realized_memory_writes","realized_error_responses",
                     "realized_completion_events","realized_service_overlap_events","elf_sha256","source_build_id")
  provenance_fields += ("requested_completion_pop_wait_cycles","realized_completion_pop_wait_cycles")
  for replay in replay_rows:
   source=by_trace.get(Path(replay.get("trace","")).parent.name)
   if source is None:
    raise SystemExit(f"replay trace has no originating simulation row: {replay.get('trace')}")
   replay.update({key:str(source.get(key,"")) for key in provenance_fields})
   if ns.cpu_random:
    for key in ("status","retirements","m_retires","apb_completions","translation_requests",
                "memory_requests","submissions","accelerator_commands","completions","iss_status",
                "iss_instructions","accelerator_outputs_checked","trace_sha256","firmware_sha256",
                "observer_build_id","data_sha256","manifest_sha256","checker_sha256","source_sha256"):
     source[key]=str(replay.get(key,""))
  with model_report.open("w",newline="") as handle:
   writer=csv.DictWriter(handle,fieldnames=list(replay_rows[0]),lineterminator="\n")
   writer.writeheader();writer.writerows(replay_rows)
  if ns.cpu_random:
   with report.open("w",newline="") as handle:
    fields=list(dict.fromkeys(key for row in rows for key in row))
    writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n")
    writer.writeheader();writer.writerows(rows)
  if model_result.returncode and not ns.define:
   failed_cases={Path(item.get("trace", "")).parent.name for item in replay_rows
                 if item.get("status")!="PASS" or item.get("iss_status")!="PASS"}
   for row in rows:
    if Path(row["trace"]).parent.name in failed_cases:
     row["status"]="FAIL"
     row["evidence"]=(row.get("evidence", "")+"|trace_model_mismatch").strip("|")
   with report.open("w",newline="") as handle:
    fields=list(dict.fromkeys(key for row in rows for key in row))
    writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n")
    writer.writeheader();writer.writerows(rows)
   passed=sum(r["status"]=="PASS" for r in rows)
print(f"Protected shared firmware: {passed} / {len(rows)} PASS");raise SystemExit(passed!=len(rows) or (ns.model and model_result.returncode != 0 and not ns.define))
