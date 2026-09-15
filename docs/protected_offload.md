# Protected Accelerator Offload

The integration now includes a CPU-independent `protected_offload_service`
boundary with explicit APB control, payload-memory, page-walk, TLB
invalidation, firmware configuration, interrupt, and performance interfaces.
`make protected-offload-service-check` verifies that boundary elaborates from
the provenance-locked components. This is a prerequisite, not a claim that the
legacy firmware harness already owns shared-memory or page-table initialization;
that harness remains separately identified where it uses behavioral memory.

This optional integration lane turns the tensor engine into a memory-to-memory
device. Software snapshots a descriptor through APB, the four-entry DMA queue
translates each input and output address, fetches a complete vector, streams it
through the existing INT8 engine, waits for the output write response, publishes
a completion record, and holds a level interrupt until software pops that record.

![Protected offload architecture](images/protected_offload_architecture.svg)

## Measured Evidence

| Evidence | Result | What actually ran |
| --- | ---: | --- |
| Directed RTL scenarios | `40 / 40` | Descriptor geometry, backpressure, faults, completion pressure, ASIDs, QoS |
| Seeded RTL scenarios | `100 / 100` | Deterministic K, batch, context, stall, fault, and completion-hold combinations |
| Independent trace replay | `205 / 205` | Python orchestration plus compiled C++ model, 5,182 ordering/numerical/accounting checks |
| Functional points | `77 / 77` | Event-derived controller, operand, protection-boundary, recovery, and concurrency intent |
| Interaction crosses | `64 / 64` | Dedicated same-execution knob and event combinations |
| RTL mutations | `10 / 10` | Expected failures in numerical, context, permission, ordering, and IRQ paths |
| Guard/queue/AXI/IOMMU checks | `4 / 4` | Descriptor legality, simultaneous queue accounting, lane/error, and translation/TLB cases |
| Solver properties | `10 / 10` | Eight bounded AXI-adapter checks plus two queue-accounting proofs; reachable covers |
| GCC firmware execution | `24 / 24` | Eight workflows at `-O0`, `-O2`, and `-Os` booted on RV32 and completed through APB/DMA |
| Code coverage | raw `289 / 341` (`84.75%`); reviewed `289 / 289` (`100%`) | 52 declaration/interface/case-attribution exclusions remain denominator-visible |
| Performance comparison rows | `45 / 45` | Scalar RV32I, MMIO stream, and autonomous DMA cycle evidence |

| Executable job timeline | Device-cycle scaling |
| --- | --- |
| ![Normalized protected-offload event timeline](images/protected_offload_timeline.svg) | ![Measured protected DMA cycles](images/protected_offload_performance.svg) |

The checked-in GCC matrix separately records build and execution status, ELF
hash, instruction image size, simulated cycles, and retired instructions. Each
program boots on the provenance-locked RV32 core, programs the descriptor CSRs
through APB, waits for the level completion interrupt, validates the completion,
and publishes a result mailbox checked against output memory. The executable
path uses the locked educational IOMMU, performs two-level page walks, and
records TLB activity per firmware run. Cache-maintenance ownership tests remain
explicitly deferred.

## Descriptor and Completion Contract

The doorbell snapshots input/output IOVAs, independent strides, `K`, batch,
tag, ASID, parameter bank/generation, and QoS. Invalid geometry, duplicate live
tags, queue pressure, and stale parameter generations are rejected before work
starts. The completion records tag, status, ASID, faulting IOVA, failing stage,
and the number of fully acknowledged output vectors.

Each vector follows this ordering:

1. Translate and fetch all `K/4` input words.
2. Issue one tagged accelerator command and exactly `K/4` stream chunks.
3. Collect one four-byte result.
4. Translate the output and issue a byte-lane-correct memory write.
5. Wait for the write response before incrementing `vectors_done`.
6. Publish one completion after the final acknowledged vector.

## Protection and Error Semantics

The executable controller carries the descriptor ASID and QoS with every
request and stops before issuing an accelerator command when input translation
or memory access fails. Output translation and write failures publish distinct
stage/status information. Successful earlier vectors remain committed; the lane
does not claim rollback of an AXI write that returns an error.

Descriptor guards reject invalid geometry, stale generation, overlap, and
32-bit address overflow. The descriptor queue is separately stressed for simultaneous dequeue/enqueue,
full occupancy, ordering, and backpressure. The imported educational IOMMU is
integrated in the RV32 firmware path and is also separately exercised for page
walk, TLB hit, ASID separation, invalidation, and permission denial. The DMA-to-AXI adapter is
separately exercised for lower/upper 32-bit lanes, independent AW/W waits,
read/write responses, and error propagation. A fully wired four-master QoS
fabric and cached-host ownership path are not claimed by this release.

## Reviewer Commands

```bash
make protected-offload-smoke
make protected-offload-service-check
make protected-offload-components
make protected-offload-directed
make protected-offload-firmware
make protected-offload-random
make protected-offload-model-check
make protected-offload-coverage
make protected-offload-formal
make protected-offload-mutations
make protected-offload-performance
make protected-offload-release-check
```

This is behavioral open-source pre-silicon evidence. It is not AXI compliance,
IOMMU certification, production firmware, cache coherence, or implementation
signoff. The current compiled workflows poll the level IRQ status through APB;
trap-handler-driven completion and recovery remain outside this lane.
