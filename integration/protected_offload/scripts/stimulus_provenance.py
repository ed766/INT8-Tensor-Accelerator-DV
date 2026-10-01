"""Attribute a coverage witness to the code that activates it, not its name.

The generated scenario signature only touches private SRAM; it is not an
independent implementation of descriptor, translation, or ownership traffic.
Generated CPU instructions qualify only when a cited retirement is inside
the linked stream symbol range checked by the release validator.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[3]
SHARED = ROOT / "integration/protected_offload/firmware/shared_offload.c"
CPU_GENERATOR = ROOT / "integration/protected_offload/scripts/gen_crossover_cpu_stream.py"
INDEPENDENT = ROOT / "integration/protected_offload/firmware/independent_offload.c"


def cross_generator_hash() -> str:
    fingerprint=hashlib.sha256()
    generator=Path(__file__).with_name("generate_crossover_cross_coverage.py")
    for source in (generator,Path(__file__),SHARED,CPU_GENERATOR,INDEPENDENT):
        fingerprint.update(str(source.relative_to(ROOT)).encode())
        fingerprint.update(source.read_bytes())
    return fingerprint.hexdigest()


def witness_implementation(summary: dict[str, str], witness: list[dict[str, str]]) -> str:
    source = SHARED
    if summary.get("stimulus_origin")=="independent_firmware_driver":
        expected=hashlib.sha256(INDEPENDENT.read_bytes()).hexdigest()
        if summary.get("stimulus_generator_sha256")!=expected:
            raise ValueError("independent firmware source provenance is missing or stale")
        source=INDEPENDENT
    if summary.get("stimulus_origin") == "generated_cpu_instruction_stream":
        try:
            start = int(summary["cpu_stream_start_pc"], 16)
            end = int(summary["cpu_stream_end_pc"], 16)
            activated = any(event.get("kind") == "RETIRE" and
                            start <= int(event.get("pc", "0"), 16) < end for event in witness)
        except (KeyError, ValueError):
            activated = False
        if activated:
            source = CPU_GENERATOR
    return f"{source.relative_to(ROOT)}:{hashlib.sha256(source.read_bytes()).hexdigest()}"
