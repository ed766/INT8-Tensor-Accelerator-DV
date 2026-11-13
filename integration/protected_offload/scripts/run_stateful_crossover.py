#!/usr/bin/env python3
"""Supplemental stateful closure with trace witnesses and independent replay."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from check_crossover_trace import check, events
from check_compute_host_evidence import check_host_trace
from stateful_cases import cases,random_cases
from end_to_end_checks import completion_reads,reference_writes,physical_ownership
from reset_evidence import phase_reached

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "integration/protected_offload/spec/stateful_coverage.json"


def number(event, key, base=10):
    return int(event.get(key, "0"), base)


def qualify(parsed, code, name):
    selected = []
    errors = []

    def require(label, matches, minimum=1):
        matches = list(matches)
        if len(matches) < minimum:
            errors.append(label + ": stimulus not reached")
        selected.extend(matches)

    def kind(label):
        return [e for e in parsed if e["kind"] == label]

    retires = kind("RETIRE")
    submits = kind("SUBMIT")
    completions = kind("COMPLETE")
    errors.extend(reference_writes(parsed)[1])
    errors.extend(physical_ownership(parsed)[1])
    if code==98:
        record=[e for e in completions if e.get("tag")=="253"]
        if [(e["status"],e["vectors_done"]) for e in record]!=[("5","0"),("0","3"),("5","1"),("0","3"),("5","2"),("0","3")]:errors.append("independent first/middle/last prefix recovery not reached")
        selected.extend(record)
    if code==99:
        record=[e for e in completions if e.get("tag")=="251"]
        if [(e["status"],e["vectors_done"]) for e in record]!=[("2","0"),("0","2"),("4","0"),("0","2"),("3","0"),("0","2")]:errors.append("independent input/output permission/bus recovery not reached")
        selected.extend(record)
    if code==95:
        require("independent write hit permission denial",(e for e in kind("XLATE_RSP") if e.get("tag")=="249" and e.get("write")=="1" and e.get("tlb_hit")=="1" and e.get("fault")=="2"))
        require("independent context recovery",(e for e in completions if e.get("tag")=="249" and e.get("status")=="0"))
    if code==96:
        require("alias resolves owned page",(e for e in kind("XLATE_RSP") if e.get("tag")=="250" and e.get("paddr")=="10006000"))
        require("unowned line within same physical page allowed",(e for e in kind("APB") if e.get("addr")=="10006040" and e.get("rdata")=="01010101"))
    if code==93:
        require("dirty final-set eviction",kind("CACHE_EVICT"))
        require("both aliases resolve one physical line",(e for e in kind("XLATE_RSP") if e.get("iova") in ("800067e0","800087e0") and e.get("paddr")=="100007e0" and e.get("fault")=="0"),2)
        require("drained alias completions",completions,3)
    if code==94:
        require("retirement stalled by full completion FIFO",(e for e in kind("MDIV_BUSY") if e.get("comp_occ")=="4" and e.get("busy")=="1"))
        require("referenced generation change rejected",(e for e in kind("APB") if e.get("addr")=="40001010" and e.get("write")=="1" and e.get("error")=="1"))
        require("all jobs eventually consumed",completions,6)
    if code==92:
        by_cycle={}
        for e in kind("FABRIC_AR_OFFER"):
            if number(e,"addr",16)>>16==0x1000:by_cycle.setdefault((e["epoch"],e["cycle"]),[]).append(e)
        overlap=[e for group in by_cycle.values() if {e["master"] for e in group}>={"1","3"} for e in group]
        require("same-target independent-master contention",overlap)
        for master in ("1","3"):
            require("contended master progress "+master,(e for e in kind("FABRIC_AR_OFFER") if e.get("master")==master and e.get("accepted")=="1"),4)
        require("chiplet sleep/wake",kind("CHIPLET_POWER"),2)
        require("verified DMA completion",completions,5)
        require("actual starvation override",(e for e in kind("FABRIC_AGE_GRANT") if e.get("master")=="1"))
        require("full completion pressure during arithmetic",(e for e in kind("MDIV_BUSY") if e.get("comp_occ")=="4" and e.get("busy")=="1"))
    if code >= 81:
        records, record_errors = completion_reads(parsed)
        errors.extend(record_errors)
        if not records: errors.append("CPU-visible completion reads not reached")
        selected.extend(e for window in records for e in window)
    if code==91:
        phase=name.removeprefix("stateful_epoch_")
        if not phase_reached(parsed,phase):errors.append("reset boundary not reached: "+phase)
        require("reboot successful completion",(e for e in completions if number(e,"epoch")>0 and e.get("status")=="0"))
        if not submits or not any(number(e,"epoch")>0 for e in submits) or len({(e["tag"],e["input_iova"],e["output_iova"]) for e in submits})!=1:
            errors.append("reset reboot identity reuse not reached")
    elif code in (1, 2, 3):
        for cause in (0x80000007, 0x8000000B):
            require("timer/device handler entry", (e for e in retires if number(e, "mcause", 16) == cause and e.get("intr") == "1"))
        require("MRET", (e for e in retires if e.get("insn") == "30200073"), 2)
        require("device acknowledgement", kind("IRQ_ACK"))
        if code in (1,3):
            require("enabled device IRQ pending at M retirement", (e for e in retires
                if int(e.get("insn","0"),16)&0xfe00007f==0x02000033
                and e.get("trap")=="0" and e.get("irq_level")=="1"
                and number(e,"mstatus",16)&8))
        if code == 1:
            require("precise synchronous fault", (e for e in retires if e.get("trap") == "1" and number(e, "mcause", 16) == 5))
            require("timer during M", (e for e in kind("IRQ_SOURCE_EDGE") if e.get("timer") == "1" and e.get("muldiv_busy") == "1"))
        elif code == 2:
            require("both pending while masked", (e for e in retires if e.get("irq_level") == "1" and e.get("irq_timer_level") == "1" and not number(e, "mstatus", 16) & 8))
        else:
            require("WFI", (e for e in retires if e.get("insn") == "10500073"))
    elif code == 10:
        phase = name.rsplit("_", 1)[-1]
        snapshots = kind("RESET_ASSERT")
        require("reset with arithmetic and DMA owners", (e for e in snapshots if e.get("muldiv_busy") == "1" and e.get("dma_busy") == "1"))
        def at_phase(e):
            state, iteration = number(e, "muldiv_state"), number(e, "muldiv_iteration")
            return ((state == 1 and 1 <= iteration <= 4) if phase == "early" else
                    (state == 1 and 14 <= iteration <= 18) if phase == "middle" else
                    state == 2 if phase == "finalize" else e.get("muldiv_result_valid") == "1")
        require("exact reset arithmetic phase", (e for e in snapshots if at_phase(e)))
        identities = {(e["tag"], e["input_iova"], e["output_iova"]) for e in submits}
        if len(submits) != 2 or len(identities) != 1 or len({e["epoch"] for e in submits}) != 2:
            errors.append("reboot must reuse the same tag/addresses in a new epoch")
        require("post-reset successful completion", (e for e in completions if number(e, "epoch") > 0 and e.get("status") == "0"))
    elif code == 20:
        require("long-lived descriptor wrap", submits, 261)
        require("completion consumption", completions, 261)
        if len({e["tag"] for e in submits}) >= len(submits):
            errors.append("software tag reuse not reached")
        require("both configuration banks", (e for e in submits if e.get("bank") == "1"), 100)
        require("generation rollover", (e for e in submits if e.get("generation") == "0"))
    elif code == 21:
        require("queued bank references", (e for e in kind("OWNERSHIP") if number(e, "count") >= 2))
        require("both bank work", (e for e in submits if e.get("bank") == "1"), 6)
        require("referenced-write rejection", (e for e in kind("APB") if e.get("error") == "1"), 3)
        require("drained completions", completions, 13)
    elif code == 30:
        requests = [e for e in kind("XLATE_REQ") if number(e, "iova", 16) >= 0x80010000 and number(e, "write") == 0]
        if len({number(e, "iova", 16) >> 12 for e in requests}) != 12:
            errors.append("twelve distinct IOVA pages not reached")
        require("replacement misses", (e for e in kind("XLATE_RSP") if number(e, "iova", 16) >= 0x80010000 and e.get("tlb_hit") == "0"), 24)
    elif code == 31:
        require("hit-path permission denial", (e for e in kind("XLATE_RSP") if e.get("tlb_hit") == "1" and e.get("fault") == "2"), 2)
        require("invalidation", kind("TLB_INVALIDATE"), 2)
        require("post-repair write", (e for e in kind("XLATE_RSP") if e.get("iova") == "80009000" and e.get("write") == "1" and e.get("fault") == "0"))
    elif code == 32:
        retry = [e for e in completions if e.get("tag") == "254"]
        if [(e["status"], e["vectors_done"]) for e in retry] != [("5", "0"), ("5", "1"), ("0", "3")]:
            errors.append("same-tag second failure and committed-prefix recovery not reached")
        selected.extend(retry)
        require("repair invalidations", kind("TLB_INVALIDATE"), 3)
    elif code in (40, 41):
        active = False
        loads = []
        arithmetic = []
        chains = []
        for e in parsed:
            if e["kind"] == "DMA_ACTIVE_START": active = True
            if e["kind"] == "DMA_ACTIVE_END": active = False
            if e["kind"] != "RETIRE" or not active or e.get("trap") != "0": continue
            if e.get("mem_addr") == "1000c000" and e.get("mem_rmask") == "f": loads.append(e)
            insn = number(e, "insn", 16)
            if insn & 0xFE00007F == 0x02000033 and loads and (e["rs1_addr"] == loads[-1]["rd_addr"] or e["rs2_addr"] == loads[-1]["rd_addr"]): arithmetic.append(e)
            if e.get("mem_addr") == "1000c004" and e.get("mem_wmask") == "f" and arithmetic and e["rs2_addr"] == arithmetic[-1]["rd_addr"]: chains.extend([loads[-1], arithmetic[-1], e])
        require("live load-M-store dependency", chains, 3)
        require("maintenance completion", kind("MAINT_DONE"), 3)
        if code == 41:
            require("maintenance failed then recovered", (e for e in kind("MAINT_DONE") if e.get("error") == "1"))
    elif code == 50:
        require("DIV while completion FIFO full", (e for e in kind("MDIV_BUSY") if e.get("dma_busy") == "1" and e.get("comp_occ") == "4" and e.get("busy") == "1"))
        require("pressure drains", completions, 6)
        if not name.endswith("_0"):
            require("actual AXI waits", kind("AXI_WAIT"))
        # Simultaneous fabric candidates are reported separately, not inferred
        # from traffic to different targets or a scenario label.
        selected.extend(kind("FABRIC_CANDIDATES"))
    elif code in (51,88):
        sleep = False
        overlap = []
        for e in parsed:
            if e["kind"] == "CHIPLET_POWER": sleep = e.get("state") == "2"
            if sleep and e["kind"] == "MDIV_BUSY" and e.get("dma_busy") == "1": overlap.append(e)
        require("M-DMA while chiplet sleeps", overlap)
        require("wake", (e for e in kind("CHIPLET_POWER") if e.get("state") == "0"))
        require("varied AES input", (e for e in kind("CHIPLET_IN") if e.get("data") in
                {"8000000100000000", "80000001ffffffff", "7ffffffeffffffff", "7ffffffe00000000"}), 4)
        if code==88:require("transport waits during sleep workload",kind("AXI_WAIT"),10)
    elif 60 <= code <= 63:
        require("reconfigured numerical result", (e for e in kind("ACCEL_OUT") if e.get("tag") == "170"))
        cfg = kind("ACCEL_CFG")
        require("numerical job timer entry", (e for e in retires if e.get("intr") == "1" and e.get("mcause") == "80000007"))
        require("timer pending during arithmetic", (e for e in kind("IRQ_SOURCE_EDGE") if e.get("timer") == "1" and e.get("muldiv_busy") == "1"))
        if code == 60: require("nonzero rounding shift", (e for e in cfg if e.get("cfg_kind") == "2" and number(e, "data", 16) >> 16))
        if code == 61: require("saturated signed lanes", (e for e in kind("ACCEL_OUT") if e.get("tag") == "170" and
                             any(((number(e, "data", 16) >> (lane * 8)) & 255) in (127, 128) for lane in range(4))))
        if code == 62: require("zero points/ReLU", (e for e in cfg if e.get("cfg_kind") == "3" and number(e, "data", 16)))
        if code == 63: require("boundary bias", (e for e in cfg if e.get("cfg_kind") == "1" and number(e, "data", 16) in (0x7FFFFFFF, 0x80000000)))
    elif code == 70:
        require("config and DMA decode errors", (e for e in kind("APB") if e.get("error")=="1" and e.get("addr") in ("40001018","40000034")),2)
        require("precise access traps", (e for e in retires if e.get("trap")=="1" and e.get("mcause")=="00000005"),2)
        require("pending status read", (e for e in kind("APB") if e.get("addr")=="40002004" and e.get("write")=="0"))
        require("W1C zero read", (e for e in kind("APB") if e.get("addr")=="4000200c" and e.get("write")=="0"))
    elif code in (71,72):
        require("input fault completion", (e for e in completions if e.get("tag")=="171" and e.get("status")==str(2 if code==71 else 4) and e.get("vectors_done")=="0"))
        require("same-tag repaired completion", (e for e in completions if e.get("tag")=="171" and e.get("status")=="0"))
        if code==71:require("input permission denial", (e for e in kind("XLATE_RSP") if e.get("write")=="0" and e.get("fault")=="2"))
        else:require("input AXI error", (e for e in kind("MEM_RSP") if e.get("write")=="0" and e.get("error")=="1"))
    elif code in (73,74):
        require("submit rejection",kind("SUBMIT_REJECT"))
        require("clear preserves and clears", (e for e in kind("APB") if e.get("addr")=="40000030" and e.get("write")=="1"))
        require("subsequent drain",completions,6 if code==74 else 2)
        if code==74:require("full queue", (e for e in kind("SUBMIT_REJECT") if e.get("occupancy")=="4"))
    elif code==75:
        require("six-cycle completion-pop waits", (e for e in kind("APB") if e.get("addr")=="4000002c" and number(e,"wait_cycles")==6),3)
    elif code==76:
        last=[e for e in completions if e.get("tag")=="253"]
        if [(e["status"],e["vectors_done"]) for e in last] != [("5","2"),("0","3")]:errors.append("last-vector prefix and retry not reached")
        selected.extend(last)
    elif code == 77:
        for address in ("40001fe8","40001ff8"):
            require("reserved mailbox write "+address, (e for e in kind("APB") if e.get("write")=="1" and e.get("addr")==address and e.get("error")=="0"))
        require("post-reserved-write completion", (e for e in completions if e.get("tag")=="172" and e.get("status")=="0"))
    elif code == 86:
        queued=[e for e in submits if e.get("tag") in ("224","225","226","227")]
        request=next((e for e in kind("APB") if e.get("addr")=="40002200" and e.get("write")=="1" and number(e,"wdata",16)==257),None)
        require("targeted invalidation request",[request] if request else [])
        require("both bank queued work",(e for e in queued if e.get("bank")=="1"),2)
        require("pending invalidate status",(e for e in kind("APB") if e.get("addr")=="40002204" and e.get("write")=="0" and number(e,"rdata",16)&1))
        consumed=[e for e in completions if e.get("tag") in ("224","225","226","227")]
        targeted=[e for e in kind("TLB_INVALIDATE") if e.get("all")=="0" and e.get("asid")=="1"]
        require("targeted drain acknowledgement",targeted)
        if request and targeted and (len([e for e in consumed if number(e,"cycle")<number(targeted[0],"cycle")])!=4 or number(targeted[0],"cycle")<=number(request,"cycle")):
            errors.append("invalidation acknowledged before four old jobs consumed")
        require("remapped post-ack input",(e for e in kind("XLATE_RSP") if e.get("iova")=="80006000" and e.get("paddr")=="10007000" and e.get("fault")=="0"))
    elif code == 89:
        require("stale mapping remains effective",(e for e in kind("XLATE_RSP") if e.get("tag")=="237" and e.get("iova")=="80006000" and e.get("paddr")=="10006000" and e.get("tlb_hit")=="1"))
        require("new PTE mapping",(e for e in kind("APB") if e.get("addr")=="30001018" and e.get("write")=="1" and e.get("wdata")=="04001ccf"))
        require("unowned physical page accessible",(e for e in kind("APB") if e.get("addr")=="10007000" and e.get("write")=="0" and e.get("rdata")=="02020202"))
        require("stale input numerical result",(e for e in kind("APB") if e.get("addr")=="10009020" and e.get("rdata")=="04040404"))
    elif code == 87:
        jobs=[e for e in completions if e.get("tag")=="235"]
        if [(e["status"],e["vectors_done"]) for e in jobs]!=[("0","1"),("0","1"),("2","0"),("0","1")]:errors.append("permission downgrade/recovery sequence not reached")
        selected.extend(jobs)
        require("stale readable hit before invalidate",(e for e in kind("XLATE_RSP") if e.get("tag")=="235" and e.get("write")=="0" and e.get("tlb_hit")=="1" and e.get("fault")=="0"))
        require("read denied after invalidation",(e for e in kind("XLATE_RSP") if e.get("tag")=="235" and e.get("write")=="0" and e.get("fault")=="2"))
        require("three invalidations",kind("TLB_INVALIDATE"),3)
    elif code == 85:
        if not phase_reached(parsed,"multiple_owners"):errors.append("reset did not reach M/DMA/payload/completion/IRQ ownership")
        require("simultaneous owner reset",kind("RESET_ASSERT"))
        for tag in ("240","241"):
            matched=[e for e in submits if e.get("tag")==tag]
            if len(matched)!=2 or len({e["epoch"] for e in matched})!=2 or len({(e["input_iova"],e["output_iova"]) for e in matched})!=1:
                errors.append("reboot did not reuse identity "+tag)
            require("post-reset successful consumption "+tag,(e for e in completions if e.get("tag")==tag and number(e,"epoch")>0 and e.get("status")=="0"))
    elif code == 81:
        campaign = [e for e in submits if e.get("tag") != "53" or number(e,"seq") > 0]
        require("384 campaign descriptors plus baseline", submits,385)
        require("all campaign completions",completions,385)
        require("full FIFO arithmetic overlap",(e for e in kind("MDIV_BUSY") if e.get("comp_occ")=="4" and e.get("busy")=="1"),96)
        full_windows=[];start=None;consumed=False
        for e in parsed:
            if e["kind"]=="MDIV_BUSY" and e.get("busy")=="1":start=e;consumed=False
            if start and e["kind"]=="COMPLETE":consumed=True
            if start and e["kind"]=="MDIV_BUSY" and e.get("busy")=="0":
                if start.get("comp_occ")=="4" and e.get("comp_occ")=="4" and not consumed:full_windows.extend([start,e])
                start=None
        require("FIFO remains full throughout arithmetic",full_windows,192)
        if len({e.get("tag") for e in campaign}) != 256: errors.append("all 256 tags and reuse not reached")
        require("both banks referenced",(e for e in kind("OWNERSHIP") if number(e,"count")>=2),96)
        generations=[number(e,"generation") for e in campaign]
        if not any(b<a for a,b in zip(generations,generations[1:])): errors.append("generation wrap not reached")
        for address in ("40000020","40000024","40000028"):
            require("repeated front-record reads "+address,(e for e in kind("APB") if e.get("addr")==address and e.get("write")=="0"),1536)
    elif code == 82:
        retry=[e for e in completions if e.get("tag")=="252"]
        if [(e["status"],e["vectors_done"]) for e in retry] != [("2","0"),("5","1"),("4","0"),("0","3")]:
            errors.append("cross-stage same-tag retry sequence not reached")
        selected.extend(retry)
        require("four drain/repair invalidations",kind("TLB_INVALIDATE"),4)
    elif code == 83:
        in_handler=False;active=False;handler=[]
        for e in parsed:
            if e["kind"]=="DMA_ACTIVE_START": active=True
            if e["kind"]=="DMA_ACTIVE_END": active=False
            if e["kind"]!="RETIRE":continue
            if e.get("intr")=="1" and e.get("mcause")=="80000007":in_handler=True
            if in_handler and active and (e.get("mem_addr") in ("1000c000","1000c004") or number(e,"insn",16)&0xfe00007f==0x02000033):handler.append(e)
            if e.get("insn")=="30200073":in_handler=False
        require("handler load/M/store while DMA active",handler,3)
        require("handler unrelated read",(e for e in handler if e.get("mem_addr")=="1000c000" and e.get("mem_rmask")=="f"))
        require("handler unrelated write",(e for e in handler if e.get("mem_addr")=="1000c004" and e.get("mem_wmask")=="f"))
        require("handler M retirement",(e for e in handler if number(e,"insn",16)&0xfe00007f==0x02000033))
    elif code == 84:
        faults=[e for e in retires if e.get("trap")=="1" and e.get("mcause")=="00000005" and e.get("irq_level")=="1" and e.get("irq_timer_level")=="1"]
        require("precise fault with both interrupts pending",faults)
        for fault in faults:
            index=retires.index(fault)
            if index==0 or number(retires[index-1],"insn",16)&0xfe00007f!=0x02000033:errors.append("fault not immediately after M retirement")
        for cause in ("80000007","8000000b"):
            require("pending interrupt preserved "+cause,(e for e in retires if e.get("intr")=="1" and e.get("mcause")==cause))
        require("fault and both handlers return",(e for e in retires if e.get("insn")=="30200073"),3)
    elif code in (78,80):
        arithmetic=[e for e in retires if e.get("trap")=="0" and number(e,"insn",16)&0xfe00007f==0x02000033]
        if {number(e,"insn",16)>>12&7 for e in arithmetic} != set(range(8)):errors.append("all eight M opcodes not reached")
        require("divide by zero", (e for e in arithmetic if number(e,"insn",16)>>12&7 in (4,5) and number(e,"rs2_data",16)==0))
        require("signed overflow", (e for e in arithmetic if number(e,"insn",16)>>12&7==4 and e.get("rs1_data")=="80000000" and e.get("rs2_data")=="ffffffff"))
        if code==80:
            require("eight seeded jobs and baseline",submits,9)
            require("both parameter banks",(e for e in submits if e.get("bank")=="1"),4)
            require("four timer handler entries",(e for e in retires if e.get("intr")=="1" and e.get("mcause")=="80000007"),4)
            require("randomized outputs",kind("ACCEL_OUT"),9)
        else:
            active=False;live=[]
            for e in parsed:
                if e["kind"]=="DMA_ACTIVE_START":active=True
                if e["kind"]=="DMA_ACTIVE_END":active=False
                if active and e in arithmetic:live.append(e)
            require("live M/DMA overlap",live)
    return list({e["eid"]: e for e in selected}.values()), errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-only", action="store_true")
    parser.add_argument("--family", default="all")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    if manifest["schema"] != 1 or set(manifest["required_scenarios"]) != {c["name"] for c in cases()}:
        raise SystemExit("stateful scenario manifest mismatch")
    pool=random_cases() if args.family=="random" or args.family.startswith("stateful_random_") else cases()
    selected = [c for c in pool if args.family in ("all", c["family"], c["name"])]
    if not selected: raise SystemExit("unknown stateful family")
    if not args.replay_only:
        subprocess.run([sys.executable, str(Path(__file__).with_name("run_shared_firmware.py")), "--model"],
                       env=dict(os.environ, PROTECTED_STATEFUL=args.family), cwd=ROOT, check=True)
    origin = ROOT / f"reports/compute_stateful_{args.family}_runs.csv"
    source = {r["scenario"]: r for r in csv.DictReader(origin.open())}
    rows = []
    for case in selected:
        run = source.get(case["name"], {})
        trace = ROOT / run.get("trace", "MISSING")
        errors = []
        witnesses = []
        digest = hashlib.sha256(trace.read_bytes()).hexdigest() if trace.is_file() else "MISSING"
        if run.get("status") != "PASS" or digest != run.get("trace_sha256"):
            errors.append("missing passing simulation or changed trace provenance")
        if trace.is_file():
            replay = check(trace, strict_schema=True)
            if replay["status"] != "PASS": errors.append("strict replay: " + replay["errors"])
            witnesses, intent_errors = qualify(events(trace), case["code"], case["name"])
            errors.extend(intent_errors)
            if case["code"] in (51,88,92) and check_host_trace(trace)["status"] != "PASS": errors.append("independent AES evidence failed")
        rows.append(dict(scenario=case["name"], family=case["family"], status="FAIL" if errors else "PASS",
                         evidence="actual_RTL_and_independent_replay", witness_count=len(witnesses),
                         event_ids=";".join(e["eid"] for e in witnesses), trace=run.get("trace", ""),
                         trace_sha256=digest, errors=";".join(errors)))
    out = ROOT / f"reports/compute_stateful_{args.family}_closure.csv"
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    if args.family == "all":
        lines = ["# Stateful Crossover Closure", "", "Supplemental executable evidence; canonical closure denominators remain unchanged.", "",
                 "| Family | Qualified scenarios | Witness events |", "|---|---:|---:|"]
        for family in dict.fromkeys(row["family"] for row in rows):
            group = [r for r in rows if r["family"] == family]
            lines.append(f"| {family} | {sum(r['status']=='PASS' for r in group)}/{len(group)} | {sum(r['witness_count'] for r in group)} |")
        lines += ["", "Every row requires a passing simulation, matching trace SHA-256, strict architectural/transaction/memory/numerical replay, and the designated activating events. Event IDs are local to the named run and reset epoch in the trace, not globally unique tags.", "",
                  "Coverage witnesses: [directed CSV](../reports/compute_stateful_all_closure.csv), [seeded multi-job CSV](../reports/compute_stateful_random_closure.csv), and [same-window crosses](compute_stateful_cross_coverage.md). Fresh code instrumentation: [report](compute_stateful_code_coverage.md).", "",
                  "## Reproducible Seeded Workloads", "",
                  "`make compute-stateful-random` executes 32 deterministic seeds. Each initializes both parameter banks and two independent input buffers, submits eight additional jobs after the baseline job, and runs all eight M opcodes plus timer interrupts. K, cache mode, ASID, QoS, channel stalls and response delays vary. Full trace replay independently validates memory, numerical results, response ownership and retirement; scenario qualification requires nine accepted descriptors, both banks and four timer entries. This is a finite seeded workload family, not exhaustive ISA or subsystem random closure.", "",
                  "## Evidence Boundaries", ""]
        lines.extend("- " + claim + "." for claim in manifest["excluded_claims"])
        lines += ["", "The TLB regression caught two independent-checker mistakes: assumed eight entries rather than this integration's four, and compacted invalidation instead of retaining physical replacement slots/cursor. The corrected model still checks exact observed hit/miss decisions. No DUT arithmetic failure was demonstrated."]
        (ROOT / "docs/compute_stateful_closure.md").write_text("\n".join(lines) + "\n")
    print(f"Qualified stateful crossover: {sum(r['status']=='PASS' for r in rows)}/{len(rows)}")
    for row in rows:
        if row["errors"]: print(row["scenario"] + ": " + row["errors"])
    return int(any(r["status"] != "PASS" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
