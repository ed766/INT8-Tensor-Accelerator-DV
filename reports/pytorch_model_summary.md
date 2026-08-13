# PyTorch Golden Model

- PyTorch version: `2.7.1`
- Workloads: `130` (`30` directed + `100` seeded random)
- Manifest SHA-256: `fbce38006520ce83263182132bf736dacfe253fb5206bdaa40b2f1b9283d44ee`
- Arithmetic: asymmetric signed INT8 inputs and weights, INT32 accumulation, per-channel round-to-nearest requantization, output zero point, optional ReLU, and INT8 saturation.
