#!/usr/bin/env python3
"""Check normalized firmware/accelerator crossover events.

This deliberately checks transaction accounting and epoch containment without
reimplementing the accelerator arithmetic; numerical checking remains the
separate PyTorch integer model.  A mailbox alone is never enough for PASS.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
from collections import defaultdict, deque
import sys
import tempfile
from pathlib import Path

CHIPLET_SCRIPTS = Path(__file__).resolve().parents[4] / "ucie_chiplet_soc/chiplet_extension/scripts"
sys.path.insert(0, str(CHIPLET_SCRIPTS))
from rv32_iss import RV32ISS  # noqa: E402


def _signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "MISSING"


def _source_fingerprint() -> str:
    # Fingerprint the actual integration compile surface, not a hand-picked
    # subset that can silently miss a newly-added bridge or package.
    source_roots = (
        ROOT / "integration/protected_offload/rtl",
        ROOT / "integration/protected_offload/sim",
        ROOT / "integration/protected_offload/vendor/rv32",
        ROOT / "integration/protected_offload/vendor/axi",
        ROOT / "integration/protected_offload/vendor/cache",
        ROOT / "integration/protected_offload/vendor/chiplet",
        ROOT / "rtl",
    )
    sources = sorted(path for root in source_roots if root.exists()
                     for path in root.rglob("*") if path.is_file() and
                     (path.suffix in (".sv", ".v", ".vh", ".svh") or
                      root == ROOT / "rtl" and path.name == "int8_tensor_accel.sv"))
    sources.append(CHIPLET_SCRIPTS / "rv32_iss.py")
    sources.append(Path(__file__))
    digest = hashlib.sha256()
    for source in sorted(set(sources)):
        relative = str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else f"external/{source.name}"
        digest.update(relative.encode())
        digest.update(source.read_bytes() if source.is_file() else b"MISSING")
    return digest.hexdigest()


ROOT = Path(__file__).resolve().parents[3]


def _empty_accel_config():
    return {
        "weights": [[[0 for _ in range(64)] for _ in range(4)] for _ in range(2)],
        "bias": [[0 for _ in range(4)] for _ in range(2)],
        "multiplier": [[1 for _ in range(4)] for _ in range(2)],
        "shift": [[0 for _ in range(4)] for _ in range(2)],
        "relu": [[0 for _ in range(4)] for _ in range(2)],
        "input_zp": [0, 0],
        "weight_zp": [[0 for _ in range(4)] for _ in range(2)],
        "output_zp": [[0 for _ in range(4)] for _ in range(2)],
    }


def _predict_accel_word(config, bank: int, k: int, inputs: list[int]) -> int:
    if len(inputs) != k:
        raise ValueError(f"accelerator command K={k}, received {len(inputs)} input values")
    packed = 0
    for output in range(4):
        acc = config["bias"][bank][output]
        for index, activation in enumerate(inputs):
            acc += ((activation - config["input_zp"][bank]) *
                    (config["weights"][bank][output][index] - config["weight_zp"][bank][output]))
        acc = _signed(acc, 32)
        product = acc * config["multiplier"][bank][output]
        shift = config["shift"][bank][output]
        if shift:
            magnitude = abs(product) + (1 << (shift - 1))
            scaled = (magnitude >> shift) * (-1 if product < 0 else 1)
        else:
            scaled = product
        scaled += config["output_zp"][bank][output]
        if config["relu"][bank][output] and scaled < 0:
            scaled = 0
        value = max(-128, min(127, scaled)) & 0xFF
        packed |= value << (output * 8)
    return packed


def events(path: Path):
    parsed=[]
    for line in path.read_text().splitlines():
        if not line.startswith("CROSS_EVT|"):
            continue
        item={}
        for field in line.split("|")[1:]:
            if "=" not in field:
                continue
            key, value=field.split("=", 1)
            item[key]=value
        item.setdefault("_line", str(len(parsed) + 1))
        parsed.append(item)
    return parsed


def _num(event, key, default=0):
    value = event.get(key, str(default))
    try:
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return default


def _same_field(field: str, actual, expected) -> bool:
    """Compare observer values across decimal IDs and fixed-width hex payloads."""
    if field in {"tag"}:
        return str(actual) == str(expected)
    for value in (actual, expected):
        if value is None:
            return False
    def parse(value):
        if isinstance(value, int):
            return value
        text = str(value)
        try:
            return int(text, 0)
        except ValueError:
            # Observer address/data fields are emitted as zero-padded hex,
            # which Python's base-0 parser rejects when there is no 0x prefix.
            try:
                return int(text, 16)
            except ValueError:
                return text
    return parse(actual) == parse(expected)


def _value_int(value, default=0) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        try:
            return int(str(value), 16)
        except (TypeError, ValueError):
            return default


def _decode_iommu(pte_memory: dict[int, int], ptw_faults: set[int], iova: int,
                  write: int) -> tuple[int, int]:
    """Independent two-level Sv32 subset used by this integration's DMA IOMMU."""
    def valid(pte: int) -> bool:
        return bool(pte & 1) and not (bool(pte & 4) and not bool(pte & 2))
    def leaf(pte: int) -> bool:
        return bool(pte & 0xE)
    def permitted(pte: int) -> bool:
        return valid(pte) and leaf(pte) and bool(pte & (1 << 6)) and (
            bool(pte & 2) if not write else bool(pte & 4) and bool(pte & (1 << 7)))

    root_addr = 0x30000000 + (((iova >> 22) & 0x3FF) * 4)
    if root_addr in ptw_faults:
        return 3, 0
    root = pte_memory.get(root_addr, 0)
    if not valid(root):
        return 1, 0
    if leaf(root):
        if ((root >> 30) != 0) or ((root >> 10) & 0x3FF) != 0:
            return 1, 0
        if not permitted(root):
            return 2, 0
        return 0, (((root >> 20) & 0x3FF) << 22) | (iova & 0x3FFFFF)
    if (root >> 30) != 0:
        return 1, 0
    leaf_base = ((root >> 10) & 0xFFFFF) << 12
    leaf_addr = leaf_base + (((iova >> 12) & 0x3FF) * 4)
    if leaf_addr in ptw_faults:
        return 3, 0
    pte = pte_memory.get(leaf_addr, 0)
    if not valid(pte) or not leaf(pte) or (pte >> 30) != 0:
        return 1, 0
    if not permitted(pte):
        return 2, 0
    return 0, (((pte >> 10) & 0xFFFFF) << 12) | (iova & 0xFFF)


def _required_num(event, key, errors):
    """Parse a required numeric field without silently accepting corruption."""
    if key not in event:
        errors.append(f"line {event.get('_line')}: missing numeric field {key}")
        return None
    try:
        return int(event[key], 0) if isinstance(event[key], str) else int(event[key])
    except (TypeError, ValueError):
        errors.append(f"line {event.get('_line')}: malformed numeric field {key}={event[key]!r}")
        return None


def _firmware_manifest(image: Path, output: Path) -> None:
    pc_word = 0
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("pc", "insn"), lineterminator="\n")
        writer.writeheader()
        for token in image.read_text().split():
            if token.startswith("@"):
                pc_word = int(token[1:], 16)
            else:
                writer.writerow({"pc": f"{pc_word * 4:08x}", "insn": token})
                pc_word += 1


def check_architecture(parsed: list[dict[str, str]], trace: Path) -> list[str]:
    """Replay actual retirement records through the authoritative RV32 ISS."""
    firmware = trace.parent / "firmware.hex"
    data = trace.parent / "data.hex"
    if not firmware.is_file() or not data.is_file():
        return ["RV32 ISS input images are missing beside the trace"]
    retirements = [event for event in parsed if event.get("kind") == "RETIRE"]
    if not retirements:
        return ["RV32 ISS received no retired instructions"]
    columns = (
        "order", "epoch", "pc_rdata", "pc_wdata", "insn", "trap", "intr",
        "rs1_addr", "rs1_rdata", "rs2_addr", "rs2_rdata", "rd_addr", "rd_wdata",
        "mem_addr", "mem_rmask", "mem_wmask", "mem_rdata", "mem_wdata",
        "mstatus", "mie", "mtvec", "mscratch", "mepc", "mcause", "mtval",
        "irq_level", "irq_timer_level", "m_ext",
    )
    mapping = {
        "order": "retire_order", "pc_rdata": "pc", "pc_wdata": "next_pc",
        "rs1_rdata": "rs1_data", "rs2_rdata": "rs2_data", "rd_wdata": "rd_data",
    }
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="crossover_iss_") as temp_name:
        temp = Path(temp_name)
        manifest = temp / "instruction_manifest.csv"
        _firmware_manifest(firmware, manifest)
        enable_m = any(event.get("m_ext") == "1" for event in retirements)
        iss = RV32ISS(
            instruction_manifest=manifest,
            data_image=data,
            enable_m=enable_m,
            external_ranges=((0x40000000, 0x40002FFF), (0x50000000, 0x500000FF)),
            direct_memory_ranges=((0x10000000, 0x1000FFFF), (0x20000000, 0x2000FFFF),
                                  (0x30000000, 0x3000FFFF)),
        )
        for event in parsed:
            if event.get("kind") == "MEM_RSP" and event.get("write") == "1" and event.get("committed") == "1":
                try:
                    address = int(event["addr"], 16)
                    data_value = int(event["wdata"], 16)
                    strobe = int(event["wstrb"], 16)
                except (KeyError, ValueError):
                    errors.append(f"line {event.get('_line')}: malformed committed memory-write event")
                    continue
                base = address & ~3
                word = iss.memory.get(base, 0)
                for lane in range(4):
                    if strobe & (1 << lane):
                        byte = (data_value >> (lane * 8)) & 0xFF
                        word = (word & ~(0xFF << (lane * 8))) | (byte << (lane * 8))
                iss.memory[base] = word & 0xFFFF_FFFF
            if event.get("kind") == "RETIRE":
                row = {column: event.get(mapping.get(column, column), "0") for column in columns}
                iss.check_row(row)
        errors.extend(iss.mismatches)
        if iss.instructions != len(retirements):
            errors.append(f"RV32 ISS retired {iss.instructions}/{len(retirements)} trace records")
    return errors


def check(path: Path, strict_schema=False):
    """Replay one normalized trace with descriptor and epoch accounting.

    The old checker used aggregate counters and accepted a mailbox with no
    completed work.  This checker keeps per-epoch transaction lifetimes.  It
    intentionally leaves numerical checking to the independent accelerator
    model, but it will not allow that model to be bypassed by a mailbox.
    """
    outstanding=defaultdict(deque)
    ptw_outstanding = deque()
    axi_aw = deque()
    axi_w = deque()
    axi_ar = deque()
    last_successful_axi_write = None
    expected_axi_write_events = deque()
    # The testbench explicitly clears the 64-KiB payload SRAM before reset
    # release.  Seed the independent model from that environment contract;
    # subsequent contents change only on successful observed writes.
    byte_memory: dict[int, int] = {address: 0 for address in range(0x10000000, 0x10010000)}
    pte_memory: dict[int, int] = {}
    ptw_faults: set[int] = set()
    # Invalidation clears valid slots, not the round-robin replacement cursor.
    # protected_offload_service elaborates four entries (leaf default is eight).
    translation_cache: list[dict[str, int] | None] = [None] * 4
    translation_replace = 0
    submitted=defaultdict(deque)
    pending_output_writes=defaultdict(int)
    maintenance_active = False
    maintenance_count = 0
    apb_setup = None
    published=defaultdict(deque)
    canceled=set()
    commands=defaultdict(deque)
    accel_config = _empty_accel_config()
    accel_jobs = deque()
    accel_predictions = defaultdict(deque)
    config_apb = {"kind": 0, "bank": 0, "output": 0, "index": 0, "data": 0}
    pending_cfg_commit = None
    translated_pending = defaultdict(deque)
    input_words_pending = defaultdict(deque)
    accelerator_outputs_pending = defaultdict(deque)
    translation_word_index = defaultdict(int)
    committed_outputs = defaultdict(int)
    command_count = defaultdict(int)
    input_word_count = defaultdict(int)
    accel_outputs_checked = 0
    iss_checked = False
    iss_instructions = 0
    errors=[]
    epochs=set()
    counts={}
    done=False
    done_index=None
    m_retires=0
    retire_orders=set()
    last_retire_order={}
    parsed = events(path)
    if not parsed:
        return {"trace": path.parent.name + "/" + path.name, "status": "FAIL",
                "events": 0, "epochs": 0, "retirements": 0, "m_retires": 0,
                "apb_completions": 0, "translation_requests": 0, "memory_requests": 0,
                "submissions": 0, "accelerator_commands": 0, "completions": 0,
                "errors": "empty trace"}
    expected_eid=0
    current_epoch=None
    last_cycle=-1
    last_epoch_num=-1
    run_name=None
    build_name=None
    for index,event in enumerate(parsed):
        kind=event.get("kind", "")
        event_cycle = _num(event, "cycle", -1)
        matched_cfg_commit = False
        if pending_cfg_commit is not None:
            if event_cycle > pending_cfg_commit["cycle"]:
                errors.append(f"APB accelerator configuration commit at line {pending_cfg_commit['line']} had no matching decoded config event")
                pending_cfg_commit = None
            elif kind == "ACCEL_CFG":
                for field, value in pending_cfg_commit["expected"].items():
                    if _value_int(event.get(field), -1) != value:
                        errors.append(f"APB configuration commit {field} mismatch at line {event.get('_line')}: observer={event.get(field)} APB={value}")
                pending_cfg_commit = None
                matched_cfg_commit = True
        if not kind:
            errors.append(f"line {event.get('_line')}: missing event kind")
        if "schema" not in event:
            if strict_schema:
                errors.append(f"line {event.get('_line')}: missing schema")
        elif event["schema"] != "3":
            errors.append(f"line {event.get('_line')}: unsupported schema {event['schema']}")
        if strict_schema and not event.get("run"):
            errors.append(f"line {event.get('_line')}: missing run identity")
        if strict_schema and not event.get("build"):
            errors.append(f"line {event.get('_line')}: missing source build identity")
        if "eid" in event:
            eid = _required_num(event, "eid", errors) if strict_schema else _num(event, "eid", -1)
            if eid is None:
                eid = -1
            if eid != expected_eid:
                errors.append(f"line {event.get('_line')}: event id {eid} expected {expected_eid}")
            expected_eid=eid+1
        elif strict_schema:
            errors.append(f"line {event.get('_line')}: missing event id")
        counts[kind]=counts.get(kind, 0)+1
        if run_name is None:
            run_name = event.get("run")
        elif strict_schema and event.get("run") != run_name:
            errors.append(f"line {event.get('_line')}: run identity changed from {run_name} to {event.get('run')}")
        if build_name is None:
            build_name = event.get("build")
        elif strict_schema and event.get("build") != build_name:
            errors.append(f"line {event.get('_line')}: source build identity changed within one trace")
        if "epoch" not in event:
            errors.append(f"line {event.get('_line')}: missing epoch")
            continue
        epoch=event["epoch"]
        epochs.add(epoch)
        current_epoch=epoch
        epoch_num = _required_num(event, "epoch", errors) if strict_schema else _num(event, "epoch", -1)
        cycle_num = _required_num(event, "cycle", errors) if strict_schema else _num(event, "cycle", -1)
        epoch_num = -1 if epoch_num is None else epoch_num
        cycle_num = -1 if cycle_num is None else cycle_num
        if strict_schema and epoch_num < last_epoch_num:
            errors.append(f"line {event.get('_line')}: reset epoch moved backwards")
        if strict_schema and cycle_num < last_cycle:
            errors.append(f"line {event.get('_line')}: event cycle moved backwards")
        last_epoch_num=max(last_epoch_num, epoch_num)
        last_cycle=max(last_cycle, cycle_num)
        if done:
            errors.append(f"event {kind} appears after firmware completion")
        if kind == "RESET_ASSERT":
            if strict_schema:
                for field, key in (("xlate_pending", "XLATE"), ("mem_pending", "MEM"),
                                   ("ptw_pending", "PTW"), ("host_aw_pending", "AXI_AW"),
                                   ("host_w_pending", "AXI_W"), ("host_ar_pending", "AXI_AR")):
                    value = _required_num(event, field, errors)
                    actual_pending = (bool(outstanding[key]) if key in ("XLATE", "MEM") else
                                      bool(ptw_outstanding) if key == "PTW" else
                                      bool(axi_aw) if key == "AXI_AW" else bool(axi_w))
                    if key == "AXI_AR":
                        actual_pending = bool(axi_ar)
                    if value is not None and bool(value) != actual_pending:
                        errors.append(f"reset pending-{key.lower()} flag disagrees with accepted transaction ledger at line {event.get('_line')}")
                for field, expected in (("apb_active", apb_setup is not None),
                                        ("maint_active", maintenance_active)):
                    value = _required_num(event, field, errors)
                    if value is not None and bool(value) != expected:
                        errors.append(f"reset {field} flag disagrees with lifecycle ledger at line {event.get('_line')}")
            for key, queue in list(outstanding.items()):
                if queue:
                    canceled.update((kind_name, txn["id"]) for txn in queue for kind_name in (key,))
            outstanding=defaultdict(deque)
            ptw_outstanding.clear()
            axi_aw.clear()
            axi_w.clear()
            axi_ar.clear()
            expected_axi_write_events.clear()
            last_successful_axi_write = None
            translation_cache = [None] * 4
            translation_replace = 0
            commands=defaultdict(deque)
            accel_config = _empty_accel_config()
            accel_jobs.clear()
            accel_predictions=defaultdict(deque)
            config_apb = {"kind": 0, "bank": 0, "output": 0, "index": 0, "data": 0}
            pending_cfg_commit = None
            translated_pending = defaultdict(deque)
            input_words_pending = defaultdict(deque)
            accelerator_outputs_pending = defaultdict(deque)
            translation_word_index = defaultdict(int)
            committed_outputs = defaultdict(int)
            command_count = defaultdict(int)
            input_word_count = defaultdict(int)
            # Descriptors that survived reset are tombstoned, not reusable.
            for tag, queue in submitted.items():
                canceled.update(("DESC", txn["id"]) for txn in queue)
            submitted=defaultdict(deque)
            pending_output_writes=defaultdict(int)
            published=defaultdict(deque)
            # Reset is the only legal way to cancel an in-flight maintenance
            # operation.  Keep this distinct from a successful MAINT_DONE.
            maintenance_active = False
            apb_setup = None
        elif kind in ("XLATE_REQ", "MEM_REQ"):
            txn_id=event.get("txn", event.get("id", f"{kind}:{index}"))
            key = kind.split("_")[0]
            if strict_schema and (txn_id is None or str(txn_id) == ""):
                errors.append(f"line {event.get('_line')}: {kind} missing transaction identity")
            if any(str(txn["id"]) == str(txn_id) for txn in outstanding[key]):
                errors.append(f"line {event.get('_line')}: duplicate live {key} transaction identity {txn_id}")
            request = {"id": txn_id, "epoch": epoch, "kind": kind}
            if kind == "MEM_REQ":
                request.update({
                    "write": _num(event, "write", 0), "addr": event.get("addr"),
                    "wdata": event.get("wdata"), "wstrb": event.get("wstrb"),
                    "tag": event.get("tag", ""), "vector": event.get("vector"),
                })
                if strict_schema:
                    for field in ("write", "addr", "wdata", "wstrb", "tag", "vector"):
                        if field not in event:
                            errors.append(f"line {event.get('_line')}: MEM_REQ missing {field}")
            else:
                request.update({
                    "iova": event.get("iova"), "asid": event.get("asid"),
                    "write": _num(event, "write", 0), "tag": event.get("tag", ""),
                    "vector": event.get("vector"),
                })
                if strict_schema:
                    for field in ("iova", "asid", "write", "tag", "vector"):
                        if field not in event:
                            errors.append(f"line {event.get('_line')}: XLATE_REQ missing {field}")
                    live = submitted.get(request["tag"], ())
                    if not live:
                        errors.append(f"XLATE_REQ has no accepted descriptor owner at line {event.get('_line')}")
                    else:
                        descriptor = live[-1]
                        try:
                            vector = _value_int(request["vector"], -1)
                            write = request["write"]
                            if descriptor["epoch"] != epoch or vector < 0 or vector >= descriptor["batch"]:
                                raise ValueError("epoch or vector does not match accepted descriptor")
                            if write:
                                expected_iova = descriptor["output_iova"] + vector * descriptor["output_stride"]
                            else:
                                offset_key = (epoch, request["tag"], vector, 0)
                                word_index = translation_word_index[offset_key]
                                if word_index >= descriptor["k"] // 4:
                                    raise ValueError("input word count exceeds descriptor K")
                                expected_iova = descriptor["input_iova"] + vector * descriptor["input_stride"] + word_index * 4
                                translation_word_index[offset_key] += 1
                            observed_iova = int(str(request["iova"]), 16)
                            if observed_iova != expected_iova:
                                errors.append(f"descriptor {request['tag']} IOVA mismatch at line {event.get('_line')}: observed=0x{observed_iova:08x} expected=0x{expected_iova:08x}")
                        except (KeyError, TypeError, ValueError) as exc:
                            errors.append(f"descriptor translation lineage invalid at line {event.get('_line')}: {exc}")
            if kind == "MEM_REQ" and strict_schema:
                try:
                    tag = request["tag"]
                    vector = _value_int(request["vector"], -1)
                    write = request["write"]
                    paddr_q = translated_pending[(epoch, tag, vector, write)]
                    if not paddr_q:
                        errors.append(f"MEM_REQ has no matching successful translation at line {event.get('_line')}")
                    elif int(str(request["addr"]), 16) != paddr_q.popleft():
                        errors.append(f"MEM_REQ physical address differs from its translated descriptor address at line {event.get('_line')}")
                    if write:
                        output_q = accelerator_outputs_pending[(epoch, tag, vector)]
                        if not output_q:
                            errors.append(f"output MEM_REQ has no matching accelerator result at line {event.get('_line')}")
                        elif int(str(request["wdata"]), 16) != output_q.popleft():
                            errors.append(f"output MEM_REQ data differs from accelerator result at line {event.get('_line')}")
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"malformed descriptor MEM_REQ lineage at line {event.get('_line')}: {exc}")
            outstanding[key].append(request)
            if kind == "MEM_REQ" and _num(event,"write",0) and event.get("tag"):
                pending_output_writes[event["tag"]] += 1
        elif kind == "PTW_REQ":
            if ptw_outstanding:
                errors.append(f"overlapping page-walk requests violate the single-walk IOMMU contract at line {event.get('_line')}")
            ptw_outstanding.append({"id": event.get("txn"), "addr": event.get("addr"), "epoch": epoch})
            if strict_schema and (event.get("txn") is None or event.get("addr") is None):
                errors.append(f"line {event.get('_line')}: PTW_REQ missing transaction or address")
        elif kind == "PTW_RSP":
            if not ptw_outstanding:
                errors.append(f"PTW_RSP without accepted page-walk request at line {event.get('_line')}")
            else:
                request = ptw_outstanding.popleft()
                if str(request.get("id")) != str(event.get("txn")):
                    errors.append(f"PTW_RSP transaction identity mismatch at line {event.get('_line')}")
                if not _same_field("addr", event.get("addr"), request.get("addr")):
                    errors.append(f"PTW_RSP address differs from accepted page-walk request at line {event.get('_line')}")
                if request.get("epoch") != epoch:
                    errors.append(f"PTW_RSP crossed reset epoch at line {event.get('_line')}")
                try:
                    address = int(event["addr"], 16)
                    data = int(event["data"], 16)
                    failed = int(event["error"], 0) != 0
                except (KeyError, ValueError):
                    errors.append(f"line {event.get('_line')}: malformed PTW response")
                else:
                    if failed:
                        ptw_faults.add(address)
                    else:
                        expected = pte_memory.get(address, 0)
                        if data != expected:
                            errors.append(f"page-table read mismatch at 0x{address:08x}: observed 0x{data:08x}, model 0x{expected:08x}")
                        ptw_faults.discard(address)
        elif kind == "AXI_AW":
            if axi_aw:
                errors.append(f"host accepted multiple outstanding AW requests at line {event.get('_line')}")
            if strict_schema and any(field not in event for field in ("master", "id", "addr", "len", "size", "burst")):
                errors.append(f"line {event.get('_line')}: AXI_AW missing identity or burst geometry")
            length = _value_int(event.get("len"), -1)
            size = _value_int(event.get("size"), -1)
            burst = _value_int(event.get("burst"), -1)
            if length < 0 or length > 15 or size not in range(4) or burst != 1:
                errors.append(f"unsupported or malformed host AXI write burst at line {event.get('_line')}")
            axi_aw.append({"id": event.get("id"), "addr": event.get("addr"),
                           "len": length, "size": size, "burst": burst,
                           "master": event.get("master"), "epoch": epoch})
        elif kind == "AXI_W":
            if len(axi_w) >= 16:
                errors.append(f"host W burst exceeded checker buffer at line {event.get('_line')}")
            if strict_schema and any(field not in event for field in ("master", "beat", "data", "strb", "last")):
                errors.append(f"line {event.get('_line')}: AXI_W missing payload, strobe, or last")
            beat = len(axi_w)
            if _value_int(event.get("beat"), -1) != beat:
                errors.append(f"host W beat index is not contiguous at line {event.get('_line')}")
            axi_w.append({"data": event.get("data"), "strb": event.get("strb"),
                          "last": _value_int(event.get("last"), -1),
                          "master": event.get("master"), "epoch": epoch})
        elif kind == "AXI_B":
            if expected_axi_write_events:
                errors.append(f"new host B arrived before prior AXI_WRITE summary beats at line {event.get('_line')}")
            if not axi_aw or not axi_w:
                errors.append(f"host B response without accepted AW and W at line {event.get('_line')}")
                last_successful_axi_write = None
            else:
                aw = axi_aw.popleft()
                expected_beats = aw["len"] + 1
                if len(axi_w) != expected_beats:
                    errors.append(f"host B observed {len(axi_w)} W beats, expected {expected_beats} at line {event.get('_line')}")
                beats = [axi_w.popleft() for _ in range(min(len(axi_w), expected_beats))]
                if not _same_field("id", event.get("id"), aw.get("id")):
                    errors.append(f"host B response ID does not match accepted AW at line {event.get('_line')}")
                if not _same_field("master", event.get("master"), aw.get("master")):
                    errors.append(f"host B response master does not match accepted AW at line {event.get('_line')}")
                if aw.get("epoch") != epoch or any(w.get("epoch") != epoch for w in beats):
                    errors.append(f"host B response crossed reset epoch at line {event.get('_line')}")
                for beat_index, beat_row in enumerate(beats):
                    if not _same_field("master", beat_row.get("master"), aw.get("master")):
                        errors.append(f"host W master differs from AW owner at beat {beat_index} line {event.get('_line')}")
                    if beat_row.get("last") != int(beat_index == aw["len"]):
                        errors.append(f"host WLAST mismatch at beat {beat_index} line {event.get('_line')}")
                aw_address = int(str(aw.get("addr", "-1")), 16)
                response_ok = _num(event, "resp", -1) == 0
                if strict_schema and "resp" not in event:
                    errors.append(f"line {event.get('_line')}: AXI_B missing response")
                if _num(event, "resp", -1) not in range(4):
                    errors.append(f"AXI_B has illegal response encoding at line {event.get('_line')}")
                if response_ok:
                    try:
                        for beat_index, beat_row in enumerate(beats):
                            data = int(str(beat_row["data"]), 16)
                            strobe = int(str(beat_row["strb"]), 16)
                            beat_address = aw_address + (beat_index << aw["size"])
                            base = beat_address & ~7
                            for lane in range(8):
                                if strobe & (1 << lane):
                                    byte_memory[base + lane] = (data >> (lane * 8)) & 0xFF
                            expected_axi_write_events.append({"master": aw.get("master"),
                                "addr": beat_address, "beat": beat_index, "len": aw["len"],
                                "size": aw["size"], "data": data, "strb": strobe})
                    except (KeyError, ValueError):
                        errors.append(f"successful host AXI write has malformed data/strobe at line {event.get('_line')}")
                first_beat = beats[0] if beats else {}
                last_successful_axi_write = ({"addr": aw.get("addr"), "data": first_beat.get("data"),
                                              "strb": first_beat.get("strb"), "success": response_ok,
                                              "len": aw["len"]}
                                             if 0x30000000 <= aw_address < 0x30010000 else None)
        elif kind == "AXI_WRITE":
            # Check the summary event against accepted AW/W and B. The model
            # update itself is applied from those lower-level channel events.
            try:
                address = int(event["addr"], 16)
                data = int(event["data"], 16)
                strobe = int(event["strb"], 16)
                length = _value_int(event.get("len"), 0)
                size = _value_int(event.get("size"), -1)
                beat_index = _value_int(event.get("beat"), -1)
                master = event.get("master")
                if length < 0 or length > 15 or size < 0 or size > 3 or beat_index < 0:
                    raise ValueError("unsupported host write geometry")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"malformed host AXI_WRITE at line {event.get('_line')}: {exc}")
            else:
                expected = expected_axi_write_events.popleft() if expected_axi_write_events else None
                if expected is None:
                    errors.append(f"AXI_WRITE summary without successful B response at line {event.get('_line')}")
                elif (address != expected["addr"] or data != expected["data"] or
                      strobe != expected["strb"] or length != expected["len"] or
                      size != expected["size"] or beat_index != expected["beat"] or
                      not _same_field("master", master, expected["master"])):
                    errors.append(f"AXI_WRITE summary disagrees with accepted channel payload at line {event.get('_line')}")
        elif kind == "PTE_WRITE":
            try:
                address = int(event["addr"], 16) & ~7
                data = int(event["data"], 16)
                strobe = int(event["strb"], 16)
            except (KeyError, ValueError):
                errors.append(f"line {event.get('_line')}: malformed committed page-table write")
            else:
                if (last_successful_axi_write is None or not last_successful_axi_write.get("success") or
                    last_successful_axi_write.get("len") != 0):
                    errors.append(f"page-table model updated without a successful matching AXI B response at line {event.get('_line')}")
                elif any(not _same_field(field, event.get(field), last_successful_axi_write.get(src))
                         for field, src in (("addr", "addr"), ("data", "data"), ("strb", "strb"))):
                    errors.append(f"PTE_WRITE payload differs from accepted AXI AW/W at line {event.get('_line')}")
                last_successful_axi_write = None
                for lane in range(8):
                    byte_address = address + lane
                    if strobe & (1 << lane) and 0x30000000 <= byte_address < 0x30010000:
                        word_address = byte_address & ~3
                        shift = (byte_address & 3) * 8
                        word = pte_memory.get(word_address, 0)
                        byte = (data >> (lane * 8)) & 0xFF
                        pte_memory[word_address] = (word & ~(0xFF << shift)) | (byte << shift)
                        ptw_faults.discard(word_address)
        elif kind == "TLB_INVALIDATE":
            if strict_schema and ("all" not in event or "asid" not in event):
                errors.append(f"line {event.get('_line')}: TLB_INVALIDATE missing scope")
            invalidate_all = _num(event, "all", 0) != 0
            invalidate_asid = _num(event, "asid", -1)
            translation_cache = [entry if entry is not None and not invalidate_all
                                 and entry["asid"] != invalidate_asid else None
                                 for entry in translation_cache]
        elif kind == "AXI_AR":
            if axi_ar:
                errors.append(f"host accepted a second read before final R at line {event.get('_line')}")
            try:
                if strict_schema and any(field not in event for field in ("master", "id", "addr", "len", "size", "burst")):
                    raise ValueError("missing read identity or burst geometry")
                request = {"id": event["id"], "addr": int(event["addr"], 16),
                           "len": _value_int(event["len"], -1),
                           "size": _value_int(event["size"], -1),
                           "burst": _value_int(event["burst"], -1),
                           "master": event.get("master"), "epoch": epoch, "beat": 0}
                if request["len"] < 0 or request["size"] not in range(4):
                    raise ValueError("invalid AXI read geometry")
                if request["len"] > 15 or request["burst"] != 1:
                    raise ValueError("unsupported host read length/burst mode")
                axi_ar.append(request)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"malformed host AXI_AR at line {event.get('_line')}: {exc}")
        elif kind == "AXI_R":
            if not axi_ar:
                errors.append(f"host R response without accepted AR at line {event.get('_line')}")
            else:
                request = axi_ar[0]
                beat = _value_int(event.get("beat"), -1)
                try:
                    if strict_schema and any(field not in event for field in ("master", "id", "addr", "beat", "size", "data", "resp", "last")):
                        raise ValueError("missing response identity, payload, or final-beat marker")
                    response_id = _value_int(event["id"], -1)
                    address = int(event["addr"], 16)
                    data = int(event["data"], 16)
                    response = _value_int(event.get("resp"), -1)
                    last = _value_int(event.get("last"), -1)
                except (KeyError, TypeError, ValueError):
                    errors.append(f"malformed host AXI_R at line {event.get('_line')}")
                    continue
                expected_address = request["addr"] + (request["beat"] << request["size"])
                if response_id != _value_int(request["id"], -2):
                    errors.append(f"host R ID mismatch at line {event.get('_line')}")
                if not _same_field("master", event.get("master"), request.get("master")):
                    errors.append(f"host R master mismatch at line {event.get('_line')}")
                if _value_int(event.get("size"), -1) != request["size"]:
                    errors.append(f"host R transfer size mismatch at line {event.get('_line')}")
                if address != expected_address or beat != request["beat"]:
                    errors.append(f"host R beat/address mismatch at line {event.get('_line')}")
                if address != expected_address:
                    errors.append(f"host R address progression mismatch at line {event.get('_line')}")
                if request["epoch"] != epoch:
                    errors.append(f"host R crossed reset epoch at line {event.get('_line')}")
                if last != int(request["beat"] == request["len"]):
                    errors.append(f"host RLAST mismatch at line {event.get('_line')}")
                if response not in range(4):
                    errors.append(f"host R has illegal response encoding at line {event.get('_line')}")
                if response == 0:
                    base = address & ~7
                    transfer_bytes = 1 << request["size"]
                    transfer_base = address
                    known = all((transfer_base + lane) in byte_memory
                                for lane in range(transfer_bytes))
                    if known:
                        lane_offset = address & 7
                        mask = ((1 << transfer_bytes) - 1) << lane_offset
                        expected_data = sum(byte_memory[base + lane] << (8 * lane)
                                            for lane in range(8) if mask & (1 << lane))
                        observed_mask = sum(0xFF << (8 * lane)
                                            for lane in range(8) if mask & (1 << lane))
                        data &= observed_mask
                        if data != expected_data:
                            errors.append(f"host AXI read data mismatch at 0x{base:08x}: observed 0x{data:016x}, modeled 0x{expected_data:016x}")
                    elif strict_schema:
                        errors.append(f"host AXI read at 0x{transfer_base:08x} has uninitialized transfer bytes")
                request["beat"] += 1
                if last:
                    axi_ar.popleft()
        elif kind in ("XLATE_RSP", "MEM_RSP"):
            key=kind.split("_")[0]
            response_id=event.get("txn", event.get("id"))
            if response_id is not None and (key, str(response_id)) in canceled:
                errors.append(f"{kind} returned a pre-reset transaction after reset at line {event.get('_line')}")
            if not outstanding[key]:
                errors.append(f"{kind} without accepted request at line {event.get('_line')}")
            else:
                txn=outstanding[key].popleft()
                if txn["epoch"] != epoch:
                    errors.append(f"{kind} crossed reset epoch at line {event.get('_line')}")
                if strict_schema and event.get("txn") is None:
                    errors.append(f"{kind} missing transaction identity at line {event.get('_line')}")
                elif event.get("txn") is not None and str(event.get("txn")) != str(txn["id"]):
                    errors.append(f"{kind} transaction {event.get('txn')} mismatches request {txn['id']} at line {event.get('_line')}")
                response_fields = ("write", "addr", "wdata", "wstrb", "tag", "vector") if kind == "MEM_RSP" else ("iova", "asid", "write", "tag", "vector")
                for field in response_fields:
                    expected = txn.get(field)
                    actual = event.get(field)
                    if strict_schema and actual is None:
                        errors.append(f"line {event.get('_line')}: {kind} missing echoed request field {field}")
                    elif expected is not None and actual is not None:
                        matches = _same_field(field, actual, expected)
                        if not matches:
                            errors.append(f"{kind} {field}={actual} mismatches accepted request {expected} at line {event.get('_line')}")
                if kind == "MEM_RSP":
                    if strict_schema and "error" not in event:
                        errors.append(f"line {event.get('_line')}: MEM_RSP missing error result")
                    if strict_schema and "committed" not in event:
                        errors.append(f"line {event.get('_line')}: MEM_RSP missing commit result")
                    if event.get("committed") is not None:
                        expected_commit = int(bool(txn.get("write")) and _num(event, "error", 0) == 0)
                        if _num(event, "committed", -1) != expected_commit:
                            errors.append(f"MEM_RSP committed flag disagrees with write/error at line {event.get('_line')}")
                    if _num(event, "error", 1) == 0:
                        if txn.get("write"):
                            try:
                                address = int(str(txn["addr"]), 16)
                                data = int(str(txn["wdata"]), 16)
                                strobe = int(str(txn["wstrb"]), 16)
                            except (KeyError, ValueError):
                                errors.append(f"committed DMA write lacks valid address/data/strobe at line {event.get('_line')}")
                            else:
                                for lane in range(4):
                                    if strobe & (1 << lane):
                                        byte_memory[address + lane] = (data >> (lane * 8)) & 0xFF
                        else:
                            try:
                                address = int(str(txn["addr"]), 16)
                                observed = int(event["rdata"], 16)
                            except (KeyError, ValueError):
                                errors.append(f"successful DMA read lacks valid data at line {event.get('_line')}")
                            else:
                                known = all((address + lane) in byte_memory for lane in range(4))
                                if known:
                                    expected = sum(byte_memory[address + lane] << (lane * 8) for lane in range(4))
                                    if observed != expected:
                                        errors.append(f"DMA read data mismatch at 0x{address:08x}: observed 0x{observed:08x}, modeled 0x{expected:08x}")
                                elif strict_schema:
                                    errors.append(f"DMA read at 0x{address:08x} has no initialized independent memory model")
                if kind == "XLATE_RSP" and strict_schema:
                    for field in ("fault", "paddr", "iova", "asid", "write", "tlb_hit"):
                        if field not in event:
                            errors.append(f"line {event.get('_line')}: XLATE_RSP missing {field}")
                    request = txn
                    try:
                        iova = int(str(request["iova"]), 16)
                        asid = _value_int(request["asid"], -1)
                        write = _value_int(request["write"], -1)
                        actual_fault = _value_int(event["fault"], -1)
                        actual_paddr = int(str(event["paddr"]), 16)
                        reported_hit = _value_int(event["tlb_hit"], -1)
                    except (KeyError, TypeError, ValueError):
                        errors.append(f"line {event.get('_line')}: malformed translation response/model inputs")
                    else:
                        if int(str(event.get("iova", "-1")), 16) != iova or _value_int(event.get("asid"), -2) != asid or _value_int(event.get("write"), -2) != write:
                            errors.append(f"XLATE_RSP request identity differs from accepted request at line {event.get('_line')}")
                        cached = next((entry for entry in reversed(translation_cache)
                                       if entry is not None and entry["asid"] == asid and entry["vpn1"] == ((iova >> 22) & 0x3FF)
                                       and (entry["superpage"] or entry["vpn0"] == ((iova >> 12) & 0x3FF))), None)
                        if cached is not None:
                            model_hit = 1
                            allowed = bool(cached["accessed"]) and (bool(cached["write"] and cached["dirty"]) if write else bool(cached["read"]))
                            model_fault = 0 if allowed else 2
                            model_paddr = ((cached["ppn"] & 0xFFFFF) << 12) | (iova & 0xFFF)
                            if cached["superpage"]:
                                model_paddr = (((cached["ppn"] >> 10) & 0x3FF) << 22) | (iova & 0x3FFFFF)
                            # A failed translation never exposes a usable PA,
                            # even though the TLB contains its cached PPN.
                            if model_fault:
                                model_paddr = 0
                        else:
                            model_hit = 0
                            model_fault, model_paddr = _decode_iommu(pte_memory, ptw_faults, iova, write)
                            if model_fault == 0:
                                root_addr = 0x30000000 + (((iova >> 22) & 0x3FF) * 4)
                                root = pte_memory.get(root_addr, 0)
                                if root & 0xE:
                                    leaf_pte, superpage = root, 1
                                else:
                                    leaf_addr = (((root >> 10) & 0xFFFFF) << 12) + (((iova >> 12) & 0x3FF) * 4)
                                    leaf_pte, superpage = pte_memory.get(leaf_addr, 0), 0
                                translation_cache[translation_replace] = {"asid": asid, "vpn1": (iova >> 22) & 0x3FF,
                                    "vpn0": (iova >> 12) & 0x3FF, "ppn": (leaf_pte >> 10) & 0xFFFFF,
                                    "read": (leaf_pte >> 1) & 1, "write": (leaf_pte >> 2) & 1,
                                    "accessed": (leaf_pte >> 6) & 1, "dirty": (leaf_pte >> 7) & 1,
                                    "superpage": superpage}
                                translation_replace = (translation_replace + 1) % len(translation_cache)
                        if actual_fault != model_fault:
                            errors.append(f"IOMMU fault mismatch at line {event.get('_line')}: observed {actual_fault}, predicted {model_fault}")
                        if actual_paddr != model_paddr:
                            errors.append(f"IOMMU physical address mismatch at line {event.get('_line')}: observed 0x{actual_paddr:08x}, predicted 0x{model_paddr:08x}")
                        if reported_hit != model_hit:
                            errors.append(f"IOMMU TLB hit/miss mismatch at line {event.get('_line')}: observed {reported_hit}, predicted {model_hit}")
                        if actual_fault == 0:
                            key = (epoch, str(request.get("tag", "")),
                                   _value_int(request.get("vector"), -1), write)
                            translated_pending[key].append(actual_paddr)
                if kind == "MEM_RSP" and txn.get("write") and txn.get("tag"):
                    tag=txn["tag"]
                    if pending_output_writes[tag] <= 0:
                        errors.append(f"write response has no per-descriptor pending write for tag {tag} at line {event.get('_line')}")
                    else:
                        pending_output_writes[tag] -= 1
                    if _num(event, "error", 1) == 0:
                        committed_outputs[(epoch, tag)] += 1
                elif kind == "MEM_RSP" and not txn.get("write") and txn.get("tag") and _num(event, "error", 1) == 0:
                    try:
                        read_word = int(event["rdata"], 16)
                        vector = _value_int(event.get("vector"), -1)
                        input_words_pending[(epoch, txn["tag"], vector)].append(read_word)
                    except (KeyError, ValueError):
                        errors.append(f"successful DMA input read lacks a usable payload at line {event.get('_line')}")
        elif kind == "MAINT_START":
            if maintenance_active:
                errors.append(f"maintenance started while another operation remained active at line {event.get('_line')}")
            maintenance_active = True
            maintenance_count += 1
        elif kind == "MAINT_DONE":
            if not maintenance_active:
                errors.append(f"maintenance completed without an accepted start at line {event.get('_line')}")
            maintenance_active = False
        elif kind == "APB_SETUP":
            if apb_setup is not None:
                errors.append(f"APB setup began before the prior access completed at line {event.get('_line')}")
            apb_setup = {"op": event.get("op"), "write": event.get("write"), "addr": event.get("addr"), "wdata": event.get("wdata")}
            if strict_schema and any(apb_setup[field] is None for field in ("op", "write", "addr")):
                errors.append(f"line {event.get('_line')}: APB_SETUP missing operation controls")
        elif kind == "APB":
            if apb_setup is None:
                errors.append(f"APB access completion without setup phase at line {event.get('_line')}")
            else:
                for field in ("op", "write", "addr"):
                    if not _same_field(field, event.get(field), apb_setup.get(field)):
                        errors.append(f"APB {field} changed between setup and access at line {event.get('_line')}")
                if strict_schema and event.get("write") == "1" and "wdata" not in event:
                    errors.append(f"line {event.get('_line')}: APB write missing accepted write data")
                elif event.get("write") == "1" and not _same_field("wdata", event.get("wdata"), apb_setup.get("wdata")):
                    errors.append(f"APB write data changed between setup and access at line {event.get('_line')}")
                if event.get("write") == "1" and _num(event, "error", 1) == 0:
                    address = int(str(event.get("addr", "0")), 16)
                    if address == 0x40001000: config_apb["kind"] = _value_int(event.get("wdata"), -1) & 7
                    elif address == 0x40001004:
                        value = _value_int(event.get("wdata"), -1)
                        config_apb["output"], config_apb["bank"] = value & 3, (value >> 2) & 1
                    elif address == 0x40001008: config_apb["index"] = _value_int(event.get("wdata"), -1) & 0x3f
                    elif address == 0x4000100c: config_apb["data"] = _value_int(event.get("wdata"), -1)
                    elif address == 0x40001014:
                        pending_cfg_commit = {"cycle": event_cycle, "line": event.get("_line"),
                            "expected": {"cfg_kind": config_apb["kind"], "bank": config_apb["bank"],
                                         "output": config_apb["output"], "index": config_apb["index"],
                                         "data": config_apb["data"]}}
                apb_setup = None
        elif kind == "RETIRE":
            if strict_schema:
                # The crossover lane is intended to be architectural evidence,
                # not just a PC/count trace.  Require the complete RVFI-style
                # record so an incomplete adapter cannot silently pass.
                rvfi_fields = (
                    "pc", "next_pc", "insn", "retire_order", "trap", "intr",
                    "rs1_addr", "rs1_data", "rs2_addr", "rs2_data",
                    "rd_addr", "rd_data", "mem_addr", "mem_rmask",
                    "mem_wmask", "mem_rdata", "mem_wdata", "mstatus",
                    "mie", "mtvec", "mscratch", "mepc", "mcause", "mtval",
                )
                missing = [field for field in rvfi_fields if field not in event]
                if missing:
                    errors.append(
                        f"line {event.get('_line')}: retirement missing RVFI fields "
                        + ",".join(missing)
                    )
            try:
                insn=int(event.get("insn", "0"), 16)
            except ValueError:
                errors.append(f"line {event.get('_line')}: malformed instruction encoding")
                insn=0
            if (insn & 0x7f) == 0x33 and ((insn >> 25) & 0x7f) == 1:
                m_retires += 1
            if strict_schema:
                order = _required_num(event, "retire_order", errors)
                if order is not None:
                    retire_key = (epoch, order)
                    if retire_key in retire_orders:
                        errors.append(f"duplicate retirement order {order} at line {event.get('_line')}")
                    if order <= last_retire_order.get(epoch, -1):
                        errors.append(f"retirement order {order} is not strictly increasing")
                    retire_orders.add(retire_key)
                    last_retire_order[epoch] = max(last_retire_order.get(epoch, -1), order)
        elif kind == "ACCEL_CFG":
            if strict_schema and not matched_cfg_commit:
                errors.append(f"accelerator configuration event has no matching successful APB commit at line {event.get('_line')}")
            try:
                cfg_kind = int(event["cfg_kind"])
                bank = int(event["bank"])
                output = int(event["output"])
                index = int(event["index"])
                data = int(event["data"], 16)
                if bank not in (0, 1) or output not in range(4):
                    raise ValueError("configuration bank/output outside supported range")
                if cfg_kind == 0:
                    if index not in range(64):
                        raise ValueError("weight index outside supported range")
                    accel_config["weights"][bank][output][index] = _signed(data, 8)
                elif cfg_kind == 1:
                    accel_config["bias"][bank][output] = _signed(data, 32)
                elif cfg_kind == 2:
                    accel_config["multiplier"][bank][output] = _signed(data, 16)
                    accel_config["shift"][bank][output] = (data >> 16) & 0x1F
                elif cfg_kind == 3:
                    accel_config["relu"][bank][output] = data & 1
                    accel_config["input_zp"][bank] = _signed(data >> 8, 8)
                    accel_config["weight_zp"][bank][output] = _signed(data >> 16, 8)
                    accel_config["output_zp"][bank][output] = _signed(data >> 24, 8)
                else:
                    raise ValueError("unknown accelerator configuration kind")
            except (KeyError, ValueError) as exc:
                errors.append(f"malformed accelerator configuration event at line {event.get('_line')}: {exc}")
        elif kind == "ACCEL_CMD":
            tag=event.get("tag", "")
            if strict_schema and not tag:
                errors.append(f"line {event.get('_line')}: accelerator command missing tag")
            commands[tag].append({"epoch":epoch, "line":event.get("_line")})
            try:
                bank = int(event["bank"])
                k = int(event["k"])
                if bank not in (0, 1) or k < 4 or k > 64 or k % 4:
                    raise ValueError("invalid bank/K command fields")
                live = submitted.get(tag, ())
                if strict_schema and (not live or live[-1]["epoch"] != epoch):
                    errors.append(f"accelerator command has no live descriptor owner at line {event.get('_line')}")
                elif strict_schema and live:
                    descriptor = live[-1]
                    if bank != descriptor["bank"] or k != descriptor["k"]:
                        errors.append(f"accelerator command bank/K differs from submitted descriptor at line {event.get('_line')}")
                command_count[(epoch, tag)] += 1
                accel_jobs.append({"tag": tag, "bank": bank, "k": k, "inputs": [], "epoch": epoch})
            except (KeyError, ValueError) as exc:
                if strict_schema:
                    errors.append(f"malformed accelerator command at line {event.get('_line')}: {exc}")
        elif kind == "ACCEL_IN":
            try:
                tag = event["tag"]
                data = int(event["data"], 16)
            except (KeyError, ValueError) as exc:
                errors.append(f"malformed accelerator input at line {event.get('_line')}: {exc}")
            else:
                if not accel_jobs:
                    errors.append(f"accelerator input without active command at line {event.get('_line')}")
                else:
                    job = accel_jobs[0]
                    if job["tag"] != tag or job["epoch"] != epoch:
                        errors.append(f"accelerator input tag/epoch does not match active command at line {event.get('_line')}")
                    if strict_schema:
                        vector = _value_int(event.get("vector"), -1)
                        data_key = (epoch, tag, vector)
                        expected_words = input_words_pending[data_key]
                        if not expected_words:
                            errors.append(f"accelerator input has no successful descriptor memory read at line {event.get('_line')}")
                        elif expected_words.popleft() != data:
                            errors.append(f"accelerator input payload differs from independently checked DMA read at line {event.get('_line')}")
                        input_word_count[data_key] += 1
                    job["inputs"].extend(_signed(data >> (8 * lane), 8) for lane in range(4))
                    if len(job["inputs"]) == job["k"]:
                        try:
                            expected = _predict_accel_word(accel_config, job["bank"], job["k"], job["inputs"])
                            accel_predictions[tag].append({"epoch": epoch, "data": expected})
                        except ValueError as exc:
                            errors.append(f"accelerator reference model failed at line {event.get('_line')}: {exc}")
                        accel_jobs.popleft()
                    elif len(job["inputs"]) > job["k"]:
                        errors.append(f"accelerator command {tag} received excess input data at line {event.get('_line')}")
        elif kind == "ACCEL_OUT":
            tag=event.get("tag", "")
            if not commands[tag]:
                errors.append(f"accelerator output tag {tag} has no accepted command at line {event.get('_line')}")
            else:
                command=commands[tag].popleft()
                if command["epoch"] != epoch:
                    errors.append(f"accelerator output tag {tag} crossed reset epoch at line {event.get('_line')}")
                if not accel_predictions[tag]:
                    errors.append(f"accelerator output tag {tag} has no independently predicted result at line {event.get('_line')}")
                else:
                    predicted=accel_predictions[tag].popleft()
                    try:
                        observed=int(event["data"], 16)
                    except (KeyError, ValueError):
                        errors.append(f"malformed accelerator output word at line {event.get('_line')}")
                        observed=None
                    if predicted["epoch"] != epoch:
                        errors.append(f"accelerator output tag {tag} prediction crossed reset epoch at line {event.get('_line')}")
                    if observed is not None and observed != predicted["data"]:
                        errors.append(f"accelerator output mismatch tag {tag}: observed 0x{observed:08x}, expected 0x{predicted['data']:08x} at line {event.get('_line')}")
                    if observed is not None and strict_schema:
                        vector = _value_int(event.get("vector"), -1)
                        accelerator_outputs_pending[(epoch, tag, vector)].append(observed)
                    accel_outputs_checked += 1
        elif kind == "SUBMIT":
            tag=event.get("tag", "")
            if not tag:
                errors.append(f"descriptor submission without tag at line {event.get('_line')}")
            elif submitted[tag]:
                errors.append(f"duplicate live descriptor tag {tag} at line {event.get('_line')}")
            txn_id=event.get("seq", event.get("descriptor", f"{tag}:{index}"))
            committed_outputs[(epoch, tag)] = 0
            command_count[(epoch, tag)] = 0
            for key, pending in accelerator_outputs_pending.items():
                if key[0] == epoch and key[1] == tag and pending:
                    errors.append(f"new descriptor reuses tag {tag} with unaccounted accelerator output at line {event.get('_line')}")
            for key in [key for key in input_word_count if key[0] == epoch and key[1] == tag]:
                input_word_count.pop(key, None)
            for key in [key for key in translation_word_index if key[0] == epoch and key[1] == tag]:
                translation_word_index.pop(key, None)
            if strict_schema and event.get("seq") is None:
                errors.append(f"line {event.get('_line')}: descriptor submission missing sequence identity")
            descriptor = {"id": txn_id, "epoch":epoch, "line":event.get("_line"),
                          "asid":event.get("asid"), "write_count_at_submit":counts.get("MEM_REQ",0)}
            if strict_schema:
                fields = ("input_iova", "output_iova", "input_stride", "output_stride", "k", "batch", "bank", "generation")
                missing = [field for field in fields if field not in event]
                if missing:
                    errors.append(f"line {event.get('_line')}: SUBMIT missing descriptor fields " + ",".join(missing))
                try:
                    descriptor.update({"input_iova": int(event["input_iova"], 16),
                        "output_iova": int(event["output_iova"], 16),
                        "input_stride": _value_int(event["input_stride"], -1),
                        "output_stride": _value_int(event["output_stride"], -1),
                        "k": _value_int(event["k"], -1), "batch": _value_int(event["batch"], -1),
                        "bank": _value_int(event["bank"], -1), "generation": _value_int(event["generation"], -1)})
                    if descriptor["batch"] <= 0 or descriptor["k"] <= 0:
                        raise ValueError("invalid K/batch")
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"malformed accepted descriptor at line {event.get('_line')}: {exc}")
            submitted[tag].append(descriptor)
        elif kind == "COMPLETE_PUBLISH":
            tag=event.get("tag","")
            if not tag or not submitted[tag]:
                errors.append(f"completion published without accepted descriptor tag {tag} at line {event.get('_line')}")
            if pending_output_writes[tag] != 0:
                errors.append(f"completion published with {pending_output_writes[tag]} outstanding output writes for tag {tag} at line {event.get('_line')}")
            try:
                asid=int(event["asid"]); status=int(event["status"]); vectors=int(event["vectors_done"])
            except (KeyError,ValueError):
                errors.append(f"malformed completion publication metadata at line {event.get('_line')}")
                asid=status=vectors=-1
            if strict_schema and submitted[tag]:
                descriptor = submitted[tag][-1]
                committed = committed_outputs[(epoch, tag)]
                if vectors != committed:
                    errors.append(f"completion vector count {vectors} disagrees with committed output count {committed} for tag {tag} at line {event.get('_line')}")
                # An output translation fault occurs after the accelerator has
                # produced the vector, but before the payload write is issued.
                # Account for exactly that one uncommitted result only when
                # the completion carries the matching fault stage, prefix,
                # faulting vector, and output IOVA. Never silently discard
                # arbitrary pending accelerator results on an error path.
                if status == 3 and _value_int(event.get("fault_stage"), -1) == 3:
                    expected_vector = vectors
                    descriptor_output = descriptor.get("output_iova")
                    stride = descriptor.get("output_stride")
                    fault_responses = [candidate for candidate in parsed[:index]
                                       if candidate.get("kind") == "XLATE_RSP" and
                                       candidate.get("epoch") == str(epoch) and
                                       candidate.get("tag") == tag and
                                       candidate.get("asid") == descriptor.get("asid") and
                                       _value_int(candidate.get("_line"), 0) > _value_int(descriptor.get("line"), 0) and
                                       candidate.get("write") == "1" and
                                       _value_int(candidate.get("fault"), 0) != 0 and
                                       _value_int(candidate.get("vector"), -1) == expected_vector]
                    if len(fault_responses) != 1:
                        errors.append(f"output-translation completion for tag {tag} requires exactly one current-descriptor fault response for vector {expected_vector}, found {len(fault_responses)}")
                    else:
                        fault_rsp = fault_responses[0]
                        try:
                            expected_iova = descriptor_output + expected_vector * stride
                            if int(fault_rsp["iova"], 16) != expected_iova:
                                errors.append(f"output fault IOVA does not match descriptor vector {expected_vector} for tag {tag}")
                        except (KeyError, TypeError, ValueError):
                            errors.append(f"output fault response for tag {tag} lacks a valid IOVA")
                        failed_vector_outputs = accelerator_outputs_pending[(epoch, tag, expected_vector)]
                        failed_vector_writes = [candidate for candidate in parsed[:index]
                                                if candidate.get("kind") == "MEM_RSP" and
                                                candidate.get("epoch") == str(epoch) and
                                                candidate.get("tag") == tag and
                                                _value_int(candidate.get("_line"), 0) > _value_int(descriptor.get("line"), 0) and
                                                candidate.get("write") == "1" and
                                                _value_int(candidate.get("vector"), -1) == expected_vector and
                                                _value_int(candidate.get("committed"), 0) != 0]
                        if len(failed_vector_outputs) != 1:
                            errors.append(f"output fault for tag {tag} vector {expected_vector} requires exactly one pending accelerator result, found {len(failed_vector_outputs)}")
                        if failed_vector_writes:
                            errors.append(f"faulted output vector {expected_vector} for tag {tag} was committed to memory")
                        if len(failed_vector_outputs) == 1 and not failed_vector_writes:
                            failed_vector_outputs.popleft()
                    if any(queue for (pending_epoch, pending_tag, pending_vector), queue
                           in accelerator_outputs_pending.items()
                           if pending_epoch == epoch and pending_tag == tag):
                        errors.append(f"error completion for tag {tag} leaves unrelated accelerator outputs unaccounted")
                if status == 0:
                    if vectors != descriptor.get("batch"):
                        errors.append(f"successful completion reports {vectors} vectors, descriptor requires {descriptor.get('batch')} at line {event.get('_line')}")
                    if command_count[(epoch, tag)] != descriptor.get("batch"):
                        errors.append(f"successful completion command count differs from descriptor batch for tag {tag} at line {event.get('_line')}")
                    for vector in range(descriptor.get("batch", 0)):
                        expected_words = descriptor.get("k", 0) // 4
                        if input_word_count[(epoch, tag, vector)] != expected_words:
                            errors.append(f"successful completion input word count for vector {vector} is {input_word_count[(epoch, tag, vector)]}, expected {expected_words}")
            published[tag].append({"epoch":epoch,"asid":asid,"status":status,"vectors":vectors})
        elif kind == "COMPLETE":
            tag=event.get("tag", "")
            if not submitted[tag]:
                errors.append(f"completion tag {tag} has no live accepted descriptor at line {event.get('_line')}")
            else:
                txn=submitted[tag].popleft()
                if txn["epoch"] != epoch:
                    errors.append(f"completion tag {tag} crossed reset epoch at line {event.get('_line')}")
                if not published[tag]:
                    errors.append(f"completion consumed without an earlier publication for tag {tag} at line {event.get('_line')}")
                else:
                    pub=published[tag].popleft()
                    if pub["epoch"] != epoch:
                        errors.append(f"completion publication for tag {tag} crossed reset epoch at line {event.get('_line')}")
                    for field, expected in (("asid",pub["asid"]),("status",pub["status"]),("vectors_done",pub["vectors"])):
                        if _num(event,field,-1) != expected:
                            errors.append(f"completion consumption {field} disagrees with publication for tag {tag} at line {event.get('_line')}")
                if txn["asid"] is not None and event.get("asid") is not None and txn["asid"] != event.get("asid"):
                    errors.append(f"completion tag {tag} ASID mismatch at line {event.get('_line')}")
                # If the observer provides publication metadata, completion
                # cannot be consumed before all required output writes.
                pending_writes=_num(event, "pending_output_writes", 0)
                if pending_writes:
                    errors.append(f"completion tag {tag} before output writes drained at line {event.get('_line')}")
                # Completion ownership is per descriptor. Another descriptor may
                # legitimately have an output write in flight while this one is
                # consumed, so consult the tag-scoped write ledger rather than
                # blocking on unrelated traffic in the global transport queue.
                if pending_output_writes[tag] != 0:
                    errors.append(f"completion tag {tag} before accepted write response at line {event.get('_line')}")
        elif kind == "FIRMWARE_DONE":
            done=True
            done_index=index
            if strict_schema:
                if pending_cfg_commit is not None:
                    errors.append("firmware completed with an unmatched accelerator configuration commit")
                if any(translated_pending.values()):
                    errors.append("firmware completed with unused successful translation results")
                if any(input_words_pending.values()):
                    errors.append("firmware completed with DMA input words not consumed by the accelerator")
                if any(accelerator_outputs_pending.values()):
                    errors.append("firmware completed with accelerator outputs not committed to memory")
            if maintenance_active:
                errors.append("firmware completed with maintenance still active")
            if apb_setup is not None:
                errors.append("firmware completed with APB transfer missing its access phase")
            if any(submitted.values()):
                errors.append("firmware completed with live descriptors")
            if any(outstanding.values()):
                errors.append("firmware completed with outstanding transport")
            if ptw_outstanding or axi_aw or axi_w or axi_ar or expected_axi_write_events:
                errors.append("firmware completed with outstanding page-walk or host AXI transaction")
            if any(commands.values()):
                # Commands are consumed by the endpoint; an explicit command
                # completion event is required in schema v2.
                if strict_schema:
                    errors.append("firmware completed with unretired accelerator command")
            if accel_jobs or any(accel_predictions.values()):
                errors.append("firmware completed with incomplete accelerator input or unread result")
    if not done:
        errors.append("firmware completion event missing")
    if strict_schema and pending_cfg_commit is not None:
        errors.append("trace ended with an unmatched APB accelerator configuration commit")
    if strict_schema and counts.get("SUBMIT", 0) == 0:
        errors.append("no descriptor was accepted")
    if strict_schema and counts.get("COMPLETE", 0) == 0:
        errors.append("no descriptor completion was observed")
    if any(submitted.values()):
        errors.append("trace ended with live descriptors")
    if any(outstanding.values()):
        errors.append("trace ended with outstanding transaction")
    if ptw_outstanding:
        errors.append("trace ended with outstanding page-walk transaction")
    if axi_aw or axi_w:
        errors.append("trace ended with incomplete host AXI write transaction")
    if axi_ar:
        errors.append("trace ended with incomplete host AXI read transaction")
    if expected_axi_write_events:
        errors.append("trace ended without summaries for successful host AXI write beats")
    if maintenance_active:
        errors.append("trace ended with maintenance still active")
    if apb_setup is not None:
        errors.append("trace ended with APB setup missing its access phase")
    if strict_schema and any(commands.values()):
        errors.append("trace ended with unretired accelerator command")
    if strict_schema and any(published.values()):
        errors.append("trace ended with published but unconsumed descriptor completions")
    if strict_schema and accel_jobs:
        errors.append("trace ended with accelerator command missing input chunks")
    if strict_schema and any(accel_predictions.values()):
        errors.append("trace ended with unconsumed independently predicted accelerator result")
    if strict_schema and (path.parent / "firmware.hex").is_file():
        iss_checked = True
        iss_instructions = counts.get("RETIRE", 0)
        architecture_errors = check_architecture(parsed, path)
        iss_checked = not architecture_errors
        errors.extend(architecture_errors)
    return {
        "trace": path.parent.name + "/" + path.name, "status": "PASS" if not errors else "FAIL",
        "events": sum(counts.values()), "epochs": len(epochs),
        "retirements": counts.get("RETIRE", 0), "m_retires": m_retires, "apb_completions": counts.get("APB", 0),
        "translation_requests": counts.get("XLATE_REQ", 0), "memory_requests": counts.get("MEM_REQ", 0),
        "submissions": counts.get("SUBMIT", 0),
        "accelerator_commands": counts.get("ACCEL_CMD", 0), "completions": counts.get("COMPLETE", 0),
        "maintenance_operations": maintenance_count,
        "iss_status": "PASS" if iss_checked else "FAIL" if iss_instructions else "NOT_RUN",
        "iss_instructions": iss_instructions, "accelerator_outputs_checked": accel_outputs_checked,
        "trace_sha256": _sha256(path), "firmware_sha256": _sha256(path.parent / "firmware.hex"),
        "observer_build_id": build_name or "unknown",
        "data_sha256": _sha256(path.parent / "data.hex"),
        "manifest_sha256": _sha256(ROOT / "integration/protected_offload/coverage/compute_crossover_manifest.json"),
        "checker_sha256": _sha256(Path(__file__)), "source_sha256": _source_fingerprint(),
        "reset_canceled_transactions": len(canceled),
        "errors": "; ".join(errors) or "none",
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("traces", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict-schema", action="store_true")
    args=parser.parse_args()
    rows=[check(path, strict_schema=args.strict_schema) for path in args.traces]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", newline="") as handle:
            writer=csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
    passed=sum(row["status"] == "PASS" for row in rows)
    print(f"Crossover trace model: {passed} / {len(rows)} PASS")
    raise SystemExit(passed != len(rows))


if __name__ == "__main__":
    main()
