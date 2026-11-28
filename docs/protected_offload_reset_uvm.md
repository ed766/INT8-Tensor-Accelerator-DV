# Reset recovery during protected INT8 offload

This regression runs bare-metal RV32 firmware against the protected DMA,
INT8 accelerator, and shared AXI fabric. A UVM virtual sequence configures
target backpressure and resets the subsystem while an original descriptor
is active or its completion is awaiting acknowledgement. The firmware
boots again, restores its mappings and accelerator configuration, and
submits a fresh descriptor with the original tag.

## Reset contract

The same reset is applied to the processor, accelerator and DMA service,
IOMMU and page walker, AXI adapters and fabric, interrupt aggregator, and
SRAM target interfaces. This test uses the uncached, non-chiplet
configuration. The SRAM target forgets accepted addresses and pending
responses on reset. Write data accepted by the SRAM target before reset
has already updated memory according to its byte strobes and survives.
An accepted write address alone leaves memory untouched. The backing SRAM
arrays, including page tables, output buffers, and a firmware boot cookie,
retain their data. Cold boot initializes the arrays.

The fabric discards its outstanding routing and write ownership state.
The shared-reset contract covers endpoints that reset with the fabric.
An external endpoint that survives reset and later responds would
require a separate isolation or drain contract.

Firmware checks the completion queue and IRQ status before reinitializing
the subsystem. It reverses the input sample order on reboot, which yields
a different expected byte sequence with the same weights and tag. The DUT
must produce a single successful replacement completion, and firmware
must consume it and acknowledge the interrupt.

## Verification plan

| Reset stage | Evidence at injection | Required recovery |
| --- | --- | --- |
| First input read | The SRAM target accepted the first DMA AR and has a delayed response pending. No DMA read response or output write has completed. | No old response, completion or interrupt appears during reboot. Only the replacement descriptor completes. |
| Partial output | The target accepted at least one output W beat. A later write has an accepted AW and stalled W. | The committed prefix matches PyTorch. Every untouched output word and both guards retain their sentinel across reset. The replacement job produces the complete reversed-order output. |
| Pending IRQ | Every output word committed and the completion was published. The IRQ is pending and firmware has performed neither a pop nor an acknowledge. | Reset clears the old completion and IRQ. The same tag is accepted again and publishes exactly one new completion. |
| Committed write, B response pending | The SRAM accepted the first output W beat and updated the expected word. The SRAM still holds the delayed DMA B response, and the DMA has accepted zero B responses. | The committed word and both guards survive reset. The SRAM drops the pending response, and the DMA sees no old response or completion. Firmware resubmits the same tag and produces the complete reversed-order output. |

The testbench counts target handshakes independently of the virtual
sequence and checks retained SRAM before reset and after release.
Assertions check for stale DMA responses, completion and IRQ before
resubmission, duplicate publications, and an IRQ or completion consume
without a fresh publication. The cross over reset stage, observed
outstanding operation and successful same-tag recovery has four legal
bins. Each is represented by a named SystemVerilog cover property and a
case-level trace witness.

The directed runs reset at the first eligible edge and hold reset for
three cycles. The constrained-random runs vary the offset within the
window, the reset length, and the SRAM delay for the read response, write
data, and write response cases.
The pending IRQ window stays open because the original firmware boot
masks CPU interrupt handling. A test-only DMA mutation preserves the
completion count across reset, and the runner requires the stale-state
assertion to catch it after reproducing the pending-IRQ window.

## Local offload reset with the system live

The integration top accepts a synchronous `offload_reset_req` pulse.
The pulse resets the offload service, including DMA queues, accelerator,
IOMMU, and configuration registers. The RV32 hart, AXI fabric, DMA and
page-walk adapters, SRAM, and interrupt aggregator keep running. An
adapter keeps ownership of any transaction it already latched, finishes
its AXI handshakes, and consumes its terminal response at the adapter
boundary. The response is masked from the offload service. The reset
controller releases the service only after both adapters return to
idle. DMA/configuration APB accesses wait until release.

Firmware polls the read-only status register at `0x40001fdc`. Bit 0
indicates reset/drain in progress and bit 1 indicates that recovery can
start. A new request clears bit 1. The contract assumes that accepted AXI
transactions eventually receive a terminal response. The hart clears
the live IRQ aggregator's sticky accelerator status before submitting
replacement work.

| Local reset window | Required evidence |
| --- | --- |
| Accepted DMA read with delayed R | Exactly one old R handshake drains while the engine is held in reset. No old response reaches the engine. The live hart resubmits the same tag and receives one fresh completion. |
| Committed output write with delayed B | Exactly one old B handshake drains. The committed word matches PyTorch, the untouched suffix and guards retain their values, and the replacement completes with the expected bytes. |
| A completed, B active, C queued | A has one unconsumed completion and a complete output, B has an accepted read with delayed R, and C is waiting. Reset cancels the old queue entries and completion record. Firmware resubmits all three tags, including A, because it had not consumed its completion. Each fresh job has exactly one checked completion and a distinct expected output sequence. |

The local-reset scoreboard checks all destination buffers on both sides
of the reset, including A's retained output and the untouched B and C
buffers. It counts AXI handshakes during drain, verifies hart retirement
and a retained `mscratch` value, and checks replacement tags, status,
vector counts, and output bytes. The three local bins have their own
native coverage properties and are reported separately from the shared
reset bins.

## Reproduce

Use a PyTorch-enabled Python, an RV32-capable RISC-V GCC toolchain, a
Verilator build with assertions and user coverage, Z3 for constrained
randomization, and the CHIPS Alliance UVM library. Set `UVM_HOME` to that
library's `src` directory and `VERILATOR_UVM` to the Verilator binary.
The local qualification used Verilator 5.048 and
[`uvm-verilator` revision `656f20d`](https://github.com/chipsalliance/uvm-verilator/commit/656f20d087370a7c742e00188d20bbf30fa95339).

```sh
make protected-offload-uvm
```

The runner writes `build/protected_offload/reset_uvm/reset_cross.csv`,
the companion `local_reset_cross.csv`, the firmware images, the PyTorch golden words, and per-case simulator
logs, traces, and coverage databases. A nominal run qualifies when the
output checker passes, UVM reports zero errors and fatals, and only the
expected native cross bin is hit. The negative control has its own row
and must fail on the named assertion.

For the delayed-B case, the CSV also records the pre-reset DMA B
handshake count and the event ID of the outstanding write request. The
testbench verifies the committed word directly in SRAM, since the DMA
trace reports write completion only after the response arrives.
