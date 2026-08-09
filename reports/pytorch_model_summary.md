# PyTorch Golden Model

- PyTorch version: `2.7.1` (runtime build suffix intentionally normalized)
- Deterministic scenarios: `63`
- Manifest SHA-256: `2bc91646c0d352933e43bd6e416e2b187acf8059cb55a83e611fb7678e2fe951`
- Arithmetic: signed INT8 inputs/weights, INT32 dot products and bias, signed fixed-point multiplier/right shift, optional ReLU, signed INT8 saturation.
- The model predicts integer results independently of the RTL implementation.
