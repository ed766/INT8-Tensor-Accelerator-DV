# Ownership, Reset and Contention Closure

This optional lane strengthens the executable RV32M/accelerator crossover without
changing canonical chiplet, cache or accelerator coverage denominators. Counts
and trace witnesses are generated from passing executions, not scenario names.

## What Changed

- Physical ownership captures descriptor-lifetime mappings, consults effective
  TLB entries before current PTE contents, and incorporates actual translation
  responses. Independent replay compares CPU accesses to translated physical
  cache lines, including accesses preceding translation completion.
- Completion checking is reset-epoch aware. Abandoned publication/read records
  cannot satisfy a rebooted job even when tags and addresses are reused.
- Eleven falling-edge, event-triggered reset cases cover metadata status/address/
  stage, publication, before pop, page walk, output-write acceptance, B wait,
  response wait, host write-channel separation and maintenance/invalidation.
- A verification-only independent AXI master contends with payload reads for the
  actual SRAM target. Four deterministic stall levels exercise mixed QoS, aging,
  full completion pressure, arithmetic, chiplet sleep/wake and checked outputs.
  Accepted requests must equal returned read beats at drain.
- Cache cases exercise physical aliases, final-set dirty eviction and an owned
  line versus a permissible adjacent line. Three expected-negative/control pairs
  validate ownership sensitivity independently of passing drained runs.
  The third pair checks a timer-handler access to an owned input line versus
  the passing handler's unrelated-line access.
- Independently constructed permission and first/middle/last committed-prefix
  recovery programs validate repaired mappings, invalidation and complete retry.

## Auditable Evidence

| Evidence | Canonical report |
|---|---|
| Directed firmware and independent replay | [Qualified executions](../reports/compute_stateful_all_closure.csv) |
| Seeded multi-job firmware | [Seeded executions](../reports/compute_stateful_random_closure.csv) |
| Advanced same-event/window bins and independent witnesses | [Cross CSV](../reports/compute_gap_cross_coverage.csv), [summary](compute_gap_cross_coverage.md) |
| Real contention, wait/service gaps and age overrides | [Measured contention](../reports/compute_gap_contention.csv) |
| Alias expected negatives with passing controls | [Ownership sensitivity](../reports/compute_ownership_alias_check.csv) |
| Reference-release, stale permission and dirty-eviction RTL defects | [Mutation qualification](../reports/compute_gap_mutations.csv) |
| Raw native coverage with separate RTL scopes | [Coverage](compute_stateful_code_coverage.md) |
| Two identical normalized regenerations | [Reproducibility](../reports/compute_gap_reproducibility.csv) |

```text
make compute-gap-release-check
make compute-end-to-end-mutations
```

Advanced high-risk permission, recovery and IRQ bins require two independently
constructed firmware templates; multiple seeds from one template do not qualify.
Reset-owner/phase, retry-attempt and cache-maintenance bins are explicitly labeled
feature evidence where only one independent template exists. Each hit carries
event identifiers, epoch, first/all contributors and a trace SHA-256.

## Evidence Boundaries

## Monitor Defect Found by the Handler Test

The independent physical-line replay rejected the owned handler access while the
inline monitor missed it. The monitor was using request direction/address at
translation response time, after the DMA had left its request state. An output
translation therefore overwrote the input mapping. The fix captures tag, IOVA
and direction on accepted requests, checks response accounting, and updates the
corresponding mapping only at response completion. Reset cancels that context.
The handler negative now requires the exact ownership violation with an accepted
descriptor and timer-entry trace witness; a generic firmware failure is rejected.

## Remaining Boundaries

The reference-monitor corrections are not evidence of a new arithmetic DUT bug.
Progress assumes finite scheduled target stalls followed by drain. The single-beat
in-order SRAM environment must return each accepted read within 2048 clocks;
the measured report checks this bound as well as final request/response balance.
This is an environment contract, not a general AXI ordering or DUT latency guarantee.
It is not
unbounded whole-SoC liveness or equal-QoS fairness. The ownership monitor's captured
page envelope is bounded to 64 pages per input/output span. Exhaustive context/
reset races, maintenance with live device-owned buffers, and an exact maintenance
last-line-skip mutation remain opportunities; dirty-eviction mutation evidence
does not substitute for that particular defect. Raw imported-module
coverage remains separate from new-control coverage. No commercial signoff is
claimed.
