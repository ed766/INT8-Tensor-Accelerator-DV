"""Embed verified simulator events in the standalone replay."""
import csv
import hashlib
import json

from shared_rtl_sources import ROOT

build = ROOT / "build/protected_offload/mlp_demo"
docs = ROOT / "docs"
manifest = json.loads((build / "evidence.json").read_text())
modes = {"fault_retry", "idle", "equal_qos", "peer_high_qos", "dma_high_qos"}
runs = {}
for entry in manifest:
    name = entry["mode"]
    if name not in modes:
        continue
    raw = (ROOT / entry["trace"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["trace_sha256"]:
        raise SystemExit(f"Trace checksum mismatch for {name}")
    events = []
    for line in raw.decode().splitlines():
        if not line.startswith("CROSS_EVT|"):
            continue
        e = dict(part.split("=", 1) for part in line.split("|")[1:] if "=" in part)
        kind = e.get("kind")
        if kind in {"MAINT_START", "MAINT_DONE", "SUBMIT", "COMPLETE_PUBLISH", "COMPLETE", "FIRMWARE_DONE"} or (
            kind == "MEM_RSP" and e.get("write") == "1"
        ) or (kind == "AXI_AR" and (e.get("addr") == "1000f000" or e.get("master") == "1")):
            e["cycle"] = int(e["cycle"])
            for key in ("run", "schema", "epoch", "build"):
                e.pop(key, None)
            events.append(e)
    runs[name] = {"events": events, "sha": entry["trace_sha256"]}
if set(runs) != modes:
    raise SystemExit("Run make cross-project-demo to generate all replay traces")
with (build / "summary.csv").open() as handle:
    metrics = list(csv.DictReader(handle))
payload = json.dumps({"runs": runs, "metrics": metrics}, separators=(",", ":")).replace("<", "\\u003c")
template = (docs / "trace_replay.template.html").read_text()
(docs / "trace_replay.html").write_text(template.replace("/* TRACE_DATA */", payload))
