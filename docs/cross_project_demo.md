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
| Offload, idle | 7,608 | 448 | 0 |
| Equal QoS | 7,692 | 448 | 3 |
| Higher contender QoS | 7,764 | 448 | 5 |
| Higher DMA QoS | 7,692 | 448 | 3 |

Cycles include buffer initialization, parameter loading, cache maintenance
and interrupt-driven completion handling. The table is one deterministic simulation of each
mode. The generated report includes nearest-rank p50 and p99 over two
descriptors per offload mode, from submission to firmware consumption, and
maximum observed read-address waits for the cache, DMA, page-table walker,
and contender port. These small
samples do not establish a latency distribution or arbitration bound.

The four offload modes each require a trace witness for the final input
cache-line writeback, successful descriptor completion, and the configured
contention condition. The fault case injects a write error on the third
output, verifies two committed words and an untouched suffix, and retries
the same descriptor. The false-maintenance mutation must reach a DMA read
on the final input line and be rejected by firmware. Evidence is written to
`build/protected_offload/mlp_demo` and uploaded by CI.

## Reproduce the missing-final-line bug

Run `make cross-project-demo` and inspect `skip_final_line/crossover.trace`
and `idle/crossover.trace` under `build/protected_offload/mlp_demo`.
The generated cache mutant skips cleaning only the line at `0x10001080`.
The DMA reads zero at that address on the mutant and reads a nonzero input
word in the passing control. Firmware then rejects the inference. The
evidence manifest records both event IDs and the mutant trace checksum.
