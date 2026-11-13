#!/usr/bin/env python3
"""Check DMA handshakes and partial completion with independently stalled peers."""
import subprocess

from run_peer_hole_checks import native_points
from run_stateful_crossover import ROOT

BASE = ROOT / "integration/protected_offload"
TOP = "tb_dma_peer_holes"
STALL_BRANCHES = {451, 461, 475, 483, 491, 504}


def main():
    cases = (
        ("nominal", [], "DMA_MEMORY_FAULTS_PASS"),
        ("early_completion", ["-DPROTECTED_MUT_EARLY_COMPLETION"], "memory request hold"),
    )
    for name, defines, expected in cases:
        build = ROOT / "build/protected_offload/dma_stall_faults" / name
        build.mkdir(parents=True, exist_ok=True)
        harness = build / "main.cpp"
        harness.write_text("""#include "Vtb_dma_peer_holes.h"
#include "verilated.h"
#include "verilated_cov.h"

int main(int argc, char** argv) {
    VerilatedContext context;
    context.commandArgs(argc, argv);
    Vtb_dma_peer_holes dut(&context);
    while (!context.gotFinish()) {
        dut.eval();
        context.timeInc(1);
    }
    dut.final();
    VerilatedCov::write("coverage.dat");
}
""")
        with (build / "compile.log").open("w") as log:
            subprocess.run(
                ["verilator", "--cc", "--exe", "--build", "--timing", "--assert", "--coverage", "-DSYNTHESIS", "-Wno-fatal",
                 "--top-module", TOP, "--Mdir", str(build), *defines,
                 str(BASE / "rtl/protected_queue_count_next.sv"),
                 str(BASE / "rtl/protected_offload_dma.sv"), str(BASE / f"sim/{TOP}.sv"), str(harness)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
            )
        for seed in (11, 97):
            database = build / "coverage.dat"
            database.unlink(missing_ok=True)
            run = subprocess.run(
                [str(build / f"V{TOP}"), "+MEMORY_FAULTS", f"+SEED={seed}"],
                cwd=build, capture_output=True, text=True, timeout=60,
            )
            output = run.stdout + run.stderr
            (build / f"seed_{seed}.log").write_text(output)
            # A compile failure, timeout, or unrelated assertion cannot qualify a mutation.
            if expected not in output or (run.returncode == 0) != (name == "nominal"):
                raise SystemExit(f"DMA stall/fault {name} seed {seed} failed; see {build}")
            if name == "nominal":
                branches = {
                    int(line) for (file, line, kind, option, _), hits
                    in native_points(database).items()
                    if file.endswith("/protected_offload_dma.sv")
                    and kind == "branch" and option == "else" and hits
                }
                if missing := STALL_BRANCHES - branches:
                    raise SystemExit(f"Uncovered DMA wait branches: {sorted(missing)}")
                database.replace(build / f"coverage_{seed}.dat")
                phases = {phase for phase in range(7) if f"|phase={phase}|waits=" in output}
                if phases != set(range(7)):
                    raise SystemExit(f"Missing DMA stall witnesses: {set(range(7)) - phases}")
    print("DMA stall/fault checks: 2/2 nominal, six wait branches per seed, and 2/2 qualified early-completion detections")


if __name__ == "__main__":
    main()
