#!/usr/bin/env bash
# Run both implementations against the same ORFS library and clock.
set -euo pipefail
flow=$(realpath "${1:?Pass the OpenROAD Flow Scripts flow directory}")
config=$(realpath "$(dirname "$0")/config.mk")
for depth in 4 8; do
    make -C "$flow" DESIGN_CONFIG="$config" FLOW_VARIANT="fifo$depth" \
        VERILOG_TOP_PARAMS="FIFO_DEPTH $depth" \
        "logs/nangate45/int8_tensor_accel/fifo$depth/6_report.log"
done
