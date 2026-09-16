# Matched RV32I/RV32IM/Accelerator Performance

All `150 / 150` rows use the same all-ones tensor contract and architectural `mcycle` boundaries. These are behavioral same-clock cycle measurements, not silicon frequency, power, FPGA, or wall-clock claims.

| Path | Rows | Median speedup vs RV32I |
| --- | ---: | ---: |
| `scalar_rv32i` | 30 | 1.000x |
| `scalar_rv32im` | 30 | 1.171x |
| `mmio_stream` | 30 | 10.440x |
| `uncached_shared_dma` | 30 | 29.717x |
| `cached_shared_dma` | 30 | 23.722x |
