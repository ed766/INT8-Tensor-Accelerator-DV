#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports"
CPP_SOURCE = ROOT / "integration/protected_offload/model/protected_trace_checker.cpp"
CPP_BINARY = ROOT / "build/protected_offload/protected_trace_checker"


def load_summary(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open())) if path.exists() else []


def check_row(row: dict[str, str]) -> tuple[int, str]:
    events = list(csv.DictReader((ROOT / row["trace"]).open()))
    kinds = [event["event"] for event in events]
    k = int(row["k"])
    batch = int(row["batch"])
    fault = int(row["fault"])
    pattern = int(row.get("pattern") or 0)
    expected_chunks = k // 4
    failures: list[str] = []
    checks = 0

    def require(condition: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(label)

    require(kinds.count("submit") == 1, "submit_count")
    require(kinds.count("completion") == 1, "completion_count")
    require(kinds.index("submit") < kinds.index("completion"), "completion_after_submit")
    require(kinds.count("apb_write") == 8, "apb_write_count")
    completion = next(event for event in events if event["event"] == "completion")
    require(int(completion["tag"]) == 0x35, "completion_tag")
    require(int(completion["arg0"]) == (fault + 1 if fault else 0), "completion_status")

    command_count = kinds.count("command")
    chunk_count = kinds.count("chunk")
    result_events = [event for event in events if event["event"] == "result"]
    write_count = sum(event["event"] == "memory" and event["arg0"] == "1" for event in events)
    read_count = sum(event["event"] == "memory" and event["arg0"] == "0" for event in events)
    if fault == 0:
        require(command_count == batch, "command_per_vector")
        require(chunk_count == batch * expected_chunks, "chunk_count")
        require(len(result_events) == batch, "result_count")
        require(read_count == batch * expected_chunks, "read_count")
        require(write_count == batch, "write_count")
        expected_byte = {0:k, 1:0, 2:min(127,10*(k//4)), 3:(-k)&0xff, 4:127}[pattern]
        expected_word = sum(expected_byte << (8 * lane) for lane in range(4))
        require(all(int(event["arg1"], 16) == expected_word for event in result_events),
                "numerical_result")
        require(int(completion["arg1"]) == batch, "vectors_done")
        last_write = max(index for index, event in enumerate(events)
                         if event["event"] == "memory" and event["arg0"] == "1")
        require(last_write < kinds.index("completion"), "completion_after_output_write")
    elif fault in (1, 3):
        require(command_count == 0, "no_command_after_input_fault")
        require(write_count == 0, "no_output_write_after_input_fault")
        require(int(completion["arg1"]) == 0, "zero_vectors_done")
    else:
        require(command_count == 1, "command_before_output_fault")
        require(chunk_count == expected_chunks, "chunks_before_output_fault")
        require(len(result_events) == 1, "result_before_output_fault")
        require(int(completion["arg1"]) == 0, "failed_vector_not_committed")
    return checks, ";".join(failures)


def main() -> int:
    CPP_BINARY.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                    str(CPP_SOURCE), "-o", str(CPP_BINARY)], check=True)
    rows = []
    total_checks = 0
    for group in ("smoke", "directed", "random", "coverage"):
        for source in load_summary(REPORTS / f"protected_offload_{group}_summary.csv"):
            checks, failure = check_row(source)
            cpp = subprocess.run([str(CPP_BINARY), str(ROOT / source["trace"]), source["k"],
                                  source["batch"], source["fault"], source.get("pattern") or "0"], text=True, capture_output=True)
            match = re.search(r"checks=(\d+)\|first_mismatch=([^\n]+)", cpp.stdout)
            cpp_checks = int(match.group(1)) if match else 0
            cpp_failure = "" if cpp.returncode == 0 else (match.group(2) if match else "cpp_checker_failure")
            checks += cpp_checks
            failure = failure or cpp_failure
            total_checks += checks
            rows.append({"test": source["name"], "group": group, "checker": "python_orchestrator+cpp_model", "checks": checks,
                         "status": "PASS" if not failure else "FAIL", "first_mismatch": failure})
    path = REPORTS / "protected_offload_model_summary.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    passed = sum(row["status"] == "PASS" for row in rows)
    print(f"PROTECTED_OFFLOAD_MODEL|status={'PASS' if passed == len(rows) else 'FAIL'}|traces={passed}/{len(rows)}|checks={total_checks}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
