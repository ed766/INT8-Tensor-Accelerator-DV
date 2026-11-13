# Advanced Crossover Coverage

Observed bins: 42/42. Robustness gaps: 0.

| Family | Hit / required | Independent-template gaps |
|---|---:|---:|
| permission | 7/7 | 0 |
| recovery | 5/5 | 0 |
| irq_pending_m_retirement | 4/4 | 0 |
| reset_boundary | 11/11 | 0 |
| reset_owner | 6/6 | 0 |
| retry_attempt | 5/5 | 0 |
| cache_maintenance | 4/4 | 0 |

[Trace windows](../reports/compute_gap_cross_coverage.csv) and [measured contention](../reports/compute_gap_contention.csv).

Read-hit permission denial is structurally unreachable for this non-user requester: only readable, accessed entries are installed; PTE changes do not mutate cached permissions.
Reset-boundary features are labeled single-source directed evidence, not independently replicated safety closure.
Pending at arithmetic retirement is not an exhaustive interrupt-arrival timing matrix.
No unbounded progress is assumed for a nonresponsive AXI target.
Retry-attempt and maintenance combinations are single-source feature evidence unless multiple independent templates are reported; the permission/recovery/IRQ safety families retain a two-template requirement.
Maintenance with device-owned buffers is not credited by free-ownership maintenance windows; owned handler accesses are separately qualified expected-negative tests.
