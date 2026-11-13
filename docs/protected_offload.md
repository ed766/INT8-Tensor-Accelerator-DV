# Protected Accelerator Offload

## Operand and IRQ Timing Matrix

`make compute-m-permutation-check` adds finite, separately reported closure:
eight opcodes, six mutually exclusive operand classes, and four live service
contexts (DMA, AES/INT8 overlap, SLEEP, full completion FIFO), with two distinct
operand samples per bin and explicit signed overflow cases. Both samples come
from one generator; they are not independent stimulus implementations.

The IRQ sweep qualifies before/early/middle/late/finalization/result/after
phases from actual observed arithmetic state, not requested delays. It checks
real accelerator completion interrupts and precise handler entry after M
retirement. Strict ISS replay, independent arithmetic predictions, numerical
results, and AES checks remain required. Run and witness counts regenerate in
the [evidence dashboard](compute_crossover_evidence_dashboard.md).

This does not close exhaustive operands, timer sources, masking combinations,
reset timing, or all power-state permutations. Those are distinct test models.

## Live RV32M Service Crosses

`make compute-live-m-check` is supplemental to the canonical crossover lane.
It executes separate GCC firmware for active DMA, eight opcode-specific
AES/INT8 overlaps, SLEEP/resume, device IRQ during arithmetic, and full
completion-FIFO pressure. The 32 opcode/service bins cite actual retirement
event IDs; the IRQ witness checks retirement before handler entry and exact
`mepc`. Strict ISS/transaction/numerical replay and independent AES stream and
destination-memory checks are required, not just firmware mailbox success.

Reports: [scenarios](../reports/compute_live_m_interactions.csv) and
[crosses](../reports/compute_live_m_cross_coverage.csv). These sampled windows
do not claim exhaustive operands, reset phases, configuration-reference or
power-state crosses. The fixed IRQ schedule delays AXI B responses by nine
cycles; if that no longer reaches arithmetic, the lane fails rather than
counting the requested timing as evidence.

The protected-offload RV32 snapshot is imported from immutable authoritative
Git bytes using `integration/protected_offload/scripts/import_rv32_snapshot.py
--commit <commit>`. The importer rejects dirty source divergence. Run
`check_provenance.py --authoritative-source <chiplet-repository>` to verify
the imported bytes against that commit in addition to the normal hash check.

## Python Dependencies

Use the same Python environment for simulation runners and their reference
models. Install `requirements.txt` for PyTorch and, separately,
`python -m pip install -r requirements-verification.txt` for the independent
AES oracle used by the combined-host checker. CI installs both dependency
sets; a passing firmware mailbox does not replace this numerical check.

`make compute-crossover-clean-check` snapshots both local repositories using
temporary Git indexes, checks out those snapshots in isolated directories,
and runs the complete strict crossover target with fresh DUT builds and traces.
Only pinned third-party tool caches are shared. The source branches and user
indexes are unchanged. The generated `build/clean-checkout-*/audit.json` records
source/tree identities and the command result; `closure.log` retains failures.
This can be a lengthy run. A local snapshot pass does not establish that the
GitHub workflow reproduced it. Local audit snapshot objects are not release
commits.

The latest full isolated run passed with exit code zero. Its source-tree hashes
and measured results are recorded in
[`compute_crossover_clean_checkout.csv`](../reports/compute_crossover_clean_checkout.csv).
It regenerated all 257 instrumented executions, qualified all 12 mutations,
executed required Spike and ACT4 RV32IM checks, and passed 16 formal groups and
16 cover tasks. This closes local executable reproduction, not remote CI:
the tested chiplet prerequisites are published at
`4d1f1639947822e0260ecdab50d3b9bca969d01f` and the workflow now pins that revision.
Its remote result remains pending. Generated CSV baselines have been reconciled;
raw solver outputs are ignored and new tasks write under `build/`.
New integration control reaches raw 95.97% line and 91.58% branch coverage;
the broader integrated totals remain 83.60% and 77.43%, respectively.

The integration now includes a CPU-independent `protected_offload_service`
boundary with explicit APB control, payload-memory, page-walk, TLB
invalidation, firmware configuration, interrupt, and performance interfaces.
`make protected-offload-service-check` verifies that boundary elaborates from
the provenance-locked components. The same gate exercises the APB-to-AXI host
bridge, lower/upper 64-bit SRAM lanes, accelerator configuration backpressure,
and set-dominant interrupt aggregation. These are prerequisites, not a claim that the
legacy firmware harness already owns shared-memory or page-table initialization;
that harness remains separately identified where it uses behavioral memory.

The newer `protected-offload-shared-matrix` lane is executable firmware-owned
evidence. GCC firmware writes the two-level page table, tensors, output storage,
weights, biases, scaling, and bank generation through the CPU host interface.
The host, DMA payload, and IOMMU page walker then traverse distinct masters of
the actual QoS fabric. Its `32 / 32` matrix crosses K, batch size, ASID, QoS,
and polling versus machine-interrupt/WFI completion. A companion matrix passes
`36 / 36` executions across `-O0/-O2/-Os` and RV32I/RV32IM. The seeded shared
integration passes `100 / 100` seeded executions with strict trace replay.
Those executions are schedule/workload evidence; they do not close a
transaction-level cross-coverage denominator.
Six seeds are reserved as deterministic combined-service overlap witnesses
with IRQ disabled and `0%` requested AXI backpressure; the other 94 rows retain
varied IRQ/backpressure schedules. Each combined row still fails unless the
observer records actual simultaneous AES/INT8 service activity.

The cached lane inserts the provenance-locked 4-KiB L1 only on the CPU payload
path. Firmware explicitly flushes before device ownership and invalidates before
CPU reuse. It passes `8 / 8` positive cases, while `4 / 4` intended-negative
cases prove that omitted maintenance, a late dirty writeback, and CPU access
during device ownership are detected.

### Crossover Closure

`make compute-crossover-directed` runs `48 / 48` GCC-built configurations
organized by CPU/RV32M, APB/AXI, queue/configuration, translation/recovery,
interrupt, cache-ownership, combined-service, and reset/transport risk
families. A verification-only observer emits retirement, completed APB,
translation, memory, accelerator, completion, interrupt, maintenance, and
reset-epoch events from the actual integration top. The independent replay
requires every response to have an accepted request, every completion to have
an accepted descriptor, no live transaction at firmware completion, and no
cross-epoch response. The checked-in [coverage report](../reports/compute_crossover_coverage.md)
and [evidence dashboard](compute_crossover_evidence_dashboard.md)
separates historical family/event reachability (`16 / 16`) from executable
crossover predicates (`15 / 15`) and trace-correlated event-cross bins
(`53 / 53`). Each bin has explicit event IDs and trace hashes; high-risk bins
have two independently constructed witnesses. The publish/pop bin specifically
uses shared and separately authored firmware drivers, with a verification-only
APB wait policy accounting for the registered CSR pop pulse, to hit same-edge
publication and consumption. The independent driver suite passes `19 / 19`
strict model replays. Adding the second witness exposed
and fixed an over-conservative model check that had blocked a completion while
an unrelated descriptor still had a write outstanding; the final checker
accounts writes by descriptor tag and still requires that descriptor's own
output responses before publication/consumption. These observed bins are separate
from the accelerator's canonical functional-coverage denominator and are not
an exhaustive Cartesian product. The strict checker is
qualified by `25` adversarial traces and `6` valid controls. The prerequisite
component suite includes the machine-timer APB boundary (`5 / 5`).
The supported seeded crossover generator includes RV32M-plus-interrupt rows;
the shared dispatch fix is exercised by the directed and seeded matrices.
These 48 directed rows are configurations in eight risk families, not 48
independently authored firmware programs. The 100 random rows are descriptor/
integration workloads, not the separate 100-seed CPU instruction-stream lane.
Predicate reachability is not equivalent to the planned transaction-level
cross-coverage closure.

The controller keeps a software tag reserved through unread completion and
rejects configuration-bank commits while queued or active work references that
bank. A consumed completion can be retried with the same tag on a subsequent
cycle. The optional chiplet CSR window is driven through an explicit APB-to-CSR
adapter, replacing the prior request-phase shortcut and preventing a
PREADY-high setup phase from creating a side effect.

### Combined Host and Reset Evidence

`make compute-host-check` runs two GCC-built firmware images on **one** RV32I
core. The firmware initializes and verifies the protected INT8 DMA job through
the four-master AXI fabric, then stages a four-word chiplet DMA job through the
optional chiplet CSR window at `0x5000_0000`. A separate trace checker
compares both AES output words against the independent AES golden model and
requires observed accelerator events during an active chiplet interval (also
specifically for K16/B4). The checked-in
[`compute_host_evidence.csv`](../reports/compute_host_evidence.csv) records
the numerical matches, overlap-event counts, and trace-replay status. This is
software orchestration of independent AES and INT8 services, not an invented
AES-to-INT8 data pipeline.

`make protected-offload-error-reset` injects reset at six event-triggered
firmware phases: page-walk request, memory request, memory response, APB wait,
completion, and the split write-channel window after AXI AW acceptance but
before any W beat is accepted. Each run restarts the ROM program and the contextual checker
requires owned work at the selected phase, distinct reset epochs,
and no pre-reset transaction response after reboot. The response case resets
on the falling edge before acceptance; the completion case resets while an
entry is valid but unread. A completed handshake followed by an idle reset
does not qualify. The checked-in
[`protected_reset_context.csv`](../reports/protected_reset_context.csv)
contains pending ownership, canceled transaction, epoch, and phase evidence.

The reduced tag/reset formal harness instantiates the implemented DMA with
two queue entries and two tag identities. It checks tag reservation through
completion consumption and cancellation across arbitrary sampled reset epochs.
Its 48-step safety result and six reachable covers are bounded evidence, not
a proof of analog reset timing or arbitrary queue geometry. During bring-up,
the Yosys frontend flattened an unpacked struct-array FIFO into one descriptor;
explicit vector elements now preserve both entries. The Verilator component
regression and the older formal harnesses were rerun after that source change.

`make protected-offload-error` runs four firmware-owned
recovery cases: invalid input PTE, invalid output PTE, output write-permission
denial, and partial-output recovery. The final case commits vector zero, faults
vector one through the error target, reads the completion count/status, pops the
failed completion, repairs the vector-one PTE, performs a targeted ASID TLB
invalidation, and resubmits the same tag. The final retry verifies both output
locations. The independent context checker also confirms the actual pre-retry
SRAM word contains only the committed prefix, checks `vectors_done=1` on the
failed completion and `vectors_done=2` on retry, and verifies that the injected
error target rejected the failed write without mutation. This is bounded
software recovery evidence, not a general IOMMU driver or transactional
rollback claim.

`make compute-crossover-mutations` now fails closed unless the report contains
the exact twelve crossover-specific mutation names, successful mutant builds,
activated scenarios, nominal controls, and intended checker buckets. The
current checked-in report contains older generic mutations rather than this
exact audit set, so this requirement remains open. Generic crashes and unrelated
timeouts do not count as detections; results are recorded in
[`protected_offload_integration_mutations.csv`](../reports/protected_offload_integration_mutations.csv).

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
| Existing protected-offload mutations | `10 / 10` | Legacy suite; separate from the audit-specific crossover mutation matrix |
| Existing generic integration mutations | `12 / 12` | Detected, but names do not match the twelve required crossover defects |
| Audit-specific crossover mutations | `12 / 12` | Exact required defect names compiled, activated, and failed in intended checker/assertion buckets |
| Guard/queue/AXI/IOMMU checks | `4 / 4` | Descriptor legality, simultaneous queue accounting, lane/error, and translation/TLB cases |
| Solver properties | `10 / 10` | Eight bounded AXI-adapter checks plus two queue-accounting proofs; reachable covers |
| GCC firmware execution | `24 / 24` | Eight workflows at `-O0`, `-O2`, and `-Os` booted on RV32 and completed through APB/DMA |
| Shared-fabric firmware | `32 / 32` | Firmware initializes page tables/data; host, DMA, and PTW use the actual QoS fabric |
| Compiler/ISA matrix | `36 / 36` | `O0/O2/Os` crossed with RV32I/RV32IM |
| Shared integration random | `100 / 100` | Deterministic K, batch, ASID, QoS, IRQ, and ISA variation |
| Cached ownership | `8 / 8` positive; `4 / 4` negatives detected | Flush/fence/device/invalidate/fence handoff |
| Shared integration coverage | `48 / 48` directed; `15 / 15` predicates; `53 / 53` event crosses | Cross bins are trace/hash checked; high-risk bins have independent activating-source provenance; separate driver `19 / 19`; not exhaustive Cartesian closure |
| Current schema-3 replay smoke | `1 / 1` | One unique trace passes local RV32 ISS, PTE/TLB replay, APB lifecycle, host AXI channel ownership, and byte-memory checks; not the 48-row crossover matrix |
| Cache-enabled schema-3 replay smoke | `1 / 1` | Independent cache-enabled trace exercises multibeat host refills/writebacks and byte-memory replay; not cache ownership closure |
| Checker qualification | `25 negative + 6 positive controls` | Includes APB reset/retry lifecycle, legal multibeat AXI read/write controls, and bad read-address progression rejection |
| Checker qualification | `23` negative traces + `4` valid controls | Includes a passing two-beat AXI write and detects early WLAST, wrong ID, incomplete reads, lifecycle, epoch, ordering, malformed-schema, and independent data-model defects |
| Crossover build identity | `PASS` in schema-3 smoke | Every event carries a run-stable build identifier over active RTL sources and the compiled firmware ELF |
| Canonical crossover replay | `48 / 48` directed; `100 / 100` seeded workloads; `100 / 100` CPU streams | Current strict schema-3 local-ISS/model replays; generated separately from the legacy 205-row model metric |
| Crossover mutations | `12 / 12` | Each mutation compiles, activates its scenario, and fails in the intended checker/assertion bucket |
| Crossover formal | `16 / 16` | All groups have solver-reachable covers. The six crossover groups are bounded safety evidence, not unbounded full-system proofs; tag/reset use two-entry queues, two tags, 48 safety steps and 64 cover steps. |
| Crossover code coverage | `PARTIAL` | Fresh provenance-bound 257/257 execution sweep: integrated raw line 744/890 (83.60%), branch 717/926 (77.43%), expression 78.34%, raw toggle 47.38%. New control RTL reaches 119/124 lines (95.97%) and 174/190 branches (91.58%) with zero exclusions; guard-based scope classification keeps functional decoding in control RTL. Imported/cache/CPU RTL are reported separately. Broad integrated targets remain unmet; SVA executes in a separate asserted lane. |
| External RV32IM oracle | `19 / 19` | Pinned Spike differential programs pass, including seven RV32M-specific cases |
| CPU instruction-stream crossover random | `100 / 100` | Generated RV32IM streams execute during accepted DMA and pass strict local ISS replay |
| Legacy standalone code coverage | raw `289 / 341` (`84.75%`); reviewed `289 / 289` (`100%`) | Separate standalone report; do not use as integrated crossover coverage |
| Performance comparison rows | `45 / 45` | Scalar RV32I, MMIO stream, and autonomous DMA cycle evidence |
| Matched five-path benchmark | `150 / 150` | Same tensors and `mcycle` contract: RV32I, RV32IM, MMIO stream, uncached DMA, cached DMA |

| Executable job timeline | Device-cycle scaling |
| --- | --- |
| ![Normalized protected-offload event timeline](images/protected_offload_timeline.svg) | ![Measured protected DMA cycles](images/protected_offload_performance.svg) |

The matched benchmark uses one all-ones tensor/quantization contract at five K
values, three batch sizes, and cold/warm parameter modes. Its median measured
speedups versus scalar RV32I are `1.171x` for RV32IM, `10.440x` for MMIO stream,
`29.717x` for uncached shared DMA, and `23.722x` for cached shared DMA. These
are same-clock behavioral cycle ratios, not frequency, power, FPGA, or silicon
claims. Raw rows and hashes are in `protected_offload_matched_performance.csv`.

![Matched five-path speedup](images/protected_offload_matched_speedup.svg)

The checked-in GCC matrix separately records build and execution status, ELF
hash, instruction image size, simulated cycles, and retired instructions. Each
program boots on the provenance-locked RV32 core, programs the descriptor CSRs
through APB, waits for the level completion interrupt, validates the completion,
and publishes a result mailbox checked against output memory. The executable
path uses the locked educational IOMMU, performs two-level page walks, and
records TLB activity per firmware run. Cache-maintenance ownership evidence is
recorded in `protected_cache_ownership.csv` and `protected_cache_negative.csv`.

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
read/write responses, and error propagation. The four-master QoS fabric is
exercised by firmware-owned host, payload DMA, and page-walk traffic. The
cached-host path is separately checked; neither is an AXI compliance claim.

## Reviewer Commands

```bash
make protected-offload-smoke
make protected-offload-service-check
make protected-offload-shared-matrix
make protected-offload-shared-compiler
make protected-offload-shared-random
make protected-offload-error
make protected-offload-error-reset
make protected-offload-error-context
make compute-host-check
make compute-crossover-directed
make compute-crossover-random
make compute-crossover-coverage
make rv32-external-iss-check
make compute-crossover-repro-check
make compute-crossover-release-check
make protected-offload-cache-ownership
make protected-offload-components
make protected-offload-directed
make protected-offload-firmware
make protected-offload-random
make protected-offload-model-check
make protected-offload-coverage
make protected-offload-formal
make protected-offload-mutations
make protected-offload-performance
make protected-offload-matched-performance
make protected-offload-release-check
```

This is behavioral open-source pre-silicon evidence. It is not AXI compliance,
IOMMU certification, production firmware, cache coherence, or implementation
signoff. Half of the shared-fabric matrix polls; half uses machine external
interrupts, WFI, trap entry, completion draining, acknowledgement, and MRET.

## Stateful Crossover Extension

The optional [stateful closure](compute_stateful_closure.md) adds 23 executable scenarios beyond the finite M operand/IRQ matrices. It includes cause-qualified timer/device/APB-fault handling; exact falling-edge arithmetic/DMA reset phases and same-identity reboot; 260 repeated jobs, two-bank references and generation rollover; four-entry TLB replacement, cached write-permission failures, and a second output failure during retry; live load-M-store cache dependencies and failed-maintenance recovery; completion pressure with channel stalls; arithmetic during chiplet SLEEP; and independently checked numerical variation with timer interruption. Canonical totals remain separate.

`make compute-stateful-check`, `make compute-stateful-selftest`, `make compute-stateful-mutations`, and `make compute-stateful-code-coverage` produce separate reports. The native coverage target collects evidence rather than declaring the broader raw 95%/90% control target closed. Physical-alias/handler-access matrices, every multi-owner reset combination, and exhaustive interrupt/fault timing permutations remain outside this finite extension. No such missing tuple is silently excluded from canonical coverage.
