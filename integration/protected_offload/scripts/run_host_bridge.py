#!/usr/bin/env python3
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build/protected_offload/host_bridge"
BUILD.mkdir(parents=True, exist_ok=True)
subprocess.run([
    "verilator", "--binary", "--sv", "--timing", "--assert", "-Wall",
    "-Wno-BLKSEQ", "-Wno-UNUSEDSIGNAL", "-Wno-SYNCASYNCNET",
    "--top-module", "tb_protected_host_axi_bridge",
    "--Mdir", str(BUILD / "obj"),
    str(ROOT / "integration/protected_offload/rtl/protected_dma_axi_adapter.sv"),
    str(ROOT / "integration/protected_offload/rtl/protected_host_axi_bridge.sv"),
    str(ROOT / "integration/protected_offload/sim/tb_protected_host_axi_bridge.sv"),
], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
run=subprocess.run([str(BUILD/"obj/Vtb_protected_host_axi_bridge")],cwd=ROOT,text=True,capture_output=True,check=True)
if "PROTECTED_HOST_BRIDGE|status=PASS" not in run.stdout:
    raise SystemExit("host bridge did not report PASS")
print("Protected host APB-to-AXI bridge: PASS")
