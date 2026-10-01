#!/usr/bin/env python3
"""Emit a small scenario-specific RV32 firmware witness routine.

The common integration driver still owns setup and teardown. Each directed
configuration gets its own executable microprogram with a unique private-RAM
location, data token, operation sequence, and return signature. The observer
trace is checked against all of those details, so an ELF/marker difference
alone cannot qualify a directed case.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


FAMILIES = ("cpu_rv32m", "apb_axi", "queues_configuration", "translation_recovery",
            "interrupts", "cache_ownership", "combined_services", "reset_transport")


def render(name: str, scenario_id: int) -> str:
    family, sep, suffix = name.partition("__")
    if not sep or family not in FAMILIES:
        raise ValueError(f"unknown directed scenario name: {name}")
    case = (5 if suffix == "input_bus_error" else
            int(suffix.rsplit("_", 1)[1]))
    if scenario_id not in range(1, 49) or (FAMILIES.index(family) * 6 + case) != scenario_id:
        raise ValueError(f"scenario id does not match directed matrix row: {name}={scenario_id}")
    # Distinct instruction classes across each six-case family. All operands
    # remain in a safe range and every routine performs an actual SRAM
    # store/load/derived-store signature while DMA/service work is outstanding.
    operations = {
        1: f"addi t3, t2, {case}",
        2: f"xori t3, t2, {scenario_id & 0x7ff}",
        3: f"slli t3, t2, {case}",
        4: f"srli t3, t2, {case}",
        5: f"ori t3, t2, {scenario_id & 0x7ff}",
        6: f"andi t3, t2, 0x7ff",
    }
    addr = 0x1000 + scenario_id * 8
    token = 0x53000000 | scenario_id
    signature = 0x43520000 | scenario_id
    # Write the instruction sequence's derived result to a private scratch
    # word. This is intentionally distinct from the driver marker in BSS.
    return f"""/* generated from directed scenario {name}; do not edit */
    .section .text.crossover_scenario,\"ax\",@progbits
    .align 2
    .globl crossover_scenario_program
    .globl crossover_scenario_program_end
    .type crossover_scenario_program,@function
crossover_scenario_program:
    li t0, {addr}
    li t1, 0x{token:08x}
    sw t1, 0(t0)
    lw t2, 0(t0)
    bne t2, t1, 1f
    {operations[case]}
    xor t4, t3, t1
    sw t4, 4(t0)
    li a0, 0x{signature:08x}
    ret
1:
    li a0, 0
    ret
crossover_scenario_program_end:
    .size crossover_scenario_program, .-crossover_scenario_program
"""


def generate(name: str, scenario_id: int, path: Path) -> str:
    text = render(name, scenario_id)
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()
