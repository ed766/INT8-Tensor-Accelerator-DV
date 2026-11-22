SIM ?= verilator
TOPLEVEL_LANG = verilog
COCOTB_TOPLEVEL = int8_accel_axi_wrapper
COCOTB_TEST_MODULES = test_int8_axi
VERILOG_SOURCES = $(addprefix $(abspath ../../rtl)/,int8_tensor_accel.sv int8_accel_health_monitor.sv int8_accel_axi_wrapper.sv)
SIM_BUILD = ../../build/cocotb_axi/$(SIM)
COCOTB_RESULTS_FILE = $(SIM_BUILD)/results.xml
include $(shell cocotb-config --makefiles)/Makefile.sim
