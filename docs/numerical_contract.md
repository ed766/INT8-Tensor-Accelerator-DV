# Numerical Contract

The reviewed accelerator configuration consumes four signed INT8 activations and applies a four-output signed INT8 weight matrix.

For output channel `o`:

```text
acc[o] = bias[o] + sum(input[i] * weight[o][i]), i = 0..3
scaled[o] = (acc[o] * multiplier[o]) >>> shift[o]
activated[o] = max(0, scaled[o]) when ReLU is enabled
output[o] = clamp(activated[o], -128, 127)
```

The dot product and bias use signed INT32 semantics. The multiplier uses a signed 64-bit intermediate before an arithmetic right shift. Saturation is deterministic; the design does not implement stochastic rounding or floating-point arithmetic.

Configuration is loaded while idle. The streaming interface preserves an 8-bit tag and can accept one vector each cycle when the output consumer remains ready. Output backpressure stalls the single-entry result stage.

This is a compact architecture for numerical verification and hardware/software co-design. It is not presented as a production neural-processing unit, training engine, or floating-point implementation.
