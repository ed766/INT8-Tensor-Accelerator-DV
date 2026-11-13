# Independent-Peer Coverage Tests

Tests use public module interfaces with independently stalled peers. They do not force internal states, patch imported RTL or inflate firmware-integration percentages.

Asserted and native runs: 14/14. DMA tests use four deterministic stall seeds, 19 jobs each (13 success / 6 wrong-tag faults), including first/middle/last-vector errors with exact committed-prefix and fault-address checking, followed by clean recovery. Held-result tests execute all eight M opcodes, division corner cases and reset with an unconsumed result.

## Separate Component Coverage

Native source-point union across these component benches only. Not baseline/integration coverage, and not independent closure for every instance/parameter setting.

| Module | Raw line | Raw branch |
|---|---:|---:|
| `protected_chiplet_apb_bridge.sv` | 3/3 (100.00%) | 6/6 (100.00%) |
| `protected_dma_axi_adapter.sv` | 7/8 (87.50%) | 26/26 (100.00%) |
| `protected_host_axi_bridge.sv` | 4/5 (80.00%) | 8/8 (100.00%) |
| `protected_offload_dma.sv` | 28/29 (96.55%) | 61/78 (78.21%) |
| `protected_queue_count_next.sv` | 4/4 (100.00%) | 0/0 (NA%) |
| `rv32_muldiv.sv` | 11/13 (84.62%) | 33/34 (97.06%) |

## Prior-Hole Witnesses

| Prior hole | Component test | Status |
|---|---|---|
| `protected_dma_axi_adapter.sv:129`  | None | NOT_COVERED_IN_COMPONENT_LANE |
| `protected_host_axi_bridge.sv:54`  | None | NOT_COVERED_IN_COMPONENT_LANE |
| `protected_offload_dma.sv:522`  | None | NOT_COVERED_IN_COMPONENT_LANE |
| `rv32_muldiv.sv:151`  | None | NOT_COVERED_IN_COMPONENT_LANE |
| `rv32_muldiv.sv:157`  | None | NOT_COVERED_IN_COMPONENT_LANE |
| `protected_chiplet_apb_bridge.sv:44` else | held_results | COMPONENT_COVERED |
| `protected_dma_axi_adapter.sv:128` else | dma_response | COMPONENT_COVERED |
| `protected_host_axi_bridge.sv:53` else | host_select | COMPONENT_COVERED |
| `protected_offload_dma.sv:447` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:457` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:467` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:471` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:479` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:480` if | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:487` else | dma_peers | COMPONENT_COVERED |
| `protected_offload_dma.sv:500` else | dma_peers | COMPONENT_COVERED |
| `rv32_muldiv.sv:156` else | held_results | COMPONENT_COVERED |
| `rv32_muldiv.sv:34` cond_else | None | NOT_COVERED_IN_COMPONENT_LANE |

[Run provenance](../reports/compute_peer_holes.csv), [native points](../reports/compute_peer_holes_coverage_points.csv), [hole mapping](../reports/compute_peer_hole_closure.csv). Wrong-tag tests model a faulty accelerator peer and require error containment without a destination write; they are not normal numerical-model runs. Defensive defaults and the magnitude helper's unreachable caller alternative remain raw holes.

The host test checks actual AW/AR handshake counts and a held-select, PENABLE-low bubble after completion. Its old eight-byte address-rounding expectation was corrected: a four-byte AXI transfer on a 64-bit bus retains address bit 2 and selects the upper data lanes. No DUT change was needed.
