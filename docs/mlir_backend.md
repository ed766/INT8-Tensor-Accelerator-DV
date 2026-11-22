# Compiling a two-layer model for the INT8 accelerator

**DMA chaining saved 3.5–8.7% under AXI contention across three models
imported through torch.fx.** Both schedules were checked byte for byte
against PyTorch. The fixed reference fixture also saved 8.8% at idle. The compiler kept the intermediate activation
in shared memory and passed its address directly to the second DMA descriptor.
This removed a CPU copy, 64 bytes of cache writeback, and two cache
maintenance operations. Both schedules produced exactly the same bytes as
the PyTorch reference.

| Schedule | RTL cycles | Descriptors | DMA payload | Staging writeback | Cache operations |
| --- | ---: | ---: | ---: | ---: | ---: |
| CPU staging | 8,364 | 2 | 448 B | 64 B | 4 |
| DMA chaining | 7,626 | 2 | 448 B | 0 B | 2 |
| CPU consumer present, staging retained | 8,833 | 2 | 448 B | 64 B | 4 |

The fixed-fixture comparison uses the idle fabric and the same RTL, quantized weights,
inputs, and firmware runtime. Cycles include buffer preparation, configuration,
cache maintenance, and interrupt-driven completion. The measurements are
simulation cycles.

## What the compiler changes

The [input MLIR](../compiler/mlir/model.mlir) describes the fixed
16→4→4 Linear/ReLU/Linear workload. A C++ MLIR pass validates the graph and
lowers it to calls into the firmware scheduling ABI. The same pass emits
a C include from those calls so the measured firmware executes the generated
schedule. The FX importer supplies model geometry, weights, biases, shifts, inputs,
and PyTorch expected results. The backend supports batches of 4, 8, or 16
and input widths of 4, 8, 16, 32, or 64, with four outputs per layer.
It accepts a straight-line two- or three-layer graph and the existing signed INT8
quantization contract.

| Staged schedule | Chained schedule |
| --- | --- |
| DMA layer 1 into hidden buffer | DMA layer 1 into hidden buffer |
| Invalidate and copy hidden data through the CPU, then clean staging buffer | Preserve the hidden buffer as the second DMA input |
| DMA layer 2 from staging buffer | DMA layer 2 from hidden buffer |
| Invalidate output before CPU readback | Invalidate output before CPU readback |

The runtime consumes the first descriptor's completion before submitting the
second. Chaining requires a single SSA use of the intermediate in the supported
graph. A recognized CPU observer forces staging and runs after invalidation.
Unknown consumers, unsupported shapes, and unsupported rounding fail lowering.
The RTL runner checks the actual second-layer input addresses, successful
completions, cache writebacks before handoff, and exact PyTorch equality for
intermediate and final data.

## FX models under contention

| Batch × input width | Idle staged → chained | Contended staged → chained | Contended cycles saved |
| --- | ---: | ---: | ---: |
| 4 × 8 | 4,596 → 4,187 | 4,614 → 4,211 | 403 (8.7%) |
| 8 × 32 | 10,003 → 9,520 | 10,087 → 9,604 | 483 (4.8%) |
| 16 × 64 | 20,772 → 20,034 | 21,114 → 20,382 | 732 (3.5%) |

The contender issues four-beat reads at QoS 15 while descriptor DMA uses
QoS 8. All six contended runs observed concurrent DMA and contender
requests and a five-cycle maximum DMA read-address wait. Each schedule
uses two descriptors. Chaining halves cache maintenance from four
operations to two and preserves DMA payload for a given shape.
The percentage gain shrinks on the largest shape because total execution
takes more cycles even though chaining saves more cycles in absolute terms.

## Reproduce

Use LLVM/MLIR 19 development libraries, FileCheck, a C++17 compiler, and the
existing demo dependencies (Verilator, RISC-V GCC/binutils, and PyTorch).

```sh
cmake -S compiler/mlir -B build/int8-mlir -DMLIR_DIR=/usr/lib/llvm-19/lib/cmake/mlir
cmake --build build/int8-mlir
python3 compiler/mlir/compare.py build/int8-mlir/int8-opt /usr/lib/llvm-19/bin/FileCheck
```

The command runs FileCheck on all three schedules, checks rejection of invalid
input, and writes lowered MLIR, firmware includes, trace logs, and
`comparison.csv` and `fx_comparison.csv` under `build/int8-mlir/rtl`.

## Three layers and buffer lifetime

**Chaining reduced simulated cycles by 9.4%** for a 16-sample
32→4→4→4 FX model under AXI contention. The same four-beat QoS 15
contender ran against QoS 8 DMA in both schedules. Firmware and trace
checks matched the PyTorch bytes at both intermediate buffers and at
the final output.

| Schedule | RTL cycles | DMA payload | Descriptors | Cache operations |
| --- | ---: | ---: | ---: | ---: |
| Stage both intermediate activations | 15,609 | 832 B | 3 | 6 |
| Chain both intermediate activations | 14,145 | 832 B | 3 | 2 |

Every DMA call in this ABI waits for the IRQ and consumes the completion.
The lowered calls distinguish the two producer buffers and the reusable
staging slot. The verifier checks producer completion, invalidation before
CPU reads, cleaning before DMA reads of staged data, and the consumer
that releases the slot. The staged schedule reuses the slot after layer
two completes. The chained schedule passes each producer buffer directly
to its consumer. The third layer reloads the first parameter bank after
the earlier completion.

The regression inserts a copy of the middle buffer into the staging slot
before layer two reads the first activation. `int8-opt --verify-schedule`
rejects the modified IR with `premature reuse of live staging buffer`.
A test-only firmware schedule executes the same overwrite and cleans the
slot so the wrong bytes reach DMA. The first layer-two read at
`0x10009000` returns the middle buffer's guard word `0xa53c79e1`.
Firmware rejects the output.

The existing reproduction command runs both schedules and the negative
control. The MLIR CI job publishes `three_layer_comparison.csv`, the
lowered schedules, and `premature_reuse.txt` with the rejection and first
incorrect trace event. The lifetime model covers straight-line two- and
three-layer graphs and the blocking firmware ABI.
