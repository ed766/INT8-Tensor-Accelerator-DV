#!/usr/bin/env python3
"""Compare generated RV32IM arithmetic on the vendored core and Spike."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REVISION = "f557b89ed6881a20515481a2585e9d004cd9642b"
SPIKE_COMMIT = re.compile(r"core\s+0:\s+3\s+0x([\da-f]+)\s+\(0x([\da-f]+)\)(.*)")
REGISTER = re.compile(r"\bx(\d+)\s+0x([\da-f]+)")


def run(*args, cwd=ROOT, timeout=120):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise SystemExit(result.stdout)
    return result.stdout


def spike_records(log, terminal):
    started = False
    for line in log.splitlines():
        match = SPIKE_COMMIT.fullmatch(line.strip())
        if not match:
            continue
        pc, insn = (int(item, 16) for item in match.groups()[:2])
        if not started and pc < 0x1000:
            continue
        started = True
        if pc < 0x1000:
            raise SystemExit("Spike left the arithmetic image")
        fields = match[3]
        if " mem " in fields:
            raise SystemExit("Unexpected memory transaction in arithmetic image")
        register = REGISTER.search(fields)
        yield pc, insn, int(register[1]) if register else 0, int(register[2], 16) if register else 0
        if pc == terminal:
            return
    raise SystemExit("Spike did not reach the terminal PC")


def replay(upstream, output, binary, seed):
    case = output / str(seed)
    case.mkdir(exist_ok=True)
    prefix = case / "generated"
    generated = case / "generated_0.S"
    generated.unlink(missing_ok=True)
    generator = upstream / "pygen/pygen_src/test/riscv_instr_base_test.py"
    run(sys.executable, str(generator), "--num_of_tests=1", "--start_idx=0",
        f"--asm_file_name={prefix}", f"--log_file_name={case / 'generator.log'}",
        "--target=rv32imc", "--gen_test=riscv_instr_base_test", f"--seed={seed}",
        "--instr_cnt=1024", "--num_of_sub_program=0",
        "--directed_instr_0=riscv_int_numeric_corner_stream,4", "--no_fence=1",
        "--no_data_page=1", "--no_branch_jump=1", "--boot_mode=m",
        "--no_csr_instr=1", "--disable_compressed_instr=1", cwd=upstream)
    source = generated.read_text()
    body = re.search(r"^init:(.*?)^test_done:", source, re.M | re.S)
    if not body:
        raise SystemExit("RISCV-DV assembly has no init-to-test_done region")
    assembly = case / "replay.S"
    assembly.write_text(
        ".option norvc\n.text\n.globl _start\n_start:" + body[1]
        + "test_done:\n"
        + "  li t0, 0x80000001\n  li t1, 3\n  remu t2, t0, t1\n"
        + "replay_end: j replay_end\n.balign 16\nuser_stack_end:\n"
    )
    linker = case / "replay.ld"
    linker.write_text("ENTRY(_start)\nPHDRS { text PT_LOAD FLAGS(5); }\n"
                      "SECTIONS { . = 0x1000; .text : { *(.text) } :text }\n")
    elf = case / "replay.elf"
    run("riscv64-unknown-elf-gcc", "-march=rv32im_zicsr", "-mabi=ilp32",
        "-nostdlib", "-nostartfiles", "-Wl,--no-relax,--build-id=none", "-T", str(linker),
        str(assembly), "-o", str(elf))
    symbols = run("riscv64-unknown-elf-nm", str(elf))
    terminal = int(re.search(r"^([\da-f]+) \w replay_end$", symbols, re.M)[1], 16)
    words_file = case / "replay.bin"
    run("riscv64-unknown-elf-objcopy", "-O", "binary", "-j", ".text", str(elf), str(words_file))
    data = words_file.read_bytes()
    if len(data) % 4 or 0x1000 + len(data) > 0x4000:
        raise SystemExit("Unexpected arithmetic image size")
    image = case / "replay.hex"
    image.write_text("@0\n0000106f\n@400\n" + "".join(
        f"{int.from_bytes(data[i:i+4], 'little'):08x}\n" for i in range(0, len(data), 4)
    ))
    spike = run("spike", "--isa=rv32im_zicsr", "--priv=m", "--pc=0x1000",
                "--disable-dtb", "-m0x1000:0xf000", "--instructions=8192",
                "-l", "--log-commits", str(elf))
    rtl = run(str(binary), f"+IMAGE={image}", f"+TERMINAL={terminal:x}")
    (case / "spike.log").write_text(spike)
    (case / "rtl.log").write_text(rtl)
    expected = list(spike_records(spike, terminal))
    observed = []
    for line in rtl.splitlines():
        if line.startswith("REPLAY,"):
            _, pc, insn, rd, value = line.split(",")
            observed.append((int(pc, 16), int(insn, 16), int(rd), int(value, 16)))
    if not observed or observed.pop(0) != (0, 0x0000106f, 0, 0):
        raise SystemExit(f"Seed {seed}: invalid RTL reset trampoline")
    for index, (gold, actual) in enumerate(zip(expected, observed)):
        if gold != actual:
            raise SystemExit(f"Seed {seed} retirement {index}: Spike {gold}, RTL {actual}")
    if len(expected) != len(observed):
        raise SystemExit(f"Seed {seed}: Spike {len(expected)} retires, RTL {len(observed)}")
    m_opcodes = sorted({(insn >> 12) & 7 for _, insn, _, _ in expected
                        if insn & 0x7f == 0x33 and insn >> 25 == 1})
    directed_start = int(re.search(r"^([\da-f]+) \w test_done$", symbols, re.M)[1], 16)
    generated_m = sorted({(insn >> 12) & 7 for pc, insn, _, _ in expected
                          if pc < directed_start and insn & 0x7f == 0x33 and insn >> 25 == 1})
    return dict(seed=seed, matched_retires=len(expected), m_funct3=m_opcodes,
                generated_m_funct3=generated_m,
                generated_assembly_sha256=hashlib.sha256(generated.read_bytes()).hexdigest(),
                elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    if run("git", "rev-parse", "HEAD", cwd=upstream).strip() != REVISION:
        raise SystemExit(f"Expected RISCV-DV revision {REVISION}")
    output = ROOT / "build/riscv_dv_rtl"
    output.mkdir(parents=True, exist_ok=True)
    report = output / "summary.json"
    report.unlink(missing_ok=True)
    vendor = ROOT / "integration/protected_offload/vendor/rv32"
    sim = output / "obj"
    run("verilator", "--binary", "--timing", "-Wno-PINMISSING", "-Wno-TIMESCALEMOD", "-j", "4",
        "--top-module", "tb_riscv_dv_replay", "--Mdir", str(sim),
        str(vendor / "rv32_muldiv.sv"), str(vendor / "rv32_core.sv"),
        str(ROOT / "integration/protected_offload/sim/tb_riscv_dv_replay.sv"))
    rows = [replay(upstream, output, sim / "Vtb_riscv_dv_replay", seed)
            for seed in (2601, 2602, 2603)]
    if set().union(*(row["m_funct3"] for row in rows)) != set(range(8)):
        raise SystemExit(f"Replay did not exercise every M opcode: {rows}")
    report.write_text(json.dumps(rows, indent=2) + "\n")
    print(report.read_text(), end="")


if __name__ == "__main__":
    main()
