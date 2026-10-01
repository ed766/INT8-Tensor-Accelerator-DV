#!/usr/bin/env python3
"""Validate trace identity, provenance, and semantic first-hit witnesses."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
csv.field_size_limit(20_000_000)

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
sys.path.insert(0, str(Path(__file__).parent))
from check_crossover_release import validate_cross_witness  # noqa: E402
from check_crossover_trace import events as load_events  # noqa: E402
from stimulus_provenance import cross_generator_hash  # noqa: E402


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def trace_path(name: str) -> Path:
    for path in (ROOT / name, ROOT / "build/protected_offload/shared_firmware" / name):
        if path.is_file():
            return path
    raise SystemExit(f"cross-coverage trace is missing: {name}")


def main() -> int:
    manifest = ROOT / "integration/protected_offload/coverage/compute_crossover_manifest.json"
    report = REPORTS / "compute_crossover_cross_coverage.csv"
    cross_rows = rows(report)
    summary_rows = (rows(REPORTS / "compute_crossover_model.csv") +
                    rows(REPORTS / "compute_crossover_random_model.csv") +
                    rows(REPORTS / "rv32m_instruction_stream_random_model.csv") +
                    rows(REPORTS / "compute_crossover_independent_model.csv"))
    trace_hashes = {row.get("trace", ""): row.get("trace_sha256", "") for row in summary_rows}
    expected_manifest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    expected_generator = cross_generator_hash()
    manifest_data = json.loads(manifest.read_text())
    expected_families = set(manifest_data["required_cross_families"])
    expected_bins = {(family, bin_name) for family, bins in manifest_data["required_cross_bins"].items()
                     for bin_name in bins}
    passed = [row for row in cross_rows if row.get("status") == "PASS"]
    actual_bins = {(row.get("cross_family", ""), row.get("bin", "")) for row in cross_rows}
    if actual_bins != expected_bins:
        raise SystemExit(f"cross-bin denominator differs from manifest: missing={sorted(expected_bins-actual_bins)}; extra={sorted(actual_bins-expected_bins)}")
    if len(passed) != len(cross_rows) or not expected_families.issubset({r.get("cross_family") for r in passed}):
        raise SystemExit("required cross bins/families are not closed")
    cache: dict[Path, dict[str, dict[str, str]]] = {}
    digest_cache: dict[Path, str] = {}
    refs_checked = 0
    for row in cross_rows:
        if row.get("point_type") != "cross_bin" or row.get("manifest_sha256") != expected_manifest or \
                row.get("generator_sha256") != expected_generator:
            raise SystemExit(f"stale or malformed cross row: {row.get('cross_family')}:{row.get('bin')}")
        if int(row.get("independent_test_count", "0")) < 2 and row.get("risk") in {
                "retirement", "ownership", "permission", "recovery"}:
            raise SystemExit(f"high-risk cross lacks independent stimulus: {row.get('cross_family')}:{row.get('bin')}")
        if row.get("risk") in {"retirement", "ownership", "permission", "recovery"}:
            paths = set(filter(None, row.get("construction_paths", "").split(";")))
            if len(paths) < 2:
                raise SystemExit(f"high-risk cross lacks two construction paths: {row.get('cross_family')}:{row.get('bin')} paths={sorted(paths)}")
        refs = row.get("witness_event_ids", "").split(";")
        first_refs = row.get("first_witness_event_ids", "").split(";")
        if not refs or not first_refs or row.get("first_event_ids") != first_refs[0]:
            raise SystemExit(f"cross row has no explicit first-hit witness: {row.get('cross_family')}:{row.get('bin')}")
        if first_refs[0].rsplit("#", 1)[0] != row.get("first_trace"):
            raise SystemExit(f"first-hit witness trace does not match row provenance: {row.get('cross_family')}:{row.get('bin')}")
        contributing_tests = set(row.get("contributing_tests", "").split(";"))
        first_events: list[dict[str, str]] = []
        for ref in refs:
            if "#" not in ref:
                raise SystemExit(f"malformed event reference: {ref}")
            name, eid = ref.rsplit("#", 1)
            if name not in trace_hashes or not eid.isdigit():
                raise SystemExit(f"event reference does not name a strict-replay trace: {ref}")
            path = trace_path(name)
            digest = digest_cache.get(path)
            if digest is None:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                digest_cache[path] = digest
            if digest != trace_hashes[name]:
                raise SystemExit(f"event reference uses a stale trace: {ref}")
            events = cache.get(path)
            if events is None:
                parsed = {}
                for event in load_events(path):
                    event_id = event.get("eid", "")
                    if event_id in parsed:
                        raise SystemExit(f"duplicate observer event ID {event_id} in {name}")
                    parsed[event_id] = event
                cache[path] = events = parsed
            if eid not in events:
                raise SystemExit(f"event ID does not exist: {ref}")
            if events[eid].get("run") not in contributing_tests:
                raise SystemExit(f"witness event comes from an unlisted contributing test: {ref}")
            refs_checked += 1
        for ref in first_refs:
            name, eid = ref.rsplit("#", 1)
            if ref not in refs:
                raise SystemExit(f"first-hit references are not in the complete witness list: {row.get('bin')}")
            first_events.append(cache[trace_path(name)][eid])
        first_path = trace_path(first_refs[0].rsplit("#", 1)[0])
        validate_cross_witness(row, first_events, list(cache[first_path].values()))
    print(f"CROSSOVER_CROSS_WITNESS_CHECK|status=PASS|bins={len(cross_rows)}|events={refs_checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
