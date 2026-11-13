#!/usr/bin/env python3
"""Require bounded safety and reachable control covers at production geometry."""
import os
import subprocess
from pathlib import Path

from run_formal import ROOT, find_sby


def abstract_result(build):
    source = (ROOT / "rtl/int8_tensor_accel.sv").read_text()
    start = "        packed_result = '0;\n"
    end = "        if (last_chunk) begin\n          result_fifo_data"
    declaration = "  integer bank_index;"
    if any(source.count(marker) != 1 for marker in (start, end, declaration)):
        raise SystemExit("The RTL changed around the 4x4 datapath abstraction")
    before, datapath = source.split(start)
    _, after = datapath.split(end)
    before = before.replace(declaration, """  (* anyseq *) logic [OUTPUTS*8-1:0] formal_result;

  integer bank_index;""")
    (build / "int8_tensor_accel_abstract.sv").write_text(
        before + "        packed_result = formal_result;\n"
        + "        perf_input_chunks <= perf_input_chunks + 1'b1;\n"
        + end + after
    )


def main():
    sby = find_sby()
    if not sby:
        raise SystemExit("4x4 formal requires SymbiYosys and Boolector")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    abstract_result(build)
    log = build / "formal_4x4.log"
    env = dict(os.environ, PATH=f"{Path(sby).parent}:{os.environ.get('PATH', '')}")
    with log.open("w") as output:
        run = subprocess.run(
            [sby, "-f", "--prefix", str(build / "formal_4x4"), "int8_control_4x4.sby"],
            cwd=ROOT / "formal", env=env, stdout=output, stderr=subprocess.STDOUT,
        )
    if run.returncode:
        raise SystemExit(f"4x4 formal failed; see {log}")
    print("4x4 formal: depth-24 safety and six reachability covers PASS")


if __name__ == "__main__":
    main()
