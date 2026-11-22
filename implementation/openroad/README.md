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
