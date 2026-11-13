# Cross-project INT8 demo

Download [trace_replay.html](trace_replay.html) and open it in a browser for the
fault and retry replay. Regenerate it after running the demo with
`python3 integration/protected_offload/scripts/export_mlp_replay.py`.

Run `make cross-project-demo` with Verilator, RV32-capable GCC/binutils,
and PyTorch installed. The demo uses the RV32IM core from the Chiplet SoC,
the L1 data cache, the AXI QoS fabric and IOMMU, and the INT8 accelerator.
The [provenance lock](../integration/protected_offload/provenance.lock.json)
records the imported revisions.

Firmware evaluates 16 inputs through a quantized 16→4→4 MLP. The accelerator
path cleans dirty buffers before handing them to DMA, chains the hidden
buffer directly into the second descriptor, and invalidates stale CPU
copies before reading results. Firmware compares all 128 hidden and final
bytes and verifies guard words. The host checker independently compares
committed DMA data to the PyTorch oracle.

| Local simulation mode | Firmware cycles | DMA payload bytes | DMA max AR wait |
| --- | ---: | ---: | ---: |
| RV32IM scalar | 94,997 | 0 | — |
| Offload, idle | 7,472 | 448 | 0 |
| Equal QoS | 7,549 | 448 | 3 |
| Higher contender QoS | 7,615 | 448 | 5 |
| Higher DMA QoS | 7,549 | 448 | 3 |

Cycles include buffer initialization, parameter loading, cache maintenance
and completion polling. The table is one deterministic simulation of each
mode. The generated report includes the minimum and maximum over two
descriptors per offload mode and maximum observed AR waits. These small
samples do not establish a latency distribution or arbitration bound.

The four offload modes each require a trace witness for the final input
cache-line writeback, successful descriptor completion, and the configured
contention condition. The fault case injects a write error on the third
output, verifies two committed words and an untouched suffix, and retries
the same descriptor. The false-maintenance mutation must reach a DMA read
on the final input line and be rejected by firmware. Evidence is written to
`build/protected_offload/mlp_demo` and uploaded by CI.
