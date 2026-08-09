PYTHON ?= python3
VERILATOR ?= verilator

.PHONY: vectors model-selftest linear-demo lint regress streaming-check coverage code-coverage mutation-check performance-report synth-check docs-check project-check release-check clean

vectors:
	$(PYTHON) scripts/generate_vectors.py

model-selftest:
	$(PYTHON) scripts/model_selftest.py

linear-demo:
	$(PYTHON) scripts/pytorch_linear_demo.py

lint:
	$(VERILATOR) --lint-only --timing --assert -Wall -Wno-fatal -Wno-SYNCASYNCNET --top-module int8_tensor_accel rtl/int8_tensor_accel.sv sim/int8_accel_assertions.sv

regress: vectors
	$(PYTHON) scripts/run_regression.py

streaming-check:
	$(PYTHON) scripts/run_streaming.py

coverage: vectors
	$(PYTHON) scripts/generate_coverage.py

code-coverage: vectors
	$(PYTHON) scripts/run_code_coverage.py

mutation-check: vectors
	PATH="$(dir $(shell command -v $(PYTHON))):$$PATH" $(PYTHON) scripts/run_mutations.py

performance-report: regress
	$(PYTHON) scripts/generate_performance.py

synth-check:
	$(PYTHON) scripts/run_synthesis.py

docs-check:
	$(PYTHON) scripts/check_docs.py

project-check: model-selftest linear-demo lint regress streaming-check coverage performance-report

release-check: project-check mutation-check code-coverage synth-check
	$(PYTHON) scripts/generate_metrics.py
	$(PYTHON) scripts/check_docs.py
	git diff --check

clean:
	rm -rf build
