#!/usr/bin/env python3
"""Run actual shared-top crossover firmware with Verilator coverage enabled."""
from __future__ import annotations

import csv
import argparse
import subprocess
import os
from functools import cache
from pathlib import Path
from coverage_provenance import validate_manifest

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "reports/compute_crossover_code_coverage.csv"
RUN_REPORT = ROOT / "reports/compute_crossover_code_coverage_runs.csv"
CASES = ROOT / "build/protected_offload/shared_firmware"


@cache
def ownership_monitor_lines(path: str, guard: str = "PROTECTED_OWNERSHIP_CHECKS") -> frozenset[int]:
    """Classify verification-only blocks by guards, not shifting line numbers."""
    stack: list[bool] = []
    result: set[int] = set()
    for number, source in enumerate((ROOT / path).read_text().splitlines(), 1):
        text = source.strip()
        if text.startswith(("`ifdef ", "`ifndef ")):
            stack.append(text == "`ifdef " + guard)
        if any(stack):
            result.add(number)
        if text.startswith("`endif") and stack:
            stack.pop()
    return frozenset(result)


def scope_for(path: str, line: str = "") -> str:
    if path.startswith("integration/protected_offload/rtl/"):
        if path.endswith("/rv32_protected_shared_top.sv") and line.isdigit() and int(line) in ownership_monitor_lines(path,"TEST_FABRIC_CONTENDER"):
            return "verification_contention_generator"
        if path.endswith("/protected_axi_sram.sv"):
            return "verification_memory_target_model"
        if path.endswith("/rv32_protected_shared_top.sv") and line.isdigit() and (
                int(line) in ownership_monitor_lines(path)):
            return "verification_ownership_monitor"
        return "new_protected_offload_control_rtl"
    if path.startswith("integration/protected_offload/vendor/rv32/"):
        return "rv32_core_and_feeder"
    if path.startswith("integration/protected_offload/vendor/cache/"):
        return "imported_l1_cache"
    if path.startswith("integration/protected_offload/vendor/axi/"):
        return "imported_axi_fabric_and_iommu"
    if path.startswith("integration/protected_offload/vendor/chiplet/"):
        return "imported_chiplet"
    if path.startswith("rtl/"):
        return "accelerator"
    if path.startswith("integration/protected_offload/sim/"):
        return "verification_observer_and_testbench"
    return "other_instrumented_rtl"


def main() -> int:
    global REPORT, RUN_REPORT
    simulator_version = ""
    for tool in ("verilator", "verilator_coverage"):
        version = subprocess.run([tool, "--version"], text=True, capture_output=True)
        reported = version.stdout + version.stderr
        if version.returncode or "5.049" not in reported:
            raise SystemExit(f"coverage requires pinned {tool} 5.049; found {reported.strip() or 'unavailable'}")
        if tool == "verilator":
            simulator_version = version.stdout.strip()
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse", action="store_true",
                        help="regenerate summaries from the latest coverage databases")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="rebuild the 257-run index from isolated coverage-lane reports")
    parser.add_argument("--stateful", action="store_true", help="isolated directed and seeded stateful coverage, not canonical closure")
    parser.add_argument("--refresh-family", help="rerun a stateful family and replace only its provenance-bound native rows")
    args = parser.parse_args()
    prefix = "compute_stateful" if args.stateful else "compute_crossover"
    if args.stateful:
        from stateful_cases import cases, random_cases
    expected = len(cases()) + len(random_cases()) if args.stateful else 257
    if args.stateful:
        if args.rebuild_index:
            raise SystemExit("stateful coverage has one isolated lane; no rebuild-index")
        REPORT = ROOT / "reports/compute_stateful_code_coverage.csv"
        RUN_REPORT = ROOT / "reports/compute_stateful_code_coverage_runs.csv"
        if args.refresh_family:
            from stateful_cases import cases, random_cases
            selected={c['name'] for c in cases()+random_cases() if args.refresh_family in (c['family'],c['name'])}
            if not selected:raise SystemExit("unknown stateful refresh family")
            subprocess.run(["python3",str(Path(__file__).with_name("run_shared_firmware.py")),"--model","--code-coverage"],
                           cwd=ROOT,env=dict(os.environ,PROTECTED_STATEFUL=args.refresh_family),check=True)
            with (ROOT/f"reports/compute_stateful_{args.refresh_family}_coverage_runs.csv").open(newline="") as handle:
                refreshed=list(csv.DictReader(handle))
            if {r['scenario'] for r in refreshed}!=selected or any(r['status']!='PASS' for r in refreshed):
                raise SystemExit("refresh requires all selected native runs to pass")
            with RUN_REPORT.open(newline="") as handle:combined=[r for r in csv.DictReader(handle) if r['scenario'] not in selected]
            combined.extend(refreshed)
            with RUN_REPORT.open("w",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=combined[0],lineterminator="\n");writer.writeheader();writer.writerows(combined)
            args.reuse=True
        if not args.reuse:
            combined = []
            for family in ("all", "random"):
                subprocess.run(["python3", str(Path(__file__).with_name("run_shared_firmware.py")), "--model", "--code-coverage"],
                               cwd=ROOT, env=dict(os.environ, PROTECTED_STATEFUL=family), check=True)
                with (ROOT / f"reports/compute_stateful_{family}_coverage_runs.csv").open(newline="") as handle:
                    combined.extend(csv.DictReader(handle))
            with RUN_REPORT.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=combined[0], lineterminator="\n")
                writer.writeheader(); writer.writerows(combined)
            args.reuse = True
    elif args.refresh_family:
        raise SystemExit("--refresh-family requires --stateful")
    rows: list[dict[str, str]] = []
    if args.rebuild_index:
        sources = [ROOT / f"reports/compute_crossover_coverage_runs_{lane}.csv"
                   for lane in ("directed", "random", "cpu", "edges", "cache")]
        rebuilt: dict[str, dict[str, str]] = {}
        for source in sources:
            with source.open(newline="") as handle:
                for model_row in csv.DictReader(handle):
                    scenario = model_row.get("scenario", "")
                    trace = model_row["trace"]
                    rebuilt[scenario] = {"scenario": scenario, "status": model_row.get("status", ""),
                        "trace": trace, "elf_sha256": model_row.get("elf_sha256", ""),
                        "source_build_id": model_row.get("source_build_id", "")}
        if len(rebuilt) != 257 or any(row.get("status") != "PASS" for row in rebuilt.values()):
            raise SystemExit(f"canonical coverage index requires 257 unique passing runs; got {len(rebuilt)}")
        rows = list(rebuilt.values())
        fields = sorted({field for row in rows for field in row})
        with RUN_REPORT.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
    if args.reuse:
        with RUN_REPORT.open(newline="") as handle:
            collected = list(csv.DictReader(handle))
        by_scenario: dict[str, dict[str, str]] = {}
        for row in collected:
            previous = by_scenario.get(row.get("scenario", ""))
            if previous is None:
                by_scenario[row.get("scenario", "")] = row
            elif any(previous.get(field) != row.get(field)
                     for field in ("trace", "elf_sha256", "source_build_id", "status")):
                raise SystemExit(f"duplicate coverage scenario has conflicting provenance: {row.get('scenario')}")
        rows = list(by_scenario.values())
    else:
        lanes = ((["--crossover"], 48, True),
                 (["--random", "--count", "100"], 100, True),
                 (["--cpu-random", "--count", "100"], 100, True),
                 (["--coverage-edges"], 1, True),
                 (["--cache"], 8, True))
        for lane_args, expected_count, strict_model in lanes:
            print(f"COVERAGE_LANE|phase=start|args={' '.join(lane_args)}|expected={expected_count}", flush=True)
            model_arg = ["--model"] if strict_model else []
            run = subprocess.run([
                "python3", str(ROOT / "integration/protected_offload/scripts/run_shared_firmware.py"),
                *lane_args, *model_arg, "--code-coverage",
            ], cwd=ROOT, text=True, capture_output=True)
            print(run.stdout, end="")
            if run.returncode:
                print(run.stderr)
                return run.returncode
            with RUN_REPORT.open(newline="") as handle:
                lane_rows = list(csv.DictReader(handle))
            if len(lane_rows) != expected_count or any(row.get("status") != "PASS" for row in lane_rows):
                raise SystemExit(f"coverage lane {lane_args} expected {expected_count} passing runs, got {len(lane_rows)}")
            print(f"COVERAGE_LANE|phase=complete|passed={len(lane_rows)}", flush=True)
            rows.extend(lane_rows)
        fields = sorted({field for row in rows for field in row})
        with RUN_REPORT.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    databases = [ROOT / Path(row["trace"]).parent / "integration_coverage.dat" for row in rows]
    if len(rows) != expected or len({row.get("scenario") for row in rows}) != expected or \
            any(not path.is_file() for path in databases):
        missing = [str(path) for path in databases if not path.is_file()]
        raise SystemExit(f"expected {expected} passing coverage runs with unique DBs; got {len(rows)} rows; missing={missing[:3]}")
    if any(row.get("status") != "PASS" for row in rows):
        raise SystemExit("coverage lane contains a failing integration scenario")
    for row, database in zip(rows, databases):
        try:
            validate_manifest(ROOT, database.parent, row, simulator_version)
        except (ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
    # Parse native Verilator point types directly.  Its LCOV exporter converts
    # expression and toggle points into DA/BRDA rows, so treating that output
    # as source line/branch coverage inflates both denominators.
    point_hits: dict[tuple[str, str, str, str, str, str], int] = {}
    edge_group = f"targeted_edges_{sum(c['family']=='edges' for c in cases())}" if args.stateful else "targeted_edges"
    gap_group=f"advanced_gap_{sum(c['family'].startswith('gap_') for c in cases())}" if args.stateful else "advanced_gap"
    groups=("original_23", edge_group, "end_to_end_8", gap_group, "seeded_jobs_32") if args.stateful else ("original_23",edge_group,"seeded_jobs_32")
    group_hits = {name: {} for name in groups}
    stateful_groups = ({c["name"]: gap_group if c["family"].startswith('gap_') else "end_to_end_8" if c["family"]=="end_to_end" else edge_group if c["family"]=="edges" else "original_23" for c in cases()}
                       if args.stateful else {})
    for run_row, database in zip(rows, databases):
        group = stateful_groups.get(run_row["scenario"], "seeded_jobs_32")
        for record in database.read_text(errors="replace").splitlines():
            if not record.startswith("C '"):
                continue
            body = record[3:record.rfind("'")]
            try:
                count = int(record[record.rfind("'") + 1:].strip() or "0")
            except ValueError:
                continue
            meta: dict[str, str] = {}
            for field in body.split("\x01"):
                if "\x02" in field:
                    key, value = field.split("\x02", 1)
                    meta[key] = value
            # Verilator 5.049 records native point type in the page name
            # (for example ``v_line`` and ``v_branch``), not a separate
            # ``t`` field. Keep the latter as a forward-compatible fallback.
            point_type = meta.get("t", "")
            if not point_type:
                page_kind = meta.get("page", "").split("/", 1)[0]
                point_type = page_kind.removeprefix("v_")
            source = meta.get("f", "")
            if point_type not in {"line", "branch", "expr", "toggle"} or not source:
                continue
            if "/integration/protected_offload/rtl/" not in source and "/integration/protected_offload/vendor/" not in source:
                continue
            source_path = Path(source)
            rel = str(source_path.relative_to(ROOT)) if source_path.is_absolute() else source
            # Aggregate the source point over the executed configuration and
            # instance matrix. Verilator's page field encodes elaboration
            # specializations (USE_CACHE/ENABLE_CHIPLET) and instance suffixes;
            # counting those as distinct source branches would penalize legal
            # configurations that structurally remove the same branch.
            if point_type == "line":
                identity = (rel, meta.get("l", ""), "", point_type, "", "")
            else:
                identity = (rel, meta.get("l", ""), meta.get("n", ""),
                            point_type, "", meta.get("o", ""))
            point_hits[identity] = max(point_hits.get(identity, 0), count)
            if args.stateful:
                group_hits[group][identity] = max(group_hits[group].get(identity, 0), count)

    kinds = ("line", "branch", "expr", "toggle")
    point_sets: dict[str, dict[tuple[str, str, str, str, str, str], int]] = {
        scope: {} for scope in ("integrated_protected_offload_and_rv32",)
    }
    for identity, count in point_hits.items():
        scope = scope_for(identity[0], identity[1])
        point_sets.setdefault(scope, {})[identity] = count
        if identity[0].startswith("integration/protected_offload/vendor/rv32/"):
            module_scope = Path(identity[0]).stem
            point_sets.setdefault(module_scope, {})[identity] = count
        point_sets["integrated_protected_offload_and_rv32"][identity] = count

    scope_rows: list[dict[str, str]] = []
    summary_values: dict[str, dict[str, tuple[int, int, float | None]]] = {}
    reviewed_branch_exclusions: list[dict[str, str]] = []
    defensive_defaults = {
        ("integration/protected_offload/rtl/protected_dma_axi_adapter.sv", "129"):
            "Defensive FSM default; state is initialized to IDLE and all legal transitions remain within the declared state enum.",
        ("integration/protected_offload/rtl/protected_host_axi_bridge.sv", "54"):
            "Defensive FSM default; state is initialized to IDLE and all legal transitions remain within the declared state enum.",
        ("integration/protected_offload/rtl/protected_offload_dma.sv", "522"):
            "Defensive DMA FSM default; state is initialized to IDLE and all legal transitions remain within the declared state enum.",
    }
    for scope, points in sorted(point_sets.items()):
        values: dict[str, tuple[int, int, float | None]] = {}
        for kind in kinds:
            selected = [(identity, count) for identity, count in points.items() if identity[3] == kind]
            hit_count = sum(count > 0 for _, count in selected)
            total_count = len(selected)
            pct = 100.0 * hit_count / total_count if total_count else None
            values[kind] = (hit_count, total_count, pct)
        summary_values[scope] = values
        line_hit, line_total, line_pct = values["line"]
        branch_hit, branch_total, branch_pct = values["branch"]
        excluded = 0
        if scope == "new_protected_offload_control_rtl":
            for (path, line_no, number, point_type, page, option), count in sorted(point_hits.items()):
                rationale = defensive_defaults.get((path, line_no))
                if rationale and point_type == "branch" and count == 0:
                    excluded += 1
                    reviewed_branch_exclusions.append({"rtl_file": path, "line": line_no,
                        "point": number, "page": page, "option": option,
                        "hit_count": str(count), "rationale": rationale})
        reviewed_total = branch_total - excluded
        reviewed_pct = (100.0 * branch_hit / reviewed_total) if reviewed_total else None
        expr_hit, expr_total, expr_pct = values["expr"]
        toggle_hit, toggle_total, toggle_pct = values["toggle"]
        scope_rows.append({"scope": scope, "passing_runs": len(rows), "databases": len(databases),
                           "line_hit": line_hit, "line_total": line_total,
                           "line_percent": f"{line_pct:.2f}" if line_pct is not None else "NA",
                           "branch_hit": branch_hit, "branch_total": branch_total,
                           "branch_percent": f"{branch_pct:.2f}" if branch_pct is not None else "NA",
                           "reviewed_branch_hit": branch_hit, "reviewed_branch_total": reviewed_total,
                           "reviewed_branch_percent": f"{reviewed_pct:.2f}" if reviewed_pct is not None else "NA",
                           "reviewed_branch_exclusions": excluded,
                           "expr_hit": expr_hit, "expr_total": expr_total,
                           "expr_percent": f"{expr_pct:.2f}" if expr_pct is not None else "NA",
                           "toggle_hit": toggle_hit, "toggle_total": toggle_total,
                           "toggle_percent": f"{toggle_pct:.2f}" if toggle_pct is not None else "NA",
                           "line_target_percent": "95", "branch_target_percent": "90",
                           "line_target_met": str(line_pct is not None and line_pct >= 95).lower(),
                           "branch_target_met": str(branch_pct is not None and branch_pct >= 90).lower()})

    point_path = ROOT / f"reports/{prefix}_code_coverage_points.csv"
    with point_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scope", "rtl_file", "line", "hit_count", "status"], lineterminator="\n")
        writer.writeheader()
        writer.writerows({"scope": scope_for(path, line_no), "rtl_file": path, "line": int(line_no), "hit_count": count,
                          "status": "HIT" if count else "UNCOVERED"}
                         for (path, line_no, _n, kind, _page, _option), count in sorted(point_hits.items())
                         if kind == "line" and line_no.isdigit())
    detail_names = {"branch": "branches", "expr": "expressions", "toggle": "toggles"}
    for kind, suffix in detail_names.items():
        output = ROOT / f"reports/{prefix}_code_coverage_{suffix}.csv"
        with output.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["scope", "rtl_file", "line", "point", "page", "option", "hit_count", "status"], lineterminator="\n")
            writer.writeheader()
            writer.writerows({"scope": scope_for(path, line_no), "rtl_file": path, "line": line_no,
                              "point": number, "page": page, "option": option,
                              "hit_count": count, "status": "HIT" if count else "UNCOVERED"}
                             for (path, line_no, number, point_type, page, option), count in sorted(point_hits.items())
                             if point_type == kind)
    exclusion_path = ROOT / f"reports/{prefix}_code_coverage_exclusions.csv"
    with exclusion_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rtl_file", "line", "point", "page", "option", "hit_count", "rationale"], lineterminator="\n")
        writer.writeheader(); writer.writerows(reviewed_branch_exclusions)
    with REPORT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scope_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(scope_rows)
    integrated = summary_values["integrated_protected_offload_and_rv32"]
    hit, total, pct = integrated["line"]
    branch_hit, branch_found, bpct = integrated["branch"]
    expr_hit, expr_found, expr_pct = integrated["expr"]
    toggle_hit, toggle_found, toggle_pct = integrated["toggle"]
    pct = pct or 0.0
    controlled = summary_values["new_protected_offload_control_rtl"]
    control_line_hit, control_line_total, control_line_pct = controlled["line"]
    control_branch_hit, control_branch_total, control_branch_pct = controlled["branch"]
    control_row = next(row for row in scope_rows if row["scope"] == "new_protected_offload_control_rtl")
    branch_text = f"{branch_hit}/{branch_found} ({bpct:.2f}%)" if bpct is not None else "NA"
    if args.stateful:
        contribution_rows=[]
        for scope in ("new_protected_offload_control_rtl", "rv32_muldiv", "rv32_core_and_feeder"):
            selected=point_sets.get(scope,{})
            for kind in ("line", "branch"):
                identities=[identity for identity in selected if identity[3]==kind]
                previous=set()
                for group, counts in group_hits.items():
                    covered={identity for identity in identities if counts.get(identity,0)>0}
                    contribution_rows.append(dict(scope=scope,point_type=kind,group=group,
                        hit=len(covered),union_denominator=len(identities),
                        newly_hit_after_prior_groups=len(covered-previous)))
                    previous |= covered
        with (ROOT / "reports/compute_stateful_code_coverage_contributions.csv").open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=contribution_rows[0],lineterminator="\n")
            writer.writeheader();writer.writerows(contribution_rows)
        text = "# Stateful Crossover Native Code Coverage\n\n"
        text += f"Fresh native Verilator 5.049 instrumentation of {expected} supplemental firmware scenarios (directed and seeded). Assertions run separately in the asserted regression; this instrumentation build defines SYNTHESIS. Source-point unions do not imply every structural variant is independently closed. No raw toggle closure is claimed.\n\n"
        text += "| Scope | Raw line hit/total (%) | Raw branch hit/total (%) | Raw toggle (%) |\n|---|---|---|---|\n"
        for row in scope_rows:
            text += f"| {row['scope']} | {row['line_hit']}/{row['line_total']} ({row['line_percent']}) | {row['branch_hit']}/{row['branch_total']} ({row['branch_percent']}) | {row['toggle_percent']} |\n"
        text += f"\nNew-control raw targets: 95% line / 90% branch. Measured gate: **{'PASS' if control_line_pct >= 95 and control_branch_pct >= 90 else 'FAIL'}**. This lane is supplemental, not a replacement for canonical integration coverage; imported-module gaps remain visible. No exclusions are used to turn an unmet raw target into PASS.\n"
        text += "\n[Incremental group contribution](../reports/compute_stateful_code_coverage_contributions.csv) uses the same source-point union denominator. New points are credited in original-directed, targeted-edge, end-to-end, seeded-workload order; this is not independent per-configuration closure.\n"
        text += "\n[Remaining-hole review](../reports/compute_stateful_coverage_hole_review.csv) retains all holes in raw denominators. The three uncovered new-control lines and two muldiv lines are defensive defaults. Remaining integrated branches include topology-constrained waits, a caller-constrained magnitude helper and an illegal-peer response path. [Independent-peer tests](compute_peer_holes.md) exercise module waits and wrong-tag containment separately; they do not inflate this integration percentage.\n"
        (ROOT / "docs/compute_stateful_code_coverage.md").write_text(text)
        print(f"STATEFUL_CODE_COVERAGE|runs={len(rows)}|control_line={control_line_pct:.2f}|control_branch={control_branch_pct:.2f}")
        return int(control_line_pct < 95 or control_branch_pct < 90)
    (ROOT / "docs/compute_crossover_code_coverage.md").write_text(
        "# Compute Crossover Integrated-Top Code Coverage\n\n"
        "Collected from 48 directed compiled-firmware scenarios, 100 seeded firmware/DMA schedules, 100 generated RV32M instruction streams, one APB edge probe, and 8 cache-enabled ownership scenarios on `tb_rv32_protected_shared`, "
        "including the RV32 core, protected DMA/IOMMU/cache-control RTL, and optional chiplet top. "
        "This is native Verilator 5.049 instrumentation, distinct from functional/cross coverage. "
        "The coverage build defines `SYNTHESIS` to exclude assertion-only code; SVA runs in the separate asserted regression.\n\n"
        "Point identity is source-based and unioned across all passing runs, elaborated parameterizations, and instances. "
        "A source point is covered when at least one tested configuration/instance executes it; this is not a claim "
        "that every instance or configuration has independent closure. Integrated, imported, ownership-monitor, and "
        "memory-model scopes remain separately visible.\n\n"
        f"- Raw line coverage: **{hit} / {total} ({pct:.2f}%)**\n"
        f"- Raw branch coverage: **{branch_text}**\n"
        f"- Raw expression coverage: **{expr_hit} / {expr_found} ({expr_pct:.2f}%)**\n"
        f"- Raw toggle coverage: **{toggle_hit} / {toggle_found} ({toggle_pct:.2f}%)**\n"
        f"- New protected-control raw coverage: line **{control_line_hit} / {control_line_total} ({control_line_pct:.2f}%)**, branch **{control_branch_hit} / {control_branch_total} ({control_branch_pct:.2f}%)**\n"
        f"- New-control reviewed branch coverage: **{control_row['reviewed_branch_hit']} / {control_row['reviewed_branch_total']} ({control_row['reviewed_branch_percent']}%)**; exclusions: **{control_row['reviewed_branch_exclusions']}** reviewed unreachable FSM default points\n"
        f"- Verification-only ownership monitor and AXI memory target are reported in separate scopes, not counted as synthesizable control RTL. The aggregate integrated scope above remains raw and includes imported RV32/cache/fabric/chiplet logic.\n"
        f"- Required new-control targets: raw line **95%**, reviewed branch **90%**\n"
        f"- Per-line points: [`compute_crossover_code_coverage_points.csv`](../reports/compute_crossover_code_coverage_points.csv)\n"
        f"- Per-branch points: [`compute_crossover_code_coverage_branches.csv`](../reports/compute_crossover_code_coverage_branches.csv)\n"
        f"- Per-expression points: [`compute_crossover_code_coverage_expressions.csv`](../reports/compute_crossover_code_coverage_expressions.csv)\n"
        f"- Per-toggle points: [`compute_crossover_code_coverage_toggles.csv`](../reports/compute_crossover_code_coverage_toggles.csv)\n"
        f"- Reviewed branch exclusions: [`compute_crossover_code_coverage_exclusions.csv`](../reports/compute_crossover_code_coverage_exclusions.csv)\n"
        f"- Instrumented passing runs: **{len(rows)} / 257** (48 directed + 100 firmware-random + 100 CPU-stream + 1 APB edge + 8 cache-ownership)\n\n"
        "The report counts native Verilator `line`, `branch`, `expr`, and `toggle` point types separately. Raw values are never replaced by reviewed values. Reviewed branch exclusions are limited to unreachable defensive FSM default arms and are listed individually with source/page provenance. The verification monitor, AXI memory model, imported modules, and full integrated raw metric remain separately visible.\n")
    print(f"CROSSOVER_CODE_COVERAGE|integrated_line={hit}/{total}:{pct:.2f}%|integrated_branch={branch_text}|control_line={control_line_hit}/{control_line_total}:{control_line_pct:.2f}%|control_branch_raw={control_branch_hit}/{control_branch_total}:{control_branch_pct:.2f}%|control_branch_reviewed={control_row['reviewed_branch_percent']}% excl={control_row['reviewed_branch_exclusions']}")
    return 0 if control_line_pct is not None and control_line_pct >= 95 and control_branch_pct is not None and control_branch_pct >= 90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
