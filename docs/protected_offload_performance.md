# Protected Offload Performance

All values are behavioral Verilator cycles. The scalar and MMIO rows come from the existing passing RV32 benchmark; DMA rows execute the new descriptor path.

| K | Batch | Scalar cycles | MMIO-stream cycles | DMA job cycles | DMA vs scalar |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 1 | 15173 | 92 | 85 | 178.51x |
| 4 | 16 | 240554 | 1850 | 325 | 740.17x |
| 4 | 64 | 960689 | 7040 | 1093 | 878.95x |
| 8 | 1 | 21983 | 108 | 92 | 238.95x |
| 8 | 16 | 357773 | 2490 | 437 | 818.70x |
| 8 | 64 | 1385732 | 9594 | 1541 | 899.24x |
| 16 | 1 | 35954 | 491 | 106 | 339.19x |
| 16 | 16 | 500279 | 7472 | 661 | 756.85x |
| 16 | 64 | 2168582 | 29516 | 2437 | 889.86x |
| 32 | 1 | 53882 | 888 | 134 | 402.10x |
| 32 | 16 | 856991 | 13680 | 1109 | 772.76x |
| 32 | 64 | 3526328 | 56058 | 4229 | 833.84x |
| 64 | 1 | 95327 | 1691 | 190 | 501.72x |
| 64 | 16 | 1569758 | 26099 | 2005 | 782.92x |
| 64 | 64 | 6285431 | 105725 | 7813 | 804.48x |

These paths have different software boundaries; the table preserves raw cycles so reviewers can inspect the comparison.
