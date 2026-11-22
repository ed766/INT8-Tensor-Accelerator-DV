# Compiling a two-layer model for the INT8 accelerator

**DMA chaining cut simulated firmware cycles by 8.8%** for the same
quantized model and 16 inputs. The compiler kept the intermediate activation
in shared memory and passed its address directly to the second DMA descriptor.
This removed a CPU copy, 64 bytes of cache writeback, and two cache
maintenance operations. Both schedules produced exactly the same bytes as
the PyTorch reference.

| Schedule | RTL cycles | Descriptors | DMA payload | Staging writeback | Cache operations |
| --- | ---: | ---: | ---: | ---: | ---: |
| CPU staging | 8,364 | 2 | 448 B | 64 B | 4 |
| DMA chaining | 7,626 | 2 | 448 B | 0 B | 2 |
| CPU consumer present, staging retained | 8,833 | 2 | 448 B | 64 B | 4 |

The comparison uses the idle fabric and the same RTL, quantized weights,
inputs, and firmware runtime. Cycles include buffer preparation, configuration,
cache maintenance, and interrupt-driven completion. The measurements are
simulation cycles.

## What the compiler changes

The [input MLIR](../compiler/mlir/model.mlir) describes the fixed
16→4→4 Linear/ReLU/Linear workload. A C++ MLIR pass validates the graph and
lowers it to calls into the firmware scheduling ABI. The same pass emits
a C include from those calls so the measured firmware executes the generated
schedule. The model weights and input vectors come from the existing PyTorch
fixture. This prototype accepts a fixed model shape and quantization contract.

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
`comparison.csv` under `build/int8-mlir/rtl`.
