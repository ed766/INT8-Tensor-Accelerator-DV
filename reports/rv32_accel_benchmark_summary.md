# RV32I vs INT8 Accelerator Benchmark

These values are measured behavioral Verilator cycles at one shared clock. They are not simulator wall time, FPGA/silicon frequency, power, or physical implementation results.

## Closure

| Evidence | Result |
| --- | ---: |
| Cold/warm benchmark matrix | `40 / 40` |
| Operand-pattern correctness | `25 / 25` |
| Output-backpressure robustness | `15 / 15` |
| Expected-fail mutations detected | `5 / 5` |

## Warm Break-Even Batch

| K | First measured batch above 1x |
| ---: | ---: |
| 4 | 1 |
| 8 | 1 |
| 16 | 1 |
| 32 | 1 |
| 64 | 1 |

## Firmware/Transport Cycle Breakdown

| Phase | Median cycles across matrix |
| --- | ---: |
| Configuration | 2761.0 |
| Command and streaming | 2406.0 |
| Polling | 50.0 |
| Output read/pop | 210.0 |

The scalar path is GCC `-O2` RV32I/Zicsr software with explicit multiplication helpers. Cold measurements include configuration; warm measurements reuse configured parameters. Compute-only latency ends at first result validity, while end-to-end latency includes firmware streaming, polling, and result reads.

![Measured speedup](../docs/images/rv32_accel_speedup.svg)

![Measured latency](../docs/images/rv32_accel_latency.svg)

![Measured break-even batch](../docs/images/rv32_accel_break_even.svg)
