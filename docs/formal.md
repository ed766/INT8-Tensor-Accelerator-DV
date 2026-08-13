# Formal Evidence

The reduced `2x2`, `MAX_K=8`, two-entry configuration uses SymbiYosys to check FIFO bounds, command accounting, illegal-command containment, bank stability, and backpressure stability. Reachability covers require FIFO-full, command-error, and bank-swap states.

- `control_safety`: **PASS**, bounded_solver_safety, depth 16
- `reachability`: **PASS**, reachable_cover, depth 20

This is reduced-geometry open-source solver evidence, not exhaustive accelerator or numerical correctness proof.
