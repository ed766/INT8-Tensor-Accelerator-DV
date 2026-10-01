PYTHON ?= $(shell if python3 -c 'import torch' >/dev/null 2>&1; then command -v python3; elif [ -x ../rl-venv/bin/python ]; then printf '%s' ../rl-venv/bin/python; else command -v python3; fi)
HOSTCHECK_PYTHON ?= python3
VERILATOR ?= verilator

.PHONY: vectors portable-vectors portable-check axi-integration-check model-selftest linear-demo mlp-demo fx-compiler-check lint regress streaming-check protocol-edges coverage code-coverage mutation-check formal-check performance-report synth-check docs-check project-check release-check rv32-benchmark-toolchain-check rv32-benchmark-build rv32-benchmark-smoke rv32-benchmark-check rv32-benchmark-sweep rv32-benchmark-backpressure rv32-benchmark-mutations rv32-benchmark-report rv32-benchmark-waveform rv32-benchmark-release-check protected-offload-provenance protected-offload-service-check protected-offload-smoke protected-offload-components protected-offload-directed protected-offload-firmware protected-offload-uvm protected-offload-random protected-offload-model-check protected-offload-formal protected-offload-mutations protected-offload-coverage protected-offload-code-coverage protected-offload-cache-ownership protected-offload-shared-compiler protected-offload-shared-random protected-offload-error protected-offload-error-reset protected-offload-error-context compute-host-check compute-crossover-checker-selftest compute-crossover-protocol-check compute-crossover-directed compute-crossover-random compute-crossover-model compute-crossover-mutations compute-crossover-coverage compute-crossover-code-coverage compute-crossover-cross-check compute-crossover-dashboard compute-crossover-repro-check rv32-external-iss-check compute-crossover-release-check compute-crossover-schema3-smoke compute-crossover-schema3-cache-smoke rv32m-core-random protected-offload-performance protected-offload-matched-performance protected-offload-report protected-offload-release-check clean
.PHONY: compute-crossover-cross-check compute-crossover-code-coverage

vectors:
	$(PYTHON) scripts/generate_vectors.py

portable-vectors:
	$(PYTHON) scripts/generate_portable_vectors.py

portable-check: portable-vectors
	$(PYTHON) scripts/run_portable_validation.py

axi-integration-check: portable-vectors
	$(PYTHON) scripts/run_axi_integration.py

model-selftest:
	$(PYTHON) scripts/model_selftest.py

linear-demo:
	$(PYTHON) scripts/pytorch_linear_demo.py

mlp-demo:
	$(PYTHON) scripts/pytorch_mlp_demo.py
	$(PYTHON) scripts/run_mlp_demo.py

fx-compiler-check:
	$(PYTHON) scripts/run_fx_graphs.py

lint:
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET --top-module int8_tensor_accel rtl/int8_tensor_accel.sv sim/int8_accel_assertions.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET --top-module int8_accel_health_monitor rtl/int8_accel_health_monitor.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL --top-module int8_accel_axi_wrapper rtl/int8_tensor_accel.sv rtl/int8_accel_health_monitor.sv rtl/int8_accel_axi_wrapper.sv
	$(VERILATOR) --lint-only --timing --assert -Wall --top-module int8_portable_record_decoder rtl/int8_portable_record_decoder.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL --top-module int8_portable_accel_top rtl/int8_tensor_accel.sv rtl/int8_accel_health_monitor.sv rtl/int8_portable_record_decoder.sv rtl/int8_portable_accel_top.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY -Wno-TIMESCALEMOD -Wno-VARHIDDEN -Wno-BLKSEQ --top-module rv32_int8_benchmark_top integration/rv32_offload/rv32/rv32_core.sv integration/rv32_offload/rv32/rv32_rom_feeder.sv rtl/int8_tensor_accel.sv rtl/int8_accel_health_monitor.sv rtl/int8_accel_axi_wrapper.sv integration/rv32_offload/rtl/apb_to_axil_bridge.sv integration/rv32_offload/rtl/apb_axis_mailbox.sv integration/rv32_offload/rtl/rv32_int8_benchmark_top.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL --top-module protected_offload_dma integration/protected_offload/rtl/protected_queue_count_next.sv integration/protected_offload/rtl/protected_offload_dma.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL --top-module protected_offload_apb_csr integration/protected_offload/rtl/protected_offload_apb_csr.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL --top-module protected_dma_axi_adapter integration/protected_offload/rtl/protected_dma_axi_adapter.sv
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-SYNCASYNCNET -Wno-UNUSEDSIGNAL -Wno-PINCONNECTEMPTY -Wno-TIMESCALEMOD -Wno-VARHIDDEN -Wno-BLKSEQ --top-module rv32_protected_offload_top integration/protected_offload/vendor/rv32/rv32_core.sv integration/protected_offload/vendor/rv32/rv32_rom_feeder.sv integration/protected_offload/vendor/axi/dma_iommu.sv rtl/int8_tensor_accel.sv integration/protected_offload/rtl/protected_queue_count_next.sv integration/protected_offload/rtl/protected_offload_dma.sv integration/protected_offload/rtl/protected_offload_apb_csr.sv integration/protected_offload/rtl/rv32_protected_offload_top.sv

rv32-benchmark-toolchain-check:
	$(PYTHON) integration/rv32_offload/scripts/check_environment.py

rv32-benchmark-build: rv32-benchmark-toolchain-check
	mkdir -p build/rv32_benchmark/smoke
	$(PYTHON) integration/rv32_offload/scripts/generate_benchmark.py --k 4 --batch 1 --mode warm --pattern random --seed 1 --output-dir build/rv32_benchmark/smoke
	$(PYTHON) integration/rv32_offload/scripts/build_firmware.py --scenario-dir build/rv32_benchmark/smoke

rv32-benchmark-smoke: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py smoke

rv32-benchmark-check: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py correctness

rv32-benchmark-sweep: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py sweep

rv32-benchmark-backpressure: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py backpressure

rv32-benchmark-mutations: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py mutations

rv32-benchmark-report:
	$(PYTHON) integration/rv32_offload/scripts/generate_report.py

rv32-benchmark-waveform: rv32-benchmark-toolchain-check
	$(PYTHON) integration/rv32_offload/scripts/run_benchmark.py smoke --waveform
	$(PYTHON) integration/rv32_offload/scripts/generate_waveform_svg.py

rv32-benchmark-release-check: rv32-benchmark-sweep rv32-benchmark-check rv32-benchmark-backpressure rv32-benchmark-mutations rv32-benchmark-report
	git diff --check

protected-offload-provenance:
	$(PYTHON) integration/protected_offload/scripts/generate_address_map.py
	$(PYTHON) integration/protected_offload/scripts/check_provenance.py

protected-offload-service-check:
	$(PYTHON) integration/protected_offload/scripts/check_service_boundary.py
	$(PYTHON) integration/protected_offload/scripts/run_host_bridge.py
	$(PYTHON) integration/protected_offload/scripts/run_irq_aggregator.py
	$(PYTHON) integration/protected_offload/scripts/run_tlb_control.py
	$(PYTHON) integration/protected_offload/scripts/run_endpoints.py

protected-offload-shared-check: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py

protected-offload-shared-matrix: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --matrix

protected-offload-cache-ownership: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --cache
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --negative

protected-offload-shared-compiler: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --compiler

protected-offload-shared-random: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --random
	$(PYTHON) integration/protected_offload/scripts/generate_shared_coverage.py

protected-offload-error-reset: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --error-reset

protected-offload-error: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --error

protected-offload-error-context: protected-offload-error protected-offload-error-reset
	$(PYTHON) integration/protected_offload/scripts/check_error_reset_context.py

compute-host-check: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --combined
	$(HOSTCHECK_PYTHON) integration/protected_offload/scripts/check_compute_host_evidence.py --from-summary --report reports/compute_host_evidence.csv

compute-crossover-directed: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --crossover --model

compute-crossover-random: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --random --model

rv32m-core-random: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --cpu-random --count 100 --model

compute-crossover-model: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --matrix --model

compute-crossover-checker-selftest: compute-crossover-schema3-smoke
	$(PYTHON) integration/protected_offload/scripts/check_crossover_trace_selftest.py
	$(HOSTCHECK_PYTHON) -m unittest discover -s integration/protected_offload/scripts -p 'test_*.py'
	$(HOSTCHECK_PYTHON) integration/protected_offload/scripts/test_compute_host_evidence.py
	$(PYTHON) integration/protected_offload/scripts/test_coverage_provenance.py
	$(PYTHON) integration/protected_offload/scripts/test_ownership_ranges.py
	$(PYTHON) integration/protected_offload/scripts/test_reset_evidence.py

.PHONY: compute-crossover-independent
.PHONY: compute-crossover-clean-check
compute-crossover-clean-check:
	$(PYTHON) integration/protected_offload/scripts/run_clean_checkout.py

compute-crossover-independent:
	PROTECTED_FIRMWARE_IMPLEMENTATION=independent $(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --model

compute-crossover-schema3-smoke:
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --schema3-smoke --model

compute-crossover-schema3-cache-smoke:
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --schema3-cache-smoke --model

compute-crossover-protocol-check: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_component_checks.py
	$(PYTHON) integration/protected_offload/scripts/run_endpoints.py
	$(PYTHON) integration/protected_offload/scripts/run_tlb_control.py

compute-crossover-mutations:
	$(PYTHON) integration/protected_offload/scripts/run_crossover_mutations.py
	$(PYTHON) integration/protected_offload/scripts/check_crossover_mutations.py
	$(PYTHON) integration/protected_offload/scripts/check_tag_lifetime_mutation.py

compute-crossover-coverage: compute-crossover-directed compute-crossover-independent
	$(PYTHON) integration/protected_offload/scripts/generate_compute_crossover_coverage.py
	$(PYTHON) integration/protected_offload/scripts/generate_crossover_cross_coverage.py
	$(PYTHON) integration/protected_offload/scripts/check_crossover_cross_coverage.py

compute-crossover-cross-check:
	$(PYTHON) integration/protected_offload/scripts/check_crossover_cross_coverage.py

compute-crossover-code-coverage: protected-offload-provenance
	@test -f ../ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/environment.sh || { echo "Missing pinned Verilator environment from ucie_chiplet_soc"; exit 1; }
	bash -c 'source ../ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/environment.sh && $(PYTHON) integration/protected_offload/scripts/run_compute_crossover_code_coverage.py'

compute-crossover-dashboard:
	$(PYTHON) integration/protected_offload/scripts/generate_crossover_dashboard.py

rv32-external-iss-check:
	@test -f ../ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/environment.sh || { echo "Missing pinned external RV32 tools"; exit 1; }
	bash -c 'source ../ucie_chiplet_soc/chiplet_extension/build/external_riscv_tools/environment.sh && $(PYTHON) ../ucie_chiplet_soc/chiplet_extension/scripts/run_external_iss.py --require --isa rv32im_zicsr'
	$(MAKE) -C ../ucie_chiplet_soc/chiplet_extension rv32-act-m-check

compute-crossover-repro-check:
	$(PYTHON) integration/protected_offload/scripts/check_crossover_reproducibility.py

compute-crossover-release-check: compute-crossover-checker-selftest compute-crossover-schema3-cache-smoke compute-crossover-protocol-check compute-crossover-directed compute-crossover-random compute-crossover-model rv32m-core-random rv32-external-iss-check compute-crossover-independent compute-crossover-coverage compute-crossover-code-coverage compute-crossover-mutations protected-offload-error-context compute-host-check protected-offload-formal compute-crossover-repro-check
	$(HOSTCHECK_PYTHON) integration/protected_offload/scripts/check_compute_host_evidence.py --from-summary --report reports/compute_host_evidence.csv
	$(PYTHON) integration/protected_offload/scripts/check_crossover_release.py
	$(PYTHON) integration/protected_offload/scripts/generate_crossover_dashboard.py
	$(PYTHON) scripts/check_docs.py
	git diff --check

protected-offload-smoke:
	$(PYTHON) integration/protected_offload/scripts/run_protected_offload.py smoke

protected-offload-components:
	$(PYTHON) integration/protected_offload/scripts/run_component_checks.py

protected-offload-directed:
	$(PYTHON) integration/protected_offload/scripts/run_protected_offload.py directed

protected-offload-firmware:
	$(PYTHON) integration/protected_offload/scripts/run_firmware_matrix.py

protected-offload-uvm:
	@echo "PROTECTED_OFFLOAD_UVM|status=NOT_APPLICABLE|detail=firmware/APB is canonical; reusable UVM/VIP remains in AXI4 QoS fabric project"

protected-offload-random:
	$(PYTHON) integration/protected_offload/scripts/run_protected_offload.py random

protected-offload-model-check: protected-offload-directed protected-offload-random
	$(PYTHON) integration/protected_offload/scripts/run_protected_offload.py coverage
	$(PYTHON) integration/protected_offload/scripts/check_traces.py

protected-offload-formal:
	$(PYTHON) integration/protected_offload/scripts/run_formal.py

protected-offload-mutations:
	$(PYTHON) integration/protected_offload/scripts/run_mutations.py
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --define PROTECTED_MUT_FALSE_MAINTENANCE
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --define PROTECTED_MUT_CACHE_RESPONSE_CORRUPT
	$(PYTHON) integration/protected_offload/scripts/merge_integration_mutations.py

protected-offload-coverage: protected-offload-model-check
	$(PYTHON) integration/protected_offload/scripts/generate_coverage.py

protected-offload-code-coverage:
	$(PYTHON) integration/protected_offload/scripts/run_code_coverage.py

protected-offload-performance:
	$(PYTHON) integration/protected_offload/scripts/run_protected_offload.py performance
	$(PYTHON) integration/protected_offload/scripts/generate_performance.py
	$(PYTHON) integration/protected_offload/scripts/generate_visuals.py

protected-offload-matched-performance: protected-offload-provenance
	$(PYTHON) integration/protected_offload/scripts/run_shared_firmware.py --benchmark
	$(PYTHON) integration/protected_offload/scripts/run_matched_performance.py
	$(PYTHON) integration/protected_offload/scripts/generate_matched_visual.py

protected-offload-report:
	$(PYTHON) scripts/generate_metrics.py
	$(PYTHON) scripts/check_docs.py

protected-offload-release-check: protected-offload-provenance protected-offload-service-check protected-offload-shared-matrix protected-offload-cache-ownership protected-offload-shared-compiler protected-offload-shared-random protected-offload-error-context compute-host-check protected-offload-smoke protected-offload-components protected-offload-firmware protected-offload-coverage protected-offload-code-coverage protected-offload-formal compute-crossover-release-check protected-offload-performance protected-offload-matched-performance protected-offload-report
	git diff --check

regress: vectors
	$(PYTHON) scripts/run_regression.py

streaming-check:
	$(PYTHON) scripts/run_streaming.py

protocol-edges:
	$(PYTHON) scripts/run_protocol_edges.py

coverage: vectors
	$(PYTHON) scripts/generate_coverage.py

code-coverage: vectors
	$(PYTHON) scripts/run_code_coverage.py

mutation-check: vectors
	PATH="$(dir $(shell command -v $(PYTHON))):$$PATH" $(PYTHON) scripts/run_mutations.py

formal-check:
	$(PYTHON) scripts/run_formal.py

performance-report: regress
	$(PYTHON) scripts/generate_performance.py

synth-check:
	$(PYTHON) scripts/run_synthesis.py

docs-check:
	$(PYTHON) scripts/check_docs.py

project-check: model-selftest linear-demo vectors mlp-demo lint regress streaming-check protocol-edges portable-check axi-integration-check coverage performance-report

release-check: project-check fx-compiler-check mutation-check formal-check code-coverage synth-check
	$(PYTHON) scripts/generate_metrics.py
	$(PYTHON) scripts/check_docs.py
	git diff --check

clean:
	rm -rf build
