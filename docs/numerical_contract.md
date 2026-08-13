# Numerical and Command Contract

For command-selected parameter bank `b`, output channel `o`, and command length `K`:

```text
acc[o] = bias[b][o]
       + sum((input[i] - input_zero[b])
           * (weight[b][o][i] - weight_zero[b][o])), i = 0..K-1

product[o] = acc[o] * multiplier[b][o]
rounded[o] = sign(product[o])
           * ((abs(product[o]) + 2^(shift[o]-1)) >> shift[o])
scaled[o] = rounded[o] + output_zero[b][o]
activated[o] = max(0, scaled[o]) when ReLU is enabled
output[o] = clamp(activated[o], -128, 127)
```

Shift zero bypasses the rounding offset. The product uses a signed 64-bit intermediate; the accumulator and bias are signed INT32. Rounding is deterministic, symmetric round-to-nearest with ties away from zero.

Legal command lengths are multiples of the lane count from `LANES` through `MAX_K`. An illegal length raises `cmd_error` without accepting work. Each accepted chunk must carry the active command tag. Configuration of the active bank is blocked until the command completes, while the inactive bank remains writable. A final chunk waits if the four-entry result FIFO is full.

Reset aborts active work and clears queued results. Aborted commands cannot create a post-reset result.
