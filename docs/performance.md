# Performance Characterization

Behavioral Verilator measurements from accepted input to accepted output. Configuration time is excluded.

| Output-ready stall | Requests | Mean latency | p50 | p95 | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 cycles | 21 | 1.00 | 1 | 1 | 1 |
| 1-2 cycles | 25 | 2.40 | 2 | 3 | 3 |
| 3-4 cycles | 8 | 4.50 | 4 | 5 | 5 |
| 5-6 cycles | 9 | 6.44 | 6 | 7 | 7 |

The single-entry output stage can accept one vector per cycle when the consumer is ready. Backpressure stalls the pipeline and increases end-to-end latency. These are RTL simulation results, not silicon timing signoff.
