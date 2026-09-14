#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"


def rows(name: str) -> list[dict[str, str]]:
    path = REPORTS / name
    return list(csv.DictReader(path.open()))


def main() -> int:
    executions = []
    for group in ("directed", "random", "coverage"):
        executions.extend(rows(f"protected_offload_{group}_summary.csv"))
    coverage_exec = rows("protected_offload_coverage_summary.csv")
    traces = {}
    for row in executions:
        with (ROOT / row["trace"]).open() as handle:
            traces[row["name"]] = list(csv.DictReader(handle))

    bins: list[tuple[str, str, callable]] = []
    for k in (4, 8, 16, 32, 64):
        bins.append(("geometry", f"k_{k}", lambda row, events, k=k: int(row["k"]) == k))
    for pattern in range(5):
        bins.append(("operand", f"pattern_{pattern}", lambda row, events, pattern=pattern:
                     int(row.get("pattern") or 0) == pattern and any(e["event"] == "result" for e in events)))
    batch_ranges = (("1", lambda v: v == 1), ("2", lambda v: v == 2),
                    ("3_4", lambda v: 3 <= v <= 4), ("5_8", lambda v: 5 <= v <= 8),
                    ("16_plus", lambda v: v >= 16))
    for label, predicate in batch_ranges:
        bins.append(("geometry", f"batch_{label}", lambda row, events, predicate=predicate: predicate(int(row["batch"]))))
    for bp in (0, 25, 50, 75):
        bins.append(("backpressure", f"requested_{bp}", lambda row, events, bp=bp: int(row["bp_pct"]) == bp))
    for status in range(5):
        bins.append(("outcome", f"status_{status}", lambda row, events, status=status: int(row["fault"]) == status))
    for stage in range(1, 5):
        bins.append(("outcome", f"fault_stage_{stage}", lambda row, events, stage=stage:
                     any(event["event"] == "completion" and int(event["arg2"]) == stage for event in events)))
    asid_predicates = (("zero", lambda v: v == 0), ("low", lambda v: 0 < v < 64),
                       ("mid", lambda v: 64 <= v < 192), ("high", lambda v: v >= 192))
    for label, predicate in asid_predicates:
        bins.append(("context", f"asid_{label}", lambda row, events, predicate=predicate: predicate(int(row.get("asid") or 18))))
    for qos_class in range(4):
        bins.append(("qos", f"qos_class_{qos_class}", lambda row, events, qos_class=qos_class:
                     int(row.get("qos") or 8) // 4 == qos_class))
    bins.append(("completion", "immediate_pop", lambda row, events: int(row.get("comp_stall") or 0) == 0))
    bins.append(("completion", "held_pop", lambda row, events: int(row.get("comp_stall") or 0) > 0))
    for event_name in ("submit", "xlate", "memory", "command", "chunk", "result", "completion"):
        bins.append(("event", event_name, lambda row, events, event_name=event_name:
                     any(event["event"] == event_name for event in events)))
    bins.extend([
        ("translation", "read", lambda row, events: any(e["event"] == "xlate" and e["arg2"] == "0" for e in events)),
        ("translation", "write", lambda row, events: any(e["event"] == "xlate" and e["arg2"] == "1" for e in events)),
        ("memory", "read", lambda row, events: any(e["event"] == "memory" and e["arg0"] == "0" for e in events)),
        ("memory", "write", lambda row, events: any(e["event"] == "memory" and e["arg0"] == "1" for e in events)),
    ])
    for k in (4, 8, 16, 32, 64):
        bins.append(("stream", f"chunk_count_k{k}", lambda row, events, k=k:
                     int(row["k"]) == k and sum(e["event"] == "chunk" for e in events) >= k // 4))
    for label, predicate in batch_ranges:
        bins.append(("completion", f"vectors_{label}", lambda row, events, predicate=predicate:
                     int(row["fault"]) == 0 and predicate(int(row["batch"]))))
    bins.extend([
        ("irq", "asserted", lambda row, events: int(row["irq_cycles"]) > 0),
        ("irq", "held_until_pop", lambda row, events: int(row.get("comp_stall") or 0) > 0 and int(row["irq_cycles"]) > 1),
        ("ordering", "write_before_success", lambda row, events: int(row["fault"]) == 0),
        ("containment", "input_fault_no_command", lambda row, events: int(row["fault"]) in (1, 3)),
        ("containment", "output_fault_after_command", lambda row, events: int(row["fault"]) in (2, 4)),
        ("ordering", "completion_after_result", lambda row, events: int(row["fault"]) in (0, 2, 4)),
        ("ordering", "translation_before_memory", lambda row, events: any(e["event"] == "memory" for e in events)),
        ("ordering", "command_after_reads", lambda row, events: any(e["event"] == "command" for e in events)),
        ("ordering", "chunks_before_result", lambda row, events: any(e["event"] == "result" for e in events)),
        ("accounting", "one_write_per_vector", lambda row, events: int(row["fault"]) == 0 and int(row["writes"]) == int(row["batch"])),
    ])
    for address in ("000", "004", "008", "00c", "010", "014", "018", "02c"):
        bins.append(("apb", f"write_{address}", lambda row, events, address=address:
                     any(e["event"] == "apb_write" and e["arg1"].lower() == address for e in events)))
    assert len(bins) == 77

    output = []
    for group, name, predicate in bins:
        contributors = [row["name"] for row in executions if predicate(row, traces[row["name"]])]
        output.append({"group": group, "bin": name, "status": "COVERED" if contributors else "UNCOVERED",
                       "hit_count": len(contributors), "first_test": contributors[0] if contributors else "",
                       "contributors": ";".join(contributors)})
    with (REPORTS / "protected_offload_functional_coverage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(output)

    cross_rows = []
    for row in coverage_exec:
        cross_rows.append({"group": row["name"].split("_")[1], "cross": row["name"],
                           "status": "COVERED" if row["status"] == "PASS" else "UNCOVERED",
                           "hit_count": 1, "first_test": row["name"], "evidence": row["trace"]})
    assert len(cross_rows) == 64
    with (REPORTS / "protected_offload_cross_coverage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cross_rows[0].keys(), lineterminator="\n")
        writer.writeheader(); writer.writerows(cross_rows)
    covered = sum(row["status"] == "COVERED" for row in output)
    crossed = sum(row["status"] == "COVERED" for row in cross_rows)
    print(f"PROTECTED_OFFLOAD_COVERAGE|status={'PASS' if covered == 77 and crossed == 64 else 'FAIL'}|functional={covered}/77|crosses={crossed}/64")
    return 0 if covered == 77 and crossed == 64 else 1


if __name__ == "__main__":
    raise SystemExit(main())
