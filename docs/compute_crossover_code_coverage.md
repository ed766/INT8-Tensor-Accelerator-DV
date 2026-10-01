# Compute Crossover Integrated-Top Code Coverage

Collected from 48 directed compiled-firmware scenarios, 100 seeded firmware/DMA schedules, 100 generated RV32M instruction streams, one APB edge probe, and 8 cache-enabled ownership scenarios on `tb_rv32_protected_shared`, including the RV32 core, protected DMA/IOMMU/cache-control RTL, and optional chiplet top. This is native Verilator 5.049 instrumentation, distinct from functional/cross coverage. The coverage build defines `SYNTHESIS` to exclude assertion-only code; SVA runs in the separate asserted regression.

Point identity is source-based and unioned across all passing runs, elaborated parameterizations, and instances. A source point is covered when at least one tested configuration/instance executes it; this is not a claim that every instance or configuration has independent closure. Integrated, imported, ownership-monitor, and memory-model scopes remain separately visible.

- Raw line coverage: **744 / 890 (83.60%)**
- Raw branch coverage: **717/926 (77.43%)**
- Raw expression coverage: **1400 / 1787 (78.34%)**
- Raw toggle coverage: **27215 / 57434 (47.38%)**
- New protected-control raw coverage: line **119 / 124 (95.97%)**, branch **174 / 190 (91.58%)**
- New-control reviewed branch coverage: **174 / 190 (91.58%)**; exclusions: **0** reviewed unreachable FSM default points
- Verification-only ownership monitor and AXI memory target are reported in separate scopes, not counted as synthesizable control RTL. The aggregate integrated scope above remains raw and includes imported RV32/cache/fabric/chiplet logic.
- Required new-control targets: raw line **95%**, reviewed branch **90%**
- Per-line points: [`compute_crossover_code_coverage_points.csv`](../reports/compute_crossover_code_coverage_points.csv)
- Per-branch points: [`compute_crossover_code_coverage_branches.csv`](../reports/compute_crossover_code_coverage_branches.csv)
- Per-expression points: [`compute_crossover_code_coverage_expressions.csv`](../reports/compute_crossover_code_coverage_expressions.csv)
- Per-toggle points: [`compute_crossover_code_coverage_toggles.csv`](../reports/compute_crossover_code_coverage_toggles.csv)
- Reviewed branch exclusions: [`compute_crossover_code_coverage_exclusions.csv`](../reports/compute_crossover_code_coverage_exclusions.csv)
- Instrumented passing runs: **257 / 257** (48 directed + 100 firmware-random + 100 CPU-stream + 1 APB edge + 8 cache-ownership)

The report counts native Verilator `line`, `branch`, `expr`, and `toggle` point types separately. Raw values are never replaced by reviewed values. Reviewed branch exclusions are limited to unreachable defensive FSM default arms and are listed individually with source/page provenance. The verification monitor, AXI memory model, imported modules, and full integrated raw metric remain separately visible.
