"""Independent operand oracle and a finite, versioned live-closure matrix."""
OPS = ("mul", "mulh", "mulhsu", "mulhu", "div", "divu", "rem", "remu")
CONTEXTS = ("dma", "dual", "sleep", "pressure")
PAIRS = {
    "zero": ((0, 7), (7, 0)),
    "one": ((1, 7), (7, 1)),
    "all_ones": ((0xffffffff, 3), (3, 0xffffffff)),
    "signed_min": ((0x80000000, 3), (3, 0x80000000)),
    "power_two": ((0x40000000, 8), (8, 0x40000000)),
    "other": ((0xfffedcbb, 0x23457), (7, 3)),
}
TIMINGS = ("before", "early", "middle", "late", "finalize", "response", "after")


def signed(value):
    return value - (1 << 32) if value & 0x80000000 else value


def operand_class(lhs, rhs):
    if 0 in (lhs, rhs): return "zero"
    if 1 in (lhs, rhs): return "one"
    if 0xffffffff in (lhs, rhs): return "all_ones"
    if 0x80000000 in (lhs, rhs): return "signed_min"
    if any(value & (value - 1) == 0 for value in (lhs, rhs)): return "power_two"
    return "other"


def expected(opcode, lhs, rhs):
    a, b = signed(lhs), signed(rhs)
    if opcode < 4:
        product = (lhs if opcode in (0, 3) else a) * (rhs if opcode in (0, 2, 3) else b)
        return (product if opcode == 0 else product >> 32) & 0xffffffff
    signed_op = opcode in (4, 6)
    dividend, divisor = (a, b) if signed_op else (lhs, rhs)
    if divisor == 0: return 0xffffffff if opcode in (4, 5) else lhs
    quotient = abs(dividend) // abs(divisor)
    if (dividend < 0) != (divisor < 0): quotient = -quotient
    return (quotient if opcode in (4, 5) else dividend - quotient * divisor) & 0xffffffff


def cases(family):
    rows = []
    if family == "operands":
        for context in CONTEXTS:
            for opcode in range(8):
                for category, pairs in PAIRS.items():
                    for sample, (lhs, rhs) in enumerate(pairs):
                        assert operand_class(lhs, rhs) == category
                        rows.append(dict(context=context, opcode=opcode, category=category,
                                         sample=sample, lhs=lhs, rhs=rhs, delay=0, nops=0, repeats=1))
            for opcode in (4, 6):
                rows.append(dict(context=context, opcode=opcode, category="signed_overflow",
                                 sample=0, lhs=0x80000000, rhs=0xffffffff, delay=0, nops=0, repeats=1))
    elif family == "timing":
        for opcode in range(8):
            for delay in range(64):
                rows.append(dict(context="timing", opcode=opcode, category="delay_sweep",
                                 sample=delay, lhs=0xfffedcbb, rhs=0x23457,
                                 delay=delay, nops=0, repeats=16))
            for category, nops, repeats, delay in (("before", 128, 1, 0), ("after", 0, 1, 128)):
                rows.append(dict(context="timing", opcode=opcode, category=category,
                                 sample=0, lhs=0xfffedcbb, rhs=0x23457,
                                 delay=delay, nops=nops, repeats=repeats))
    else:
        raise ValueError("unknown M permutation family")
    for row in rows:
        row["family"] = family
        row["name"] = f"mperm_{family}_{row['context']}_{row['opcode']}_{row['category']}_{row['sample']:02d}"
        row["expected"] = expected(row["opcode"], row["lhs"], row["rhs"])
        k = 4 if row["context"] == "pressure" or row["category"] == "before" else 64
        batch = 1 if row["context"] in ("pressure", "timing") else 4
        row["spec"] = (row["name"], k, batch, 1, 8, int(row["context"] == "timing"),
                       0, "", "O2", 1, 9200, 0, int(row["context"] in ("dual", "sleep")), -1, "", "none")
    return rows


def assembly(row):
    op = OPS[row["opcode"]]
    return f""".section .text
.align 2
.global m_sweep_probe
.global m_sweep_begin
.global m_sweep_end
m_sweep_probe:
  li a0,0x{row['lhs']:08x}
  li a1,0x{row['rhs']:08x}
  .rept {row['nops']}
  nop
  .endr
m_sweep_begin:
  .rept {row['repeats']}
  {op} a2,a0,a1
  .endr
m_sweep_end:
  li t0,0x{row['expected']:08x}
  xor a0,a2,t0
  sltiu a0,a0,1
  ret
"""
