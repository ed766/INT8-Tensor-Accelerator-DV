#!/usr/bin/env bash
# Generate an independent arithmetic program and run it on Spike.
set -euo pipefail
upstream=$(realpath "${1:?Pass a RISCV-DV checkout}")
output=$(realpath -m "${2:?Pass a new output directory}")
revision=f557b89ed6881a20515481a2585e9d004cd9642b
if [[ $(git -C "$upstream" rev-parse HEAD) != "$revision" ]]; then
    echo "Expected RISCV-DV revision $revision" >&2
    exit 1
fi
if [[ -e "$output" ]]; then
    echo "Choose a new output directory" >&2
    exit 1
fi
export RISCV_GCC="$(command -v riscv64-unknown-elf-gcc)"
export RISCV_OBJCOPY="$(command -v riscv64-unknown-elf-objcopy)"
cd "$upstream"
python3 run.py --target rv32imc --simulator pyflow --test riscv_arithmetic_basic_test \
    --seed 2601 --steps gen,gcc_compile --gen_timeout 600 --output "$output"
timeout 60 spike --log-commits --isa=rv32imc_zicsr_zifencei --priv=m -l \
    "$output/asm_test/riscv_arithmetic_basic_test_0.o" >"$output/spike.log" 2>&1
grep -qE 'mem 0x[[:xdigit:]]+ 0x00000001$' "$output/spike.log"
echo "RISCV-DV pyflow arithmetic program passed on Spike"
