# Performance Characterization

Behavioral Verilator measurements from command acceptance through result acceptance.

| K | Output stall | Requests | Mean | p50 | p95 | Max | MACs/command | Double-buffer overlap saving |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 0 | 7 | 2.00 | 2 | 2 | 2 | 16 | 6.67% |
| 4 | 1-3 | 6 | 6.00 | 6 | 8 | 8 | 16 | 6.67% |
| 4 | 4-7 | 11 | 9.27 | 10 | 12 | 12 | 16 | 6.67% |
| 8 | 0 | 14 | 3.00 | 3 | 3 | 3 | 32 | 6.38% |
| 8 | 1-3 | 8 | 7.25 | 7 | 9 | 9 | 32 | 6.38% |
| 8 | 4-7 | 10 | 9.60 | 9 | 13 | 13 | 32 | 6.38% |
| 16 | 0 | 10 | 5.00 | 5 | 5 | 5 | 64 | 6.17% |
| 16 | 1-3 | 8 | 8.75 | 9 | 11 | 11 | 64 | 6.17% |
| 16 | 4-7 | 9 | 12.33 | 13 | 15 | 15 | 64 | 6.17% |
| 32 | 0 | 5 | 9.20 | 9 | 10 | 10 | 128 | 6.04% |
| 32 | 1-3 | 7 | 12.71 | 13 | 15 | 15 | 128 | 6.04% |
| 32 | 4-7 | 13 | 16.08 | 17 | 19 | 19 | 128 | 6.04% |
| 64 | 0 | 4 | 17.00 | 17 | 17 | 17 | 256 | 5.96% |
| 64 | 1-3 | 9 | 21.00 | 21 | 23 | 23 | 256 | 5.96% |
| 64 | 4-7 | 9 | 23.67 | 23 | 27 | 27 | 256 | 5.96% |

The datapath performs 16 signed MACs per active input-chunk cycle. Parameter bank B may be loaded while bank A executes, so configuration and compute can overlap. The overlap column is a cycle-count architectural model using measured command geometry, not silicon timing or power signoff.
