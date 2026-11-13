# End-to-End Lifetime and Recovery Closure

This optional lane extends the firmware-owned integration, not the standalone
chiplet's canonical 70-test gate. Every scenario requires successful RTL
execution, SHA-256-bound trace evidence, independent architectural/transaction/
translation/numerical replay, and its specific activating events.

## Scenarios

| Scenario | Required end-to-end behavior |
|---|---|
| `lifetime_campaign` | 96 rounds of four jobs, both banks, all 256 tags with reuse, generation wrap, full completion FIFO through arithmetic, stable front-record reads, and checked destination memory. |
| `cross_stage_retry` | Same logical descriptor fails input permission, then middle output write, then input read; repair/invalidate/retry finally succeeds. Firmware compares fault stage/address and every committed or untouched output word. |
| `handler_cached_arithmetic` | Timer handler executes a cached load/M/store dependency on an unrelated line while the DMA owns its buffers; ABI return, arithmetic and output data are independently checked. |
| `fault_both_pending` | An access-faulting load immediately follows M retirement with timer/device events pending and globally masked. The load preserves its destination, precise fault returns, then both pending handlers execute. |
| `reset_multiple_owners` | Event-triggered falling-edge reset with M, DMA, payload request, unread completion and device IRQ pending. Reboot reuses software tags and addresses; epoch-aware replay rejects ghost activity. |
| `queued_invalidation` | Targeted invalidation requested while both-bank jobs are queued; pending status remains visible until all four completions drain. A later repaired mapping plus global invalidation changes actual translated input data. |
| `read_permission_downgrade` | Install a readable translation, downgrade its PTE without changing context, observe the intentionally stale readable hit, invalidate, reject the next read, then repair and recover. |
| `contended_sleep_drain` | 75-percent requested deterministic transport stalls and delayed responses during AES/INT8 service lifetimes, arithmetic during chiplet SLEEP, wake and drain. AES and INT8 outputs use independent models. |

The extended sleep interval is stimulus, not overlap evidence. The checker
requires actual service-overlap events; it does not claim two compute engines
make arithmetic progress in the same clock while one is asleep.

## Independent Metadata Checking

APB completion events now record read data. A separate checker compares status,
ASID, committed count, fault address, stage and tag reads with the ordered
publication/consumption lifetime already checked against the device model.
Missing read data fails closed. Firmware success alone cannot satisfy this gate.
Each observed completion read must also match its CPU retirement memory data and
destination register; mutually consistent but corrupted RVFI load/result fields
cannot substitute for the actual APB response.

The checker now partitions publication, metadata reads, retirement and consumption
by reset epoch. A reset may abandon an unread record or unfinished read; it cannot
bind that record to a later same-tag job. Eleven executable reset boundaries,
including individual metadata reads and pre-pop/publication, are covered by the
[advanced closure lane](compute_gap_closure.md).

The actual `PROTECTED_MUT_TORN_COMPLETION_METADATA` RTL mutation corrupts the
CPU-visible stage while retaining the internal completion record. Detection
requires a passing nominal control, an executable mutant, matching trace hash,
and the exact `completion_metadata_read_mismatch` diagnostic. Checker trace
self-tests are reported separately from that RTL mutation.

## Commands and Evidence

```text
make compute-end-to-end-check
make compute-end-to-end-selftest
make compute-end-to-end-mutations
make compute-stateful-check
make compute-end-to-end-summary
```

Measured [snapshot](../reports/compute_end_to_end_closure.md),
[trace witnesses](../reports/compute_end_to_end_closure.csv), and
[mutation qualification](../reports/compute_end_to_end_mutations.csv).

## Remaining Boundaries

- Additional resets now target page walking, accepted output writes, B/response
  waits, host AW/W separation and maintenance/invalidation. These finite phase
  tests do not exhaust simultaneous owner combinations. Acknowledged pre-reset
  writes are not assumed rolled back.
- Metadata stability is exercised at occupied/full FIFOs; exact same-edge
  publication/pop coverage remains the existing dedicated collision lane.
- Context tests do not exhaust all ASID/targeted/global invalidation races.
- A timer-handler owned-line negative is now paired with the unrelated-line
  passing control. Foreground alias/shared-line controls additionally distinguish
  owned lines from permissible adjacent lines; all possible handler aliases are
  not claimed closed.
- Progress is demonstrated for finite scheduled stalls, not under a permanently
  nonresponsive target. No unbounded whole-SoC liveness proof is claimed.
- The historical sleep/drain scenario alone is not arbitration evidence. Four
  additional runs use a real independent fabric master, measure service gaps and
  actual aging grants, and require eventual response drain under finite stalls.
  Equal-QoS statistical fairness and unbounded liveness are not claimed.
- Reference-release, stale permission context and dirty-eviction mutations are
  now qualified separately. The dirty mutation is not a last-maintenance-line
  skip mutation; that specific checker-sensitivity case remains open.
