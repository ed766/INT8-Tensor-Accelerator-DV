# Portable Transaction Vectors

`portable_vectors.mem` is a packed, tool-neutral command stream. The same records are consumed by the SystemVerilog portability bench and are suitable for a future FPGA host transport.

| Bits | Record | Meaning |
| --- | --- | --- |
| `[63:60]=0` | configuration | bank, kind, output, index, and 32-bit data |
| `[63:60]=1` | command | bank, K, and transaction tag |
| `[63:60]=2` | activation | tag and four packed INT8 activation lanes |
| `[63:60]=3` | expectation | expected tag and four packed INT8 outputs |
| `[63:60]=4` | sink stall | cycles to hold result ready low |
| `[63:60]=f` | end | end of stream |

Generate and execute the stream with `make portable-check`. JSON metadata records the schema version, seed, case count, and SHA-256 digest so host and RTL runs can prove they used identical vectors.
