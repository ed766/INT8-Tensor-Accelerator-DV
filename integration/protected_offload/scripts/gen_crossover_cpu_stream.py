#!/usr/bin/env python3
"""Generate deterministic RV32IM instruction streams for crossover replay."""
from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path


def generate(seed: int, output: Path) -> str:
    rng = random.Random(seed)
    lines = [
        ".section .text", ".align 2", ".globl generated_cpu_stream",
        "generated_cpu_stream:", "addi sp, sp, -80", "sw ra, 76(sp)",
        "sw s0, 72(sp)", "sw s1, 68(sp)", "sw s2, 64(sp)",
        "sw s3, 60(sp)", "sw s4, 56(sp)", "sw s5, 52(sp)",
        f"li t0, 0x{rng.getrandbits(32):08x}",
        f"li t1, 0x{rng.getrandbits(32):08x}",
        f"li t2, 0x{(rng.getrandbits(31) | 1):08x}",
        "li t6, 1", "csrr s0, misa", "csrr s1, mcycle",
    ]

    # Every seed covers all eight M opcodes with non-constant operands. The
    # surrounding operations and lane accesses vary by seed; all memory stays
    # within the hart's private stack SRAM.
    lines.extend([
        "mul t3, t0, t1", "mulh t4, t0, t1", "mulhsu t5, t0, t2",
        "mulhu s2, t1, t2", "div t3, t0, t1", "divu t4, t0, t2",
        "rem t5, t0, t1", "remu s2, t0, t2",
        "divu a1, t0, zero", "remu a2, t0, zero",
    ])

    for index in range(20):
        imm = rng.randrange(-1024, 1024)
        bit_imm = rng.randrange(0, 2048)
        word_off = rng.choice((0, 4, 8, 12, 16, 20))
        byte_off = word_off + rng.randrange(4)
        half_off = word_off + 2 * rng.randrange(2)
        label = f".Lskip_{index}"
        lines.extend([
            f"addi t0, t0, {imm}",
            f"xori t1, t1, {bit_imm}",
            "add t3, t0, t1", "sub t4, t3, t0", "xor t5, t0, t1",
            "sll t6, t5, t2", "srl a3, t6, t2", "sra a4, t6, t2",
            "slt a5, t0, t1", "sltu a6, t0, t1",
            "sw t3, %d(sp)" % word_off,
            "sb t4, %d(sp)" % byte_off,
            "sh t5, %d(sp)" % half_off,
            "lw a0, %d(sp)" % word_off,
            "lb a1, %d(sp)" % byte_off,
            "lbu a2, %d(sp)" % byte_off,
            "lh a3, %d(sp)" % half_off,
            "lhu a4, %d(sp)" % half_off,
            "mulhsu a5, t0, t2", "mulhu a6, t1, t2",
            "div a7, t0, t2", "divu s3, t1, t2",
            "rem s4, t0, t2", "remu s5, t1, t2",
            # Both branch directions vary across deterministic seeds; the
            # skipped instruction is side-effect free and the target is local.
            f"beq t0, t1, {label}", "addi t0, t0, 1", f"{label}:",
            f"bne t0, t1, {label}_ne", "addi t1, t1, 1", f"{label}_ne:",
        ])
        if index % 4 == 0:
            subroutine = f".Lsubroutine_{index}"
            lines.extend([f"jal ra, {subroutine}", f".Lreturn_{index}:"])
            # The helper returns through the saved return address. A nearby
            # unique call target avoids depending on global testbench state.
            lines.extend([f"j .Lafter_{index}", f"{subroutine}:",
                          "mul t0, t0, t2", "divu t1, t0, t2", "ret",
                          f".Lafter_{index}:"])
        if index % 5 == 0:
            lines.extend(["csrr t3, mcycle", "csrr t4, misa", "fence"])

    lines.extend([
        # Independent dependency motifs used by the crossover cross model:
        # M -> effective address, load -> M -> store, and M -> branch. These
        # are real retired instruction dependencies in every generated stream,
        # not coverage labels inferred from the random seed.
        "addi t0, sp, 0", "addi t1, zero, 1", "mul t2, t0, t1",
        "lw t3, 0(t2)",
        "addi t5, zero, 1", "lw t4, 0(sp)", "mul t6, t4, t5",
        "sw t6, 4(sp)",
        "addi t0, zero, 0", "addi t1, zero, 7", "mul t2, t0, t1",
        "beq t2, zero, .Lgenerated_m_branch", "addi t0, t0, 1",
        ".Lgenerated_m_branch:",
        # Deterministic shift amounts and both conditional-branch outcomes
        # complement the seed-dependent ALU stream and make closure auditable.
        "addi t0, zero, 1", "sll t1, t0, zero", "sll t5, t0, t0",
        "addi t2, zero, 31",
        "srl t3, t1, t2", "sra t4, t1, t2",
        "beq zero, zero, .Lbranch_taken", "addi t5, t5, 1",
        ".Lbranch_taken:", "addi t6, zero, 1",
        "beq zero, t6, .Lbranch_not_taken", "addi t5, t5, 1",
        ".Lbranch_not_taken:", "bne zero, t6, .Lbranch_bne_taken",
        "addi t5, t5, 1", ".Lbranch_bne_taken:",
        "bne t6, t6, .Lbranch_bne_not_taken", "addi t5, t5, 1",
        ".Lbranch_bne_not_taken:",
        "add a0, t0, t1", "xor a0, a0, t3", "lw ra, 76(sp)",
        "lw s0, 72(sp)", "lw s1, 68(sp)", "lw s2, 64(sp)",
        "lw s3, 60(sp)", "lw s4, 56(sp)", "lw s5, 52(sp)",
        "addi sp, sp, 80", "ret", ".globl generated_cpu_stream_end",
        "generated_cpu_stream_end:", "",
        ".align 2", ".globl generated_cpu_stream_abi_probe",
        "generated_cpu_stream_abi_probe:", "addi sp, sp, -16",
        "sw ra, 12(sp)", "sw s3, 8(sp)", "sw s4, 4(sp)", "sw s5, 0(sp)",
        "li s3, 0x13579bdf", "li s4, 0x2468ace0", "li s5, 0x55aa33cc",
        "jal ra, generated_cpu_stream", "li a0, 1",
        "li t0, 0x13579bdf", "bne s3, t0, .Labi_fail",
        "li t0, 0x2468ace0", "bne s4, t0, .Labi_fail",
        "li t0, 0x55aa33cc", "bne s5, t0, .Labi_fail", "j .Labi_done",
        ".Labi_fail:", "li a0, 0", ".Labi_done:",
        "lw s5, 0(sp)", "lw s4, 4(sp)", "lw s3, 8(sp)",
        "lw ra, 12(sp)", "addi sp, sp, 16", "ret", "",
    ])
    text = "\n".join(lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(generate(args.seed, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
