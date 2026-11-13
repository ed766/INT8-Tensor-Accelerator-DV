# Stateful Interaction Coverage

Supplemental to canonical crossover closure. No scenario-name credit or denominator inflation.

| Family | Hit / Required | Predicate |
|---|---:|---|
| k_bank | 10/10 | K and configuration bank on one accepted descriptor |
| m_completion_pressure | 16/16 | M dispatch snapshot and matching successful retirement in the same epoch and PC; completion occupancy at dispatch |
| apb_direction_wait | 4/4 | direction and observed wait cycles on one completed APB transaction |
| recovery | 5/5 | failed consumed completion followed by successful same-tag new descriptor after invalidation in one epoch |

[Event-window witnesses](../reports/compute_stateful_cross_coverage.csv). Every hit requires a matching trace hash, passing simulation, independent replay and scenario activation qualification. Raw traces remain generated artifacts.

[Seeded requested-versus-realized activity](../reports/compute_stateful_random_activity.csv) records applied knobs, descriptor/completion/bank/IRQ counts, M opcodes and AXI waits. Wait-event count is not a measurement of achieved ready-low duty percentage.

## Boundaries

- No cross-epoch retry credit.
- No scenario-name-inferred hits.
- Not a full Cartesian outcome or interrupt matrix.
- Completion pressure is sampled at M dispatch, not assumed stable through retirement.
