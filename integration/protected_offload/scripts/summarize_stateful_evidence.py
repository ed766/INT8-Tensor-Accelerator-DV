#!/usr/bin/env python3
"""Keep supplemental stateful metrics and hole review tied to measured reports."""
import csv
from pathlib import Path
from run_stateful_crossover import ROOT

csv.field_size_limit(20_000_000)


def read(name):
    with (ROOT/"reports"/name).open(newline="") as handle:return list(csv.DictReader(handle))


def main():
    directed=read("compute_stateful_all_closure.csv")
    seeded=read("compute_stateful_random_closure.csv")
    crosses=read("compute_stateful_cross_coverage.csv")
    mutations=read("compute_stateful_mutations.csv")
    coverage=read("compute_stateful_code_coverage.csv")
    control=next(r for r in coverage if r["scope"]=="new_protected_offload_control_rtl")
    muldiv=next(r for r in coverage if r["scope"]=="rv32_muldiv")
    def result(rows,status):return f"{sum(r['status']==status for r in rows)}/{len(rows)}"
    control_pass=control["line_target_met"]=="true" and control["branch_target_met"]=="true"
    records={
        "C-STATEFUL-EXECUTION":("PASS" if all(r['status']=='PASS' for r in directed) else "FAIL",
            "compute-stateful-check","reports/compute_stateful_all_closure.csv",f"{result(directed,'PASS')} supplemental directed scenarios; independent replay and activating event witnesses"),
        "C-STATEFUL-RANDOM":("PASS" if all(r['status']=='PASS' for r in seeded) else "FAIL",
            "compute-stateful-random","reports/compute_stateful_random_closure.csv",f"{result(seeded,'PASS')} seeded multi-job firmware workloads; varied inputs banks K ASID QoS cache and AXI delays; not exhaustive random closure"),
        "C-STATEFUL-CROSSES":("PASS" if all(r['status']=='HIT' for r in crosses) else "FAIL",
            "compute-stateful-crosses","reports/compute_stateful_cross_coverage.csv",f"{result(crosses,'HIT')} same-event or correlated-window bins; separate from canonical crossover coverage"),
        "C-STATEFUL-MUTATIONS":("PASS" if all(r['status']=='DETECTED' for r in mutations) else "FAIL",
            "compute-stateful-mutations","reports/compute_stateful_mutations.csv",f"{result(mutations,'DETECTED')} compiled RTL mutations detected with passing controls and intended diagnostics; checker self-tests are separate"),
        "C-STATEFUL-NATIVE-COVERAGE":("PASS" if control_pass else "PARTIAL",
            "compute-stateful-code-coverage","reports/compute_stateful_code_coverage.csv",f"{control['passing_runs']} native instrumented runs; raw control line {control['line_hit']}/{control['line_total']} ({control['line_percent']} percent); branch {control['branch_hit']}/{control['branch_total']} ({control['branch_percent']} percent); raw imported-module gaps remain visible")}
    if (ROOT/"reports/compute_end_to_end_closure.csv").is_file():
        end_to_end=read("compute_end_to_end_closure.csv")
        records["C-END-TO-END-CLOSURE"]=("PASS" if len(end_to_end)==8 and all(r['status']=='PASS' for r in end_to_end) else "FAIL",
            "compute-end-to-end-check","reports/compute_end_to_end_closure.csv",f"{result(end_to_end,'PASS')} qualified full firmware integration cases; metadata reads and multi-owner reset; finite schedules, not exhaustive permutations")
    if (ROOT/"reports/compute_end_to_end_mutations.csv").is_file():
        end_mutations=read("compute_end_to_end_mutations.csv")
        records["C-END-TO-END-MUTATIONS"]=("PASS" if len(end_mutations)==1 and all(r['status']=='DETECTED' for r in end_mutations) else "FAIL",
            "compute-end-to-end-mutations","reports/compute_end_to_end_mutations.csv",f"{result(end_mutations,'DETECTED')} actual CPU-visible completion metadata mutation; passing control and designated independent read-check diagnostic")
    for identifier,file,target,success,note in (
        ("C-GAP-CROSSES","compute_gap_cross_coverage.csv","compute-gap-crosses","HIT","event-correlated bins; high-risk bins require two independently constructed templates"),
        ("C-GAP-MUTATIONS","compute_gap_mutations.csv","compute-gap-mutations","DETECTED","reference lifetime; stale permission context; dirty eviction data loss; exact activation and diagnostic"),
        ("C-GAP-ALIASES","compute_ownership_alias_check.csv","compute-gap-alias-check","PASS","physical-alias and handler expected-negative/control pairs; not drained positive executions")):
        if (ROOT/"reports"/file).is_file():
            rows=read(file)
            passed=all(r['status']==success and r.get('robustness','PASS')=='PASS' for r in rows)
            records[identifier]=("PASS" if passed else "FAIL",target,"reports/"+file,f"{result(rows,success)} {note}")
    peer=[];peer_closed=0
    if (ROOT/"reports/compute_peer_holes.csv").is_file():
        peer=read("compute_peer_holes.csv")
        peer_closed=sum(r['status']=='COMPONENT_COVERED' for r in read("compute_peer_hole_closure.csv"))
        records["C-PEER-HOLE-CHECKS"]=("PASS" if len(peer)==14 and all(r['status']=='PASS' for r in peer) else "FAIL",
            "compute-peer-holes","reports/compute_peer_holes.csv",f"{result(peer,'PASS')} asserted/native independent-peer executions; {peer_closed} prior holes exercised at module level; not unioned into firmware integration coverage")
    ledger=ROOT/"integration/protected_offload/implementation_ledger.csv"
    with ledger.open(newline="") as handle:
        reader=csv.DictReader(handle);fields=reader.fieldnames;entries=list(reader)
    # Update only this supplemental lane, preserving unrelated requirements.
    for requirement,(status,target,report,note) in records.items():
        row=next((r for r in entries if r[fields[0]]==requirement),None)
        if row is None:
            row=dict.fromkeys(fields,"");row[fields[0]]=requirement;entries.append(row)
        row.update(dict(zip(fields[1:],("Supplemental stateful crossover",status,target,report,note))))
    with ledger.open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n");writer.writeheader();writer.writerows(entries)
    peer_lookup={(r['rtl_file'],r['line'],r['point_type'],r['option']):r for r in read("compute_peer_hole_closure.csv")} if peer else {}
    review=[]
    for point_type,file in (("line","points"),("branch","branches")):
        for row in read(f"compute_stateful_code_coverage_{file}.csv"):
            if row['status']!='UNCOVERED' or not (row['scope']=='new_protected_offload_control_rtl' or row['rtl_file'].endswith('/rv32_muldiv.sv')):continue
            path=ROOT/row['rtl_file'];source=path.read_text().splitlines()[int(row['line'])-1].strip()
            if "default:" in source:
                category="defensive_default"
                reason="Legal state/opcode transitions do not reach this default. Remains in raw denominator; no forced invalid-state stimulus."
            elif path.name=='rv32_muldiv.sv' and 'value[31]' in source:
                category="caller_constrained_branch"
                reason="magnitude is called only for negative signed operands; its nonnegative alternative is not reached by legal callers. Retained raw."
            elif path.name=='rv32_protected_shared_top.sv':
                category="executable_and_worth_testing"
                reason="Ignored/reserved mailbox-address alternative remains untested; define its contract before adding a directed test."
            elif path.name=='protected_offload_dma.sv' and 'accel_out_tag !=' in source:
                category="illegal_peer_sensitivity"
                reason="Wrong accelerator tag requires faulty peer/mutation stimulus, not legal successful traffic. Not counted as nominal error recovery closure."
            else:
                category="wait_or_topology_gap_review"
                reason="Not observed in this integrated topology. Review ready/valid reachability or add an independently stallable peer; not excluded or claimed closed."
            component=peer_lookup.get((row['rtl_file'],row['line'],point_type,row.get('option','')))
            if component and component['status']=='COMPONENT_COVERED':
                category="covered_in_independent_peer_only"
                reason="Executed by "+component['contributing_tests']+" using public interfaces and independent peers. Remains uncovered in firmware integration and in its raw denominator; see compute_peer_hole_closure.csv."
            review.append(dict(point_type=point_type,rtl_file=row['rtl_file'],line=row['line'],option=row.get('option',''),
                               category=category,exclusion_applied="false",rationale=reason,source=source))
    with (ROOT/"reports/compute_stateful_coverage_hole_review.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=review[0],lineterminator="\n");writer.writeheader();writer.writerows(review)
    block=("<!-- STATEFUL METRICS START -->\n"
           f"Supplemental stateful evidence: **{result(directed,'PASS')} directed**, **{result(seeded,'PASS')} seeded multi-job workloads**, "
           f"**{result(crosses,'HIT')} event-correlated crosses**, and **{result(mutations,'DETECTED')} qualified RTL mutations**. "
           f"Fresh new-control raw coverage: **{control['line_hit']}/{control['line_total']} ({control['line_percent']}%) line**, "
           f"**{control['branch_hit']}/{control['branch_total']} ({control['branch_percent']}%) branch**. "
           f"Muldiv remains separately reported: **{muldiv['line_percent']}% line / {muldiv['branch_percent']}% branch**. "
           "Canonical denominators are unchanged. [Closure](docs/compute_stateful_closure.md), "
           "[advanced ownership/reset closure](docs/compute_gap_closure.md), "
           "[cross witnesses](docs/compute_stateful_cross_coverage.md), [code coverage](docs/compute_stateful_code_coverage.md), "
           "and [remaining-hole review](reports/compute_stateful_coverage_hole_review.csv).\n"
           "<!-- STATEFUL METRICS END -->")
    if peer:
        block=block.replace("<!-- STATEFUL METRICS END -->",f"\nIndependent-peer component evidence: **{result(peer,'PASS')} asserted/instrumented executions**, covering **{peer_closed}** previously missed wait/containment branches separately from integration coverage. [Tests and boundaries](docs/compute_peer_holes.md).\n<!-- STATEFUL METRICS END -->")
    if (ROOT/"reports/compute_gap_cross_coverage.csv").is_file():
        advanced=read("compute_gap_cross_coverage.csv");gap_mutations=read("compute_gap_mutations.csv");aliases=read("compute_ownership_alias_check.csv")
        block=block.replace("<!-- STATEFUL METRICS END -->",
            f"\nAdvanced closure: **{result(advanced,'HIT')} correlated bins**, **{result(gap_mutations,'DETECTED')} targeted RTL mutations**, and **{result(aliases,'PASS')} ownership alias/handler negative-control pairs**. [Witnesses and boundaries](docs/compute_gap_closure.md).\n<!-- STATEFUL METRICS END -->")
    readme=ROOT/"README.md";text=readme.read_text();start="<!-- STATEFUL METRICS START -->";end="<!-- STATEFUL METRICS END -->"
    if start in text:
        a=text.index(start);b=text.index(end,a)+len(end);text=text[:a]+block+text[b:]
    else:
        anchor="The optional [stateful closure lane]"
        a=text.index(anchor);b=text.index("\n",a);text=text[:a]+block+text[b:]
    readme.write_text(text)
    print(f"Stateful evidence summary: directed={result(directed,'PASS')} random={result(seeded,'PASS')} crosses={result(crosses,'HIT')} mutations={result(mutations,'DETECTED')}")
    return int(not control_pass or any(r['status']!='PASS' for r in directed+seeded) or any(r['status']!='HIT' for r in crosses) or any(r['status']!='DETECTED' for r in mutations))

if __name__=="__main__":raise SystemExit(main())
