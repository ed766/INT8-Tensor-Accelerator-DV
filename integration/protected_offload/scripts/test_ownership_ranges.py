#!/usr/bin/env python3
"""Unit checks for trace-derived, line-rounded DMA ownership ranges."""
import unittest
from pathlib import Path
from unittest.mock import patch

from ownership_ranges import descriptor_physical_ranges, physical_access_owned


class OwnershipRangeTests(unittest.TestCase):
    def test_architectural_payload_encoding_is_explicit_hex(self):
        from generate_crossover_cross_coverage import num
        self.assertEqual(num({"mem_addr": "10000000"}, "mem_addr"), 0x10000000)
        self.assertEqual(num({"rd_data": "12345678"}, "rd_data"), 0x12345678)
        self.assertEqual(num({"cycle": "12345678"}, "cycle"), 12345678)

    def test_ownership_cross_witness_orders_mapping_and_owner_events(self):
        from generate_crossover_cross_coverage import collect
        submitted = dict(self.submit, cycle="1")
        mappings = [dict(event, cycle=str(int(event["eid"]))) for event in self.events]
        owner = dict(kind="OWNERSHIP", eid="6", cycle="6", epoch="0", count="1", active_tag="7")
        access = dict(kind="OWNED_CPU_ACCESS", eid="7", cycle="7", epoch="0", active_tag="7", addr="10008000")
        with patch("generate_crossover_cross_coverage.load_events", return_value=[submitted, *mappings, owner, access]):
            rows = collect(Path("unused.trace"))
        witness = next(row[2] for row in rows if row[0] == "cache_ownership_x_cpu_access")
        self.assertEqual([event["eid"] for event in witness], ["1", "2", "3", "4", "5", "6", "7"])

    def setUp(self):
        self.submit = {
            "kind": "SUBMIT", "eid": "1", "epoch": "0", "tag": "7", "asid": "3",
            "input_iova": "80001004", "input_stride": "64", "k": "8", "batch": "1",
            "output_iova": "8000401c", "output_stride": "64",
        }
        self.events = [
            {"kind": "XLATE_REQ", "eid": "2", "epoch": "0", "tag": "7", "asid": "3",
             "txn": "0", "iova": "80001004"},
            {"kind": "XLATE_RSP", "eid": "3", "epoch": "0", "tag": "7", "asid": "3",
             "txn": "0", "iova": "80001004", "paddr": "10000004", "fault": "0"},
            {"kind": "XLATE_REQ", "eid": "4", "epoch": "0", "tag": "7", "asid": "3",
             "txn": "1", "iova": "8000401c"},
            {"kind": "XLATE_RSP", "eid": "5", "epoch": "0", "tag": "7", "asid": "3",
             "txn": "1", "iova": "8000401c", "paddr": "1000401c", "fault": "0"},
        ]

    def test_physical_ranges_preserve_page_offsets_and_round_cache_lines(self):
        ranges, evidence = descriptor_physical_ranges(self.submit, self.events)
        self.assertEqual(ranges, [(0x10000000, 0x1000001f), (0x10004000, 0x1000401f)])
        self.assertEqual([event["eid"] for event in evidence], ["2", "3", "4", "5"])

    def test_hex_address_membership_uses_physical_range(self):
        ranges, _ = descriptor_physical_ranges(self.submit, self.events)
        self.assertTrue(physical_access_owned(int("10000004", 16), ranges))
        self.assertTrue(physical_access_owned(int("1000401f", 16), ranges))
        self.assertFalse(physical_access_owned(int("10004020", 16), ranges))

    def test_other_asid_or_epoch_cannot_supply_mapping(self):
        altered = [dict(event) for event in self.events]
        altered[1]["asid"] = "4"
        ranges, evidence = descriptor_physical_ranges(self.submit, altered)
        self.assertIsNone(ranges)
        self.assertEqual(evidence, [])

    def test_malformed_page_offset_mapping_is_rejected(self):
        altered = [dict(event) for event in self.events]
        altered[1]["paddr"] = "10000100"
        ranges, _ = descriptor_physical_ranges(self.submit, altered)
        self.assertIsNone(ranges)

    def test_reused_tag_cannot_supply_old_translation(self):
        reused = dict(self.submit, eid="10")
        ranges, evidence = descriptor_physical_ranges(reused, self.events)
        self.assertIsNone(ranges)
        self.assertEqual(evidence, [])

    def test_later_tag_reuse_cannot_replace_live_mapping(self):
        events = self.events + [
            {"kind": "COMPLETE_PUBLISH", "eid": "6", "epoch": "0", "tag": "7", "asid": "3"},
            {"kind": "SUBMIT", "eid": "7", "epoch": "0", "tag": "7", "asid": "3"},
            {"kind": "XLATE_REQ", "eid": "8", "epoch": "0", "tag": "7", "asid": "3", "txn": "0", "iova": "80001004"},
            {"kind": "XLATE_RSP", "eid": "9", "epoch": "0", "tag": "7", "asid": "3", "txn": "0", "iova": "80001004", "paddr": "10008004", "fault": "0"},
        ]
        ranges, _ = descriptor_physical_ranges(self.submit, events)
        self.assertEqual(ranges[0], (0x10000000, 0x1000001f))

    def test_conflicting_mapping_within_one_lifetime_is_not_credited(self):
        events = self.events + [
            {"kind": "XLATE_REQ", "eid": "6", "epoch": "0", "tag": "7", "asid": "3", "txn": "2", "iova": "80001004"},
            {"kind": "XLATE_RSP", "eid": "7", "epoch": "0", "tag": "7", "asid": "3", "txn": "2", "iova": "80001004", "paddr": "10008004", "fault": "0"},
        ]
        ranges, _ = descriptor_physical_ranges(self.submit, events)
        self.assertIsNone(ranges)


if __name__ == "__main__":
    unittest.main()
