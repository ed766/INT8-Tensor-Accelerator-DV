#!/usr/bin/env python3
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[3];BUILD=ROOT/"build/protected_offload/endpoints";BUILD.mkdir(parents=True,exist_ok=True)
sources=[ROOT/"integration/protected_offload/rtl/protected_dma_axi_adapter.sv",ROOT/"integration/protected_offload/rtl/protected_host_axi_bridge.sv",ROOT/"integration/protected_offload/rtl/protected_axi_sram.sv",ROOT/"integration/protected_offload/rtl/protected_accel_apb_config.sv",ROOT/"integration/protected_offload/sim/tb_protected_endpoints.sv"]
subprocess.run(["verilator","--binary","--sv","--timing","--assert","-Wall","-Wno-BLKSEQ","-Wno-SYNCASYNCNET","-Wno-UNUSEDSIGNAL","-Wno-PINMISSING","--top-module","tb_protected_endpoints","--Mdir",str(BUILD/"obj"),*map(str,sources)],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
run=subprocess.run([str(BUILD/"obj/Vtb_protected_endpoints")],cwd=ROOT,text=True,capture_output=True,check=True)
if "PROTECTED_ENDPOINTS|status=PASS" not in run.stdout:raise SystemExit("protected endpoints did not report PASS")
print("Protected firmware-owned endpoints: PASS")
