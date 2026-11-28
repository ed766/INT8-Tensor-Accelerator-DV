# Compute Crossover Coverage

Supplemental family/event reachability (not closure bins): **34 / 34**.

Observed executable predicates: **15 / 15**. This is not the planned transaction-cross coverage closure.

A predicate is credited only from its listed event IDs in a passing RTL trace. `NOT_REACHED` is a verification gap, not a pass. The comma-separated witness IDs are exact; they do not imply that intervening trace events belong to the same coverage sample.

| Type | Point | Status | Hits | First test | First event | Window |
|---|---|---:|---:|---|---:|---|
| family | `cpu_rv32m` | PASS | 6 | `cpu_rv32m__case_1` | `NOT_A_WITNESS` | `` |
| family | `apb_axi` | PASS | 6 | `apb_axi__case_1` | `NOT_A_WITNESS` | `` |
| family | `queues_configuration` | PASS | 6 | `queues_configuration__case_1` | `NOT_A_WITNESS` | `` |
| family | `translation_recovery` | PASS | 6 | `translation_recovery__fault_1` | `NOT_A_WITNESS` | `` |
| family | `interrupts` | PASS | 6 | `interrupts__case_1` | `NOT_A_WITNESS` | `` |
| family | `cache_ownership` | PASS | 6 | `cache_ownership__case_1` | `NOT_A_WITNESS` | `` |
| family | `combined_services` | PASS | 6 | `combined_services__case_1` | `NOT_A_WITNESS` | `` |
| family | `reset_transport` | PASS | 6 | `reset_transport__case_1` | `NOT_A_WITNESS` | `` |
| required_predicate | `rv32m_dma_overlap` | PASS | 6 | `cpu_rv32m__case_1` | `655` | `655,694,749` |
| required_predicate | `apb_wait_state` | PASS | 45 | `cpu_rv32m__case_1` | `49` | `49` |
| required_predicate | `reset_epoch_recovery` | PASS | 7 | `apb_axi__case_6` | `26` | `26,27,4032` |
| required_predicate | `translation_fault` | PASS | 4 | `translation_recovery__fault_1` | `1609` | `1609,1623` |
| required_predicate | `interrupt_delivery` | PASS | 9 | `cpu_rv32m__case_2` | `1080` | `1080,1082` |
| required_predicate | `completion_after_memory` | PASS | 36 | `cpu_rv32m__case_1` | `652` | `652,747,748,981` |
| required_predicate | `referenced_bank_rejection` | PASS | 1 | `queues_configuration__case_5` | `5164` | `5164,5167` |
| required_predicate | `unrelated_cpu_access_during_owned_buffers` | PASS | 1 | `cache_ownership__case_6` | `1631` | `1631,1749,1948,2078` |
| required_predicate | `aes_int8_overlap` | PASS | 6 | `interrupts__case_3` | `2826` | `2826,2834,2970` |
| required_predicate | `transport_backpressure` | PASS | 30 | `cpu_rv32m__case_2` | `30` | `30` |
| required_predicate | `chiplet_sleep_wake_during_offload` | PASS | 1 | `combined_services__case_5` | `3115` | `3115,3247,3266,3273,3470,3492` |
| required_predicate | `rv32m_interrupt_pending_at_retirement` | PASS | 2 | `cpu_rv32m__case_5` | `5306` | `5306,5339,5341,5342,5343` |
| required_predicate | `transport_payload_identity` | PASS | 40 | `cpu_rv32m__case_1` | `718` | `718,720` |
| required_predicate | `independent_translation_result` | PASS | 42 | `cpu_rv32m__case_1` | `654` | `654,702` |
| required_predicate | `maintenance_lifecycle` | PASS | 6 | `cache_ownership__case_1` | `664` | `664,838` |
| event | `RETIRE` | PASS | 48 | `cpu_rv32m__case_1` | `2` | `2` |
| event | `M_RETIRE` | PASS | 8 | `cpu_rv32m__case_1` | `2` | `2` |
| event | `APB` | PASS | 48 | `cpu_rv32m__case_1` | `49` | `49` |
| event | `XLATE_REQ` | PASS | 48 | `cpu_rv32m__case_1` | `654` | `654` |
| event | `XLATE_RSP` | PASS | 48 | `cpu_rv32m__case_1` | `702` | `702` |
| event | `PTW_REQ` | PASS | 48 | `cpu_rv32m__case_1` | `658` | `658` |
| event | `PTW_RSP` | PASS | 48 | `cpu_rv32m__case_1` | `683` | `683` |
| event | `PTE_WRITE` | PASS | 48 | `cpu_rv32m__case_1` | `48` | `48` |
| event | `TLB_INVALIDATE` | PASS | 3 | `translation_recovery__fault_3` | `934` | `934` |
| event | `AXI_AW` | PASS | 48 | `cpu_rv32m__case_1` | `42` | `42` |
| event | `AXI_W` | PASS | 48 | `cpu_rv32m__case_1` | `44` | `44` |
| event | `AXI_B` | PASS | 48 | `cpu_rv32m__case_1` | `46` | `46` |
| event | `AXI_WRITE` | PASS | 48 | `cpu_rv32m__case_1` | `47` | `47` |
| event | `AXI_AR` | PASS | 48 | `cpu_rv32m__case_1` | `901` | `901` |
| event | `AXI_R` | PASS | 48 | `cpu_rv32m__case_1` | `969` | `969` |
| event | `MEM_REQ` | PASS | 47 | `cpu_rv32m__case_1` | `704` | `704` |
| event | `MEM_RSP` | PASS | 47 | `cpu_rv32m__case_1` | `718` | `718` |
| event | `SUBMIT` | PASS | 48 | `cpu_rv32m__case_1` | `652` | `652` |
| event | `SUBMIT_REJECT` | PASS | 2 | `queues_configuration__case_1` | `734` | `734` |
| event | `DMA_ACTIVE_START` | PASS | 48 | `cpu_rv32m__case_1` | `655` | `655` |
| event | `DMA_ACTIVE_END` | PASS | 48 | `cpu_rv32m__case_1` | `749` | `749` |
| event | `COMPLETE_PUBLISH` | PASS | 48 | `cpu_rv32m__case_1` | `748` | `748` |
| event | `COMPLETE` | PASS | 48 | `cpu_rv32m__case_1` | `981` | `981` |
| event | `MAINT_START` | PASS | 7 | `cache_ownership__case_1` | `664` | `664` |
| event | `MAINT_DONE` | PASS | 7 | `cache_ownership__case_1` | `838` | `838` |
| event | `FIRMWARE_DONE` | PASS | 48 | `cpu_rv32m__case_1` | `1000` | `1000` |

Coverage is trace-derived from the real firmware integration top. It does not inflate the accelerator or chiplet canonical denominators.
