# Stateful Crossover Closure

Supplemental executable evidence; canonical closure denominators remain unchanged.

| Family | Qualified scenarios | Witness events |
|---|---:|---:|
| irq | 3/3 | 144 |
| reset | 4/4 | 8 |
| resources | 2/2 | 565 |
| translation | 3/3 | 35 |
| cache | 2/2 | 19 |
| progress | 5/5 | 1278 |
| numerical | 4/4 | 24 |
| edges | 9/9 | 63 |
| end_to_end | 8/8 | 11795 |
| gap_ownership | 2/2 | 29 |
| gap_reset | 11/11 | 68 |
| gap_contention | 4/4 | 408110 |
| gap_cache | 1/1 | 17 |
| gap_resources | 1/1 | 94 |
| gap_translation | 1/1 | 25 |
| gap_recovery | 2/2 | 68 |

Every row requires a passing simulation, matching trace SHA-256, strict architectural/transaction/memory/numerical replay, and the designated activating events. Event IDs are local to the named run and reset epoch in the trace, not globally unique tags.

Coverage witnesses: [directed CSV](../reports/compute_stateful_all_closure.csv), [seeded multi-job CSV](../reports/compute_stateful_random_closure.csv), and [same-window crosses](compute_stateful_cross_coverage.md). Fresh code instrumentation: [report](compute_stateful_code_coverage.md).

## Reproducible Seeded Workloads

`make compute-stateful-random` executes 32 deterministic seeds. Each initializes both parameter banks and two independent input buffers, submits eight additional jobs after the baseline job, and runs all eight M opcodes plus timer interrupts. K, cache mode, ASID, QoS, channel stalls and response delays vary. Full trace replay independently validates memory, numerical results, response ownership and retirement; scenario qualification requires nine accepted descriptors, both banks and four timer entries. This is a finite seeded workload family, not exhaustive ISA or subsystem random closure.

## Evidence Boundaries

- exhaustive Cartesian interrupt/fault/timing permutations.
- simultaneous M/DMA/AXI/IRQ ownership at every reset phase.
- all physical aliases and shared-cache-line handler accesses.
- independent construction of two witnesses for every high-risk predicate.
- unbounded core-control or 32-bit arithmetic equivalence proof.

The TLB regression caught two independent-checker mistakes: assumed eight entries rather than this integration's four, and compacted invalidation instead of retaining physical replacement slots/cursor. The corrected model still checks exact observed hit/miss decisions. No DUT arithmetic failure was demonstrated.
