export DESIGN_NAME = int8_tensor_accel
export PLATFORM = nangate45
INT8_CONFIG_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export VERILOG_FILES = $(abspath $(INT8_CONFIG_DIR)../../rtl/int8_tensor_accel.sv)
export SDC_FILE = $(INT8_CONFIG_DIR)constraints.sdc
export CORE_UTILIZATION = 35
export SYNTH_HDL_FRONTEND = slang
export PLACE_DENSITY = 0.50
