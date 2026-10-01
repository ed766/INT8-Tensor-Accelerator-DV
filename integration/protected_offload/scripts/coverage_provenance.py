"""Bind native coverage to the simulator, sources and execution that produced it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(root: Path, case: Path, sources: list[Path], version: str,
                   build_id: str, scenario: str, exit_code: int) -> None:
    artifacts = {name: sha256(case / name) for name in
                 ("integration_coverage.dat", "crossover.trace", "firmware.elf")}
    manifest = {"schema": 1, "scenario": scenario, "simulator_version": version,
                "source_build_id": build_id, "simulation_exit_code": exit_code,
                "sources": {str(path.relative_to(root)): sha256(path) for path in sources},
                "artifacts": artifacts}
    (case / "coverage_provenance.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n")


def validate_manifest(root: Path, case: Path, row: dict[str, str], version: str) -> None:
    path = case / "coverage_provenance.json"
    if not path.is_file():
        raise ValueError(f"{case.name}: no execution-bound coverage provenance; rerun coverage")
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != 1 or manifest.get("scenario") != row.get("scenario"):
        raise ValueError(f"{case.name}: invalid coverage provenance identity")
    if manifest.get("simulation_exit_code") != 0:
        raise ValueError(f"{case.name}: coverage came from a failing simulation")
    if manifest.get("simulator_version") != version:
        raise ValueError(f"{case.name}: coverage simulator version differs from pinned runner")
    if manifest.get("source_build_id") != row.get("source_build_id"):
        raise ValueError(f"{case.name}: model/run and coverage source identities differ")
    artifacts = manifest.get("artifacts", {})
    if set(artifacts) != {"integration_coverage.dat", "crossover.trace", "firmware.elf"}:
        raise ValueError(f"{case.name}: incomplete artifact hashes")
    for name, expected in artifacts.items():
        if not (case / name).is_file() or sha256(case / name) != expected:
            raise ValueError(f"{case.name}: stale or altered coverage artifact {name}")
    if artifacts["firmware.elf"] != row.get("elf_sha256"):
        raise ValueError(f"{case.name}: run firmware does not match coverage firmware")
    sources = manifest.get("sources", {})
    if not sources:
        raise ValueError(f"{case.name}: missing source hashes")
    for name, expected in sources.items():
        source = root / name
        if source.resolve().is_relative_to(root.resolve()) is False or not source.is_file() or sha256(source) != expected:
            raise ValueError(f"{case.name}: source changed since coverage execution: {name}")
