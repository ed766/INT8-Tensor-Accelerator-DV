# Protected Offload Address Map

Generated from `integration/protected_offload/spec/address_map.json`.

| Region | Base | Size | Use |
| --- | ---: | ---: | --- |
| `DMA_CSR` | `0x40000000` | `0x1000` | descriptor staging, completion, IRQ |
| `ACCEL_CFG` | `0x40001000` | `0x1000` | parameter-bank programming |
| `SHARED_IOVA` | `0x80000000` | `0x10000` | translated input/output buffers |
| `SHARED_PHYS` | `0x10000000` | `0x10000` | physical payload SRAM |
| `PAGE_TABLE` | `0x30000000` | `0x10000` | restricted page-table memory |
| `RESULT_MAILBOX` | `0x40001ff0` | `0x10` | firmware status and completion |
