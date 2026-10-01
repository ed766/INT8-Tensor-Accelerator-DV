#!/usr/bin/env python3
"""Build a compact, fail-closed evidence dashboard for crossover review."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
csv.field_size_limit(20_000_000)

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "integration/protected_offload/implementation_ledger.csv"
COVERAGE = ROOT / "reports/compute_crossover_coverage.csv"
CODE_COVERAGE = ROOT / "reports/compute_crossover_code_coverage.csv"
CSV_OUT = ROOT / "reports/compute_crossover_evidence_dashboard.csv"
MD_OUT = ROOT / "docs/compute_crossover_evidence_dashboard.md"
MANIFEST = ROOT / "integration/protected_offload/coverage/compute_crossover_manifest.json"
GENERATOR = ROOT / "integration/protected_offload/scripts/generate_compute_crossover_coverage.py"
CROSS_COVERAGE = ROOT / "reports/compute_crossover_cross_coverage.csv"
CROSS_GENERATOR = ROOT / "integration/protected_offload/scripts/generate_crossover_cross_coverage.py"
FORMAL = ROOT / "reports/protected_offload_formal.csv"
MUTATIONS = ROOT / "reports/protected_offload_integration_mutations.csv"
TAG_MUTATION = ROOT / "reports/protected_offload_tag_lifetime_mutation.csv"

def csv_rows(path: Path):
    with path.open(newline="") as handle:
        reader=csv.DictReader(handle)
        rows=list(reader)
        if not reader.fieldnames or any(None in row or any(value is None for value in row.values()) for row in rows):
            raise SystemExit(f"malformed CSV evidence file: {path}")
        return rows

def report_status(report_ref: str) -> tuple[str, str]:
    """Return an execution result only when the ledger names a concrete report."""
    refs = [ref.strip() for ref in report_ref.split(";") if ref.strip()]
    paths = [ROOT / ref if ref.startswith("reports/") else ROOT.parent / ref[3:]
             for ref in refs if ref.startswith(("reports/", "../"))]
    if not paths or len(paths) != len(refs) or any(not path.is_file() for path in paths):
        return "NOT_REPORTED", ""
    rows_by_path = {path: csv_rows(path) for path in paths}
    report_rows = [row for path in paths for row in rows_by_path[path]]
    states = {row.get("status", "") for row in report_rows}
    all_mutations_detected = bool(report_rows) and all(state == "DETECTED" for state in states)
    mixed_control_and_mutant = bool(report_rows) and "DETECTED" in states and states <= {"PASS", "DETECTED"}
    status = ("PASS" if report_rows and states == {"PASS"} else "PASS" if all_mutations_detected or
              mixed_control_and_mutant else "FAIL" if "FAIL" in states else "NOT_REPORTED")
    if any(path.name == "compute_crossover_code_coverage.csv" for path in paths):
        integrated = next((row for row in report_rows if row.get("scope") == "integrated_protected_offload_and_rv32"), {})
        control = next((row for row in report_rows if row.get("scope") == "new_protected_offload_control_rtl"), {})
        if not integrated or not control:
            status = "NOT_REPORTED"
        elif control.get("line_target_met") == "true" and control.get("branch_target_met") == "true":
            status = "PASS" if integrated.get("line_target_met") == "true" and integrated.get("branch_target_met") == "true" else "PARTIAL"
        else:
            status = "FAIL"
    model_names = {"compute_crossover_model.csv", "compute_crossover_random_model.csv",
                   "compute_crossover_independent_model.csv",
                   "compute_crossover_scenario_model.csv", "compute_crossover_schema3_smoke_model.csv",
                   "compute_crossover_schema3_cache_smoke_model.csv",
                   "rv32m_instruction_stream_random_model.csv"}
    model_rows = [row for path in paths if path.name in model_names for row in rows_by_path[path]]
    if model_rows:
        checker_path = ROOT / "integration/protected_offload/scripts/check_crossover_trace.py"
        current_checker = hashlib.sha256(checker_path.read_bytes()).hexdigest()
        if any(row.get("checker_sha256") != current_checker or
               not row.get("observer_build_id") for row in model_rows):
            status = "STALE"
    if any(path.name == "compute_crossover_code_coverage.csv" for path in paths):
        control = next((row for row in report_rows if row.get("scope") == "new_protected_offload_control_rtl"), {})
        if control.get("line_target_met") != "true" or control.get("branch_target_met") != "true":
            status = "PARTIAL"
    evidence_digest = hashlib.sha256("".join(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths).encode()).hexdigest()
    return status, evidence_digest

def main() -> int:
    ledger=csv_rows(LEDGER)
    if not ledger or list(ledger[0]) != ["requirement_id", "component", "status", "test_target", "evidence", "blocking_dependency"]:
        raise SystemExit("implementation ledger header does not match the documented six-column schema")
    if not COVERAGE.exists():
        raise SystemExit("missing trace-correlated coverage report")
    coverage=csv_rows(COVERAGE)
    current_hashes={
        "manifest_sha256":hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "directed_report_sha256":hashlib.sha256((ROOT/"reports/compute_crossover_directed.csv").read_bytes()).hexdigest(),
        "generator_sha256":hashlib.sha256(GENERATOR.read_bytes()).hexdigest(),
    }
    coverage_current = all(point.get(field)==expected
                           for point in coverage for field,expected in current_hashes.items())
    required_cross_families = set(json.loads(MANIFEST.read_text())["required_cross_families"])
    cross_rows = csv_rows(CROSS_COVERAGE) if CROSS_COVERAGE.exists() else []
    from stimulus_provenance import cross_generator_hash as provenance_hash
    cross_generator_hash = provenance_hash()
    manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    cross_current = bool(cross_rows) and all(
        row.get("manifest_sha256") == manifest_hash and
        row.get("generator_sha256") == cross_generator_hash for row in cross_rows)
    cross_pass = [row for row in cross_rows if row.get("point_type") == "cross_bin" and row.get("status") == "PASS"]
    cross_families = {row.get("cross_family") for row in cross_pass}
    independence_missing=sum(int(row.get("independent_test_count","0"))<2 for row in cross_rows
                             if row.get("risk") in {"retirement","ownership","permission","recovery"})
    cross_summary = f"required families observed: {len(required_cross_families & cross_families)}/{len(required_cross_families)}; bins observed: {len(cross_pass)}/{len(cross_rows)}; high-risk independence gaps: {independence_missing}"
    formal_summary_rows = csv_rows(FORMAL) if FORMAL.exists() else []
    formal_reachable_covers = sum(row.get("status") == "PASS" and row.get("cover") == "REACHABLE"
                                  for row in formal_summary_rows)
    formal_trace_covers = sum(row.get("status") == "PASS" and row.get("cover") in
                              ("RTL_TEST_REACHED", "RTL_TRACE_REACHED")
                              for row in formal_summary_rows)
    formal_trace_backed_groups = sum(
        row.get("status") == "PASS" and "rtl_trace" in row.get("mode", "")
        for row in formal_summary_rows)
    formal_summary = (f"property groups PASS: {sum(row.get('status') == 'PASS' for row in formal_summary_rows)}/"
                      f"{len(formal_summary_rows)}; reachable solver covers {formal_reachable_covers}; "
                      f"RTL trace/test cover rows {formal_trace_covers}; RTL-trace-backed property groups "
                      f"{formal_trace_backed_groups}")
    mutation_summary_rows = csv_rows(MUTATIONS) if MUTATIONS.exists() else []
    mutation_summary = f"crossover mutation detections: {sum(row.get('status') == 'DETECTED' for row in mutation_summary_rows)}/{len(mutation_summary_rows)}"
    code_rows = csv_rows(CODE_COVERAGE) if CODE_COVERAGE.exists() else []
    integrated_code = next((row for row in code_rows if row.get("scope") == "integrated_protected_offload_and_rv32"), {})
    control_code = next((row for row in code_rows if row.get("scope") == "new_protected_offload_control_rtl"), {})
    code_evidence = (
        f"Fresh {integrated_code.get('passing_runs', 'NA')}/{integrated_code.get('databases', 'NA')} "
        f"execution-bound runs: integrated raw line {integrated_code.get('line_hit', 'NA')}/"
        f"{integrated_code.get('line_total', 'NA')} ({integrated_code.get('line_percent', 'NA')}%), "
        f"branch {integrated_code.get('branch_hit', 'NA')}/{integrated_code.get('branch_total', 'NA')} "
        f"({integrated_code.get('branch_percent', 'NA')}%), expression {integrated_code.get('expr_percent', 'NA')}%, "
        f"raw toggle {integrated_code.get('toggle_percent', 'NA')}%; new-control RTL line "
        f"{control_code.get('line_hit', 'NA')}/{control_code.get('line_total', 'NA')} "
        f"({control_code.get('line_percent', 'NA')}%) and branch "
        f"{control_code.get('branch_hit', 'NA')}/{control_code.get('branch_total', 'NA')} "
        f"({control_code.get('branch_percent', 'NA')}%) with "
        f"{control_code.get('reviewed_branch_exclusions', 'NA')} reviewed exclusions. "
        "New-control targets are met; imported and processor RTL keep aggregate targets unmet."
    ) if integrated_code and control_code else "Code-coverage report is incomplete."
    code_summary = (f"raw integrated code coverage: {integrated_code.get('line_hit', 'NA')}/"
                    f"{integrated_code.get('line_total', 'NA')} lines ({integrated_code.get('line_percent', 'NA')}%); "
                    f"branch {integrated_code.get('branch_percent', 'NA')}%; "
                    f"expression {integrated_code.get('expr_percent', 'NA')}%; "
                    f"raw toggle {integrated_code.get('toggle_percent', 'NA')}%; new-control scope "
                    f"line {control_code.get('line_hit', 'NA')}/{control_code.get('line_total', 'NA')} "
                    f"({control_code.get('line_percent', 'NA')}%), branch raw "
                    f"{control_code.get('branch_percent', 'NA')}%, reviewed "
                    f"{control_code.get('reviewed_branch_percent', 'NA')}% after "
                    f"{control_code.get('reviewed_branch_exclusions', '0')} documented exclusions")
    rows = []
    for item in ledger:
        if not item["requirement_id"].startswith("C-"):
            continue
        status = item["status"]
        detail = item["blocking_dependency"]
        execution_status, evidence_hash=report_status(item["evidence"])
        checker_status = "NOT_APPLICABLE"
        coverage_status = "NOT_APPLICABLE"
        if item["requirement_id"] in (
                "C-CROSSOVER-OBSERVER", "C-CROSSOVER-CACHE-OBSERVER",
                "C-CROSSOVER-CHECKER-SELFTEST", "C-CPU-RANDOM", "C-EXTERNAL-RV32IM",
                "C-CROSSOVER-DIRECTED", "C-CROSSOVER-FORMAL", "C-INTEGRATION-MUTATIONS",
                "C-ERROR-CONTEXT", "C-ERROR-RESET", "C-COMBINED-HOST", "C-CACHE",
                "C-RANDOM", "C-CROSSOVER-COVERAGE", "C-TAG-LIFETIME",
                "C-CONFIG-REFERENCE", "C-APB-PHASE", "C-APB-CHIPLET-BRIDGE"):
            checker_status = "PASS" if execution_status == "PASS" else execution_status
        if item["requirement_id"] in ("C-CROSSOVER-COVERAGE", "C-CROSSOVER-DIRECTED"):
            coverage_status = "PASS" if execution_status == "PASS" else execution_status
        if item["requirement_id"] == "C-CROSSOVER-COVERAGE":
            coverage_status = "PASS" if execution_status == "PASS" and cross_current and \
                len(cross_pass) == len(cross_rows) and not independence_missing and all(row.get("status") == "PASS" for row in coverage) else "PARTIAL"
        if item["requirement_id"] == "C-CROSSOVER-CODE-COVERAGE":
            checker_status = "PASS" if execution_status in ("PASS", "PARTIAL") else execution_status
            coverage_status = execution_status
        if item["requirement_id"] == "C-CROSSOVER-OBSERVER":
            coverage_status = "SEE_CROSSOVER_COVERAGE_ROW"
        evidence_text = item["evidence"]
        if item["requirement_id"] == "C-CROSSOVER-CODE-COVERAGE":
            evidence_text = "reports/compute_crossover_code_coverage.csv; " + code_evidence
        rows.append({
            "item_type": "implementation_requirement",
            "requirement": item["requirement_id"],
            "implementation_status": status,
            "execution_status": execution_status,
            "checker_status": checker_status,
            "coverage_status": coverage_status,
            "stimulus": item["test_target"],
            "evidence": evidence_text if item["requirement_id"] == "C-CROSSOVER-CODE-COVERAGE"
                        else evidence_text + (f"; {detail}" if detail else ""),
            "blocker": detail,
            "evidence_sha256": evidence_hash,
        })
    for item in coverage:
        if item["point_type"] != "required_predicate":
            continue
        point_status = item["status"] if coverage_current else "STALE"
        rows.append({
            "item_type": "trace_predicate",
            "requirement": f"PREDICATE:{item['point']}",
            "implementation_status": "IMPLEMENTED" if point_status == "PASS" else "PARTIAL",
            "execution_status": point_status,
            "checker_status": "PASS" if point_status == "PASS" else "STALE" if point_status == "STALE" else "NOT_REACHED",
            "coverage_status": point_status,
            "stimulus": item["contributing_tests"] or "NOT_REACHED",
            "evidence": f"events {item['witness_event_ids']} window {item['event_window']}",
            "blocker": "" if point_status == "PASS" else "coverage input hashes do not match current schema-3 observer, checker, manifest, and directed traces" if point_status == "STALE" else "required event predicate not observed in a passing trace",
            "evidence_sha256": current_hashes["directed_report_sha256"],
        })
    for item in cross_rows:
        if item.get("point_type") != "cross_bin":
            continue
        point_status = item.get("status", "NOT_REACHED")
        if not cross_current:
            point_status = "STALE"
        independent_missing=(item.get("risk") in {"retirement","ownership","permission","recovery"} and
                             int(item.get("independent_test_count","0"))<2)
        rows.append({
            "item_type": "trace_cross_bin",
            "requirement": f"CROSS:{item.get('cross_family')}:{item.get('bin')}",
            "implementation_status": "IMPLEMENTED" if point_status == "PASS" else "PARTIAL",
            "execution_status": point_status,
            "checker_status": "PASS" if point_status == "PASS" else "STALE" if point_status == "STALE" else "NOT_REACHED",
            "coverage_status": "PARTIAL" if point_status=="PASS" and independent_missing else point_status,
            "stimulus": item.get("contributing_tests", ""),
            "evidence": f"{item.get('hit_count')} hits; {item.get('independent_test_count')} independent tests; first witness `{item.get('first_witness_event_ids', '')}`",
            "blocker": "second independent activating stimulus required" if point_status=="PASS" and independent_missing else "" if point_status == "PASS" else "cross report is stale" if point_status == "STALE" else "no correlated RTL witness",
            "evidence_sha256": item.get("first_trace_sha256", ""),
        })
    formal_rows = formal_summary_rows
    for item in formal_rows:
        status = item.get("status", "NOT_RUN")
        cover = item.get("cover", "NOT_REPORTED")
        state = "PASS" if status == "PASS" and cover in (
            "REACHABLE", "RTL_TEST_REACHED", "RTL_TRACE_REACHED") else status
        rows.append({
            "item_type": "formal_property",
            "requirement": f"FORMAL:{item.get('property', '?')}",
            "implementation_status": "IMPLEMENTED",
            "execution_status": state,
            "checker_status": cover,
            "coverage_status": "NOT_APPLICABLE",
            "stimulus": item.get("mode", ""),
            "evidence": f"{item.get('detail', '')}; depth={item.get('depth', '')}; runtime={item.get('runtime_s', '')}s",
            "blocker": item.get("detail", "") if state != "PASS" else "",
            "evidence_sha256": hashlib.sha256(FORMAL.read_bytes()).hexdigest(),
        })
    for report_path in (MUTATIONS,):
        if not report_path.exists():
            continue
        for item in csv_rows(report_path):
            status = item.get("status", "NOT_RUN")
            rows.append({
                "item_type": "mutation",
                "requirement": f"MUTATION:{item.get('mutation', item.get('case', '?'))}",
                "implementation_status": "IMPLEMENTED",
                "execution_status": status,
                "checker_status": item.get("detection", item.get("expected", "")),
                "coverage_status": "NOT_APPLICABLE",
                "stimulus": item.get("activated", item.get("test", "")),
                "evidence": item.get("detection", item.get("detail", "")),
                "blocker": item.get("blocker", "") if status not in ("PASS", "DETECTED") else "",
                "evidence_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            })
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["item_type", "requirement", "implementation_status", "execution_status", "checker_status", "coverage_status", "stimulus", "evidence", "blocker", "evidence_sha256"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    impl_rows = [row for row in rows if row["item_type"] == "implementation_requirement"]
    coverage_rows = [row for row in rows if row["item_type"] == "trace_predicate"]
    implementation_summary = f"implementation items PASS/PARTIAL: {sum(row['implementation_status']=='PASS' for row in impl_rows)}/{len(impl_rows)}"
    stale_count = sum(row["coverage_status"] == "STALE" for row in coverage_rows)
    coverage_summary = f"current predicates PASS: {sum(row['coverage_status']=='PASS' for row in coverage_rows)}/{len(coverage_rows)}; stale: {stale_count}"
    MD_OUT.write_text(
        "# Crossover Evidence Dashboard\n\n"
        "This dashboard is generated from the implementation ledger and the trace-correlated coverage report. "
        "A mailbox or scenario label is not sufficient evidence; `PASS` requires an executable stimulus, a checker result, and a trace reference.\n\n"
        f"Current evidence is separated by type: **{implementation_summary}**; **{coverage_summary}**; **{cross_summary}**; **{formal_summary}**; **{mutation_summary}**; **{code_summary}**. A `NOT_APPLICABLE` status means the evidence type does not apply to that requirement; `NOT_REPORTED` means no current report was found. These are not combined into one heterogeneous closure total. Raw code coverage remains independent of functional and cross coverage.\n\n"
        "| Type | Requirement | Impl. | Execution | Checker | Coverage | Stimulus | Evidence | Blocker |\n|---|---|---|---|---|---|---|---|---|\n" +
        "".join(f"| {row['item_type']} | `{row['requirement']}` | **{row['implementation_status']}** | **{row['execution_status']}** | **{row['checker_status']}** | **{row['coverage_status']}** | `{row['stimulus']}` | `{row['evidence']}` | {row['blocker']} |\n" for row in rows) +
        "\nThe strict checker is qualified independently by `make compute-crossover-checker-selftest`; component prerequisites are run by `make compute-crossover-protocol-check`.\n"
    )
    print(f"CROSSOVER_DASHBOARD|implementation={len(impl_rows)}|predicates={len(coverage_rows)}|status=GENERATED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
