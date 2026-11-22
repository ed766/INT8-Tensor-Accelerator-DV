# INT8 FIFO implementation comparison

The configurations compare the default 4×4 accelerator with four and eight
result FIFO entries. Both use the Nangate45 typical library, a 10 ns clock,
1 ns I/O delays, 35% floorplan utilization, and a 0.50 placement density.

With compatible OpenROAD and Yosys/slang binaries configured in OpenROAD
Flow Scripts, run `bash implementation/openroad/run_comparison.sh /path/to/flow`.
The two final report directories are under
`reports/nangate45/int8_tensor_accel/fifo4` and `fifo8`.

## Initial implementation estimates

| FIFO entries | Floorplan standard-cell area (µm²) | Floorplan worst setup slack (ns) |
| --- | ---: | ---: |
| 4 | 87,281.0 | 1.90231 |
| 8 | 88,344.7 | 1.95402 |

Yosys 0.66+181 mapped both designs with Flow Scripts revision
`a9adcf481395d3b1355afda40df1c8bde10a0e40`. OpenROAD revision
`edf00dff99f6c40d67a30c0e22a8191c5d2ed9d6` predates the flow's
`write_liberty_binary` requirement. The mapped netlists were handed to
Flow Scripts revision `baaa665ad873b358089fc20150a9666c8c865334`
for physical implementation. These are floorplan-stage estimates.

## Routed results

| FIFO entries | Final cell area excluding fillers (µm²) | Extracted worst setup slack (ns) | Router violations |
| --- | ---: | ---: | ---: |
| 4 | 99,310.3 | +2.02 | 0 |
| 8 | 100,491.3 | +2.06 | 0 |

The eight-entry FIFO increased the measured cell area by about 1.2%.
Both core-clock critical paths start at `previous_bank$_DFFE_PN0P_`.
The four-entry path ends at `result_fifo_data[0][18]$_DFFE_PP_` and the
eight-entry path ends at `result_fifo_data[6][29]$_DFFE_PP_`.
Timing uses extracted parasitics. These are implementation estimates
under the stated constraints. The flow's default IR analysis needs a
validated supply and activity setup before drawing power integrity
conclusions. Firmware simulation cycles are in the
[cross-project demo](../../docs/cross_project_demo.md).
