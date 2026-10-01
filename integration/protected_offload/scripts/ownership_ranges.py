"""Independent IOVA-to-physical ownership range reconstruction."""
from __future__ import annotations


def hx(event: dict[str, str], key: str) -> int:
    value = event.get(key, "")
    if not value:
        raise ValueError(f"missing hexadecimal observer field {key}")
    return int(value, 16)


def descriptor_physical_ranges(submit: dict[str, str], events: list[dict[str, str]]):
    """Return line-rounded PA ranges and the XLATE request/response evidence.

    No PTE shadow, requested plusarg, or scenario label is used: page mappings
    come only from successful request/response pairs in the same trace epoch,
    tag, and ASID.
    """
    epoch, tag, asid = (submit.get("epoch"), submit.get("tag"), submit.get("asid"))
    submit_eid = int(submit["eid"])
    end_eid = next((int(event["eid"]) for event in events
                    if event.get("kind") in ("COMPLETE_PUBLISH", "COMPLETE") and
                    event.get("epoch") == epoch and event.get("tag") == tag and
                    event.get("asid") == asid and int(event.get("eid", "0")) > submit_eid), None)
    def in_lifetime(event: dict[str, str]) -> bool:
        eid = int(event.get("eid", "0"))
        return submit_eid < eid and (end_eid is None or eid < end_eid)

    reqs: dict[str, dict[str, str]] = {}
    page_map: dict[int, int] = {}
    evidence: list[dict[str, str]] = []
    for response in sorted(events, key=lambda event: int(event.get("eid", "0"))):
        if not in_lifetime(response):
            continue
        if (response.get("kind") == "XLATE_REQ" and response.get("epoch") == epoch and
                response.get("tag") == tag and response.get("asid") == asid):
            reqs[response.get("txn", "")] = response
            continue
        if (response.get("kind") != "XLATE_RSP" or response.get("epoch") != epoch or
                response.get("tag") != tag or response.get("asid") != asid or
                response.get("fault") != "0"):
            continue
        request = reqs.pop(response.get("txn", ""), None)
        if request is None or request.get("iova") != response.get("iova"):
            continue
        iova_page = hx(request, "iova") & ~0xfff
        paddr = hx(response, "paddr")
        # Sv32 page offsets are preserved. Refuse malformed evidence instead
        # of silently using a rounded mapping that could bless the wrong line.
        if (hx(request, "iova") & 0xfff) != (paddr & 0xfff):
            continue
        pa_page = paddr & ~0xfff
        if iova_page in page_map and page_map[iova_page] != pa_page:
            return None, []
        page_map[iova_page] = pa_page
        evidence.extend((request, response))

    ranges: list[tuple[int, int]] = []
    for base_field, stride_field, length, vectors in (
        ("input_iova", "input_stride", int(submit.get("k", "0")), int(submit.get("batch", "0"))),
        ("output_iova", "output_stride", 4, int(submit.get("batch", "0"))),
    ):
        base = hx(submit, base_field)
        stride = int(submit.get(stride_field, "0"))
        if length <= 0 or vectors <= 0:
            return None, []
        for vector in range(vectors):
            lo_iova = (base + vector * stride) & ~31
            hi_iova = (base + vector * stride + length - 1) | 31
            page = lo_iova & ~0xfff
            final_page = hi_iova & ~0xfff
            while page <= final_page:
                pa_page = page_map.get(page)
                if pa_page is None:
                    return None, []
                lo = max(lo_iova, page)
                hi = min(hi_iova, page + 0xfff)
                ranges.append((pa_page + (lo - page), pa_page + (hi - page)))
                page += 0x1000
    # Deduplicate request/response witnesses while preserving trace order.
    unique = {event.get("eid"): event for event in evidence}
    return ranges, sorted(unique.values(), key=lambda event: int(event.get("eid", "0")))


def physical_access_owned(address: int, ranges: list[tuple[int, int]]) -> bool:
    line = address & ~31
    return any(lo <= line <= hi for lo, hi in ranges)
