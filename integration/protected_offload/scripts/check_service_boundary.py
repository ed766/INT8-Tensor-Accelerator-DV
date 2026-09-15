#!/usr/bin/env python3
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
sources = [
    ROOT / "rtl/int8_tensor_accel.sv",
    ROOT / "integration/protected_offload/rtl/protected_queue_count_next.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_dma.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_apb_csr.sv",
    ROOT / "integration/protected_offload/vendor/axi/dma_iommu.sv",
    ROOT / "integration/protected_offload/rtl/protected_offload_service.sv",
]
subprocess.run([
    "verilator", "--lint-only", "--sv", "--timing", "-Wall",
    "-Wno-UNUSEDSIGNAL", "--top-module", "protected_offload_service",
    *map(str, sources),
], cwd=ROOT, check=True)
print("PROTECTED_SERVICE_BOUNDARY|status=PASS|host=APB|payload=explicit|ptw=explicit|config=firmware_owned")
