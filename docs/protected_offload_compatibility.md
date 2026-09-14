# Protected Offload Compatibility Audit

| Component | Locked source | Consumer configuration | Executable evidence |
| --- | --- | --- | --- |
| INT8 accelerator | Local canonical RTL | 4 lanes, 4 outputs, K up to 64 | 40 directed + 100 seeded offload jobs |
| RV32 core/ROM | Chiplet commit `96ecbb1d572f001c1000beb6edf44b4cc6ebcec9` | RV32I/Zicsr snapshot | 24 GCC-built images execute through APB/DMA at `-O0/-O2/-Os` |
| AXI QoS fabric | Fabric commit `25fd40691c9052b638f38746528da2d09ddb1e88` | 64-bit data, 4-bit ID | Provenance only in this lane; source project owns fabric closure |
| DMA IOMMU | Same fabric commit | 4-entry TLB, two-level page walk | Integrated firmware translation plus focused hit/miss, ASID, invalidation, and permission-fault test |
| L1 cache | Cache commit `6f54c0fbd996b5878691e2cacf52d038b1af561e` | Baseline parity snapshot | Provenance only; cached ownership phase deferred |
| DMA-to-AXI adapter | New local RTL | 32-bit DMA to single-beat 64-bit AXI | Lower/upper lanes, waits, read/write errors |
| Descriptor queues | New local RTL | Four submit + four completion entries | Simultaneous submit push/pop, full occupancy, ordering, backpressure |
| Descriptor guard | New local RTL | 32-bit aligned IOVA ranges | Geometry, generation, overlap, and overflow rejection matrix |

`integration/protected_offload/provenance.lock.json` records the SHA-256 digest
of every imported RTL file. `make protected-offload-provenance` rejects local
snapshot drift. Imported component results are never counted as subsystem
closure unless that component is exercised in this repository.
