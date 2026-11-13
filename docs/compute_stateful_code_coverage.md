# Stateful Crossover Native Code Coverage

Fresh native Verilator 5.049 instrumentation of 94 supplemental firmware scenarios (directed and seeded). Assertions run separately in the asserted regression; this instrumentation build defines SYNTHESIS. Source-point unions do not imply every structural variant is independently closed. No raw toggle closure is claimed.

| Scope | Raw line hit/total (%) | Raw branch hit/total (%) | Raw toggle (%) |
|---|---|---|---|
| imported_axi_fabric_and_iommu | 70/79 (88.61) | 93/112 (83.04) | 36.21 |
| imported_chiplet | 354/465 (76.13) | 210/340 (61.76) | 68.27 |
| imported_l1_cache | 43/59 (72.88) | 61/92 (66.30) | 56.61 |
| integrated_protected_offload_and_rv32 | 720/899 (80.09) | 724/954 (75.89) | 54.78 |
| new_protected_offload_control_rtl | 119/122 (97.54) | 175/186 (94.09) | 49.95 |
| rv32_core | 83/121 (68.60) | 60/86 (69.77) | 50.42 |
| rv32_core_and_feeder | 97/137 (70.80) | 98/126 (77.78) | 62.07 |
| rv32_muldiv | 11/13 (84.62) | 32/34 (94.12) | 99.63 |
| rv32_rom_feeder | 3/3 (100.00) | 6/6 (100.00) | 55.34 |
| verification_contention_generator | 3/3 (100.00) | 8/8 (100.00) | 100.00 |
| verification_memory_target_model | 13/13 (100.00) | 41/42 (97.62) | 70.41 |
| verification_ownership_monitor | 21/21 (100.00) | 38/48 (79.17) | 45.95 |

New-control raw targets: 95% line / 90% branch. Measured gate: **PASS**. This lane is supplemental, not a replacement for canonical integration coverage; imported-module gaps remain visible. No exclusions are used to turn an unmet raw target into PASS.

[Incremental group contribution](../reports/compute_stateful_code_coverage_contributions.csv) uses the same source-point union denominator. New points are credited in original-directed, targeted-edge, end-to-end, seeded-workload order; this is not independent per-configuration closure.

[Remaining-hole review](../reports/compute_stateful_coverage_hole_review.csv) retains all holes in raw denominators. The three uncovered new-control lines and two muldiv lines are defensive defaults. Remaining integrated branches include topology-constrained waits, a caller-constrained magnitude helper and an illegal-peer response path. [Independent-peer tests](compute_peer_holes.md) exercise module waits and wrong-tag containment separately; they do not inflate this integration percentage.
