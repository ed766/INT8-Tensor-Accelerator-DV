#!/usr/bin/env python3
"""Checker sensitivity test for exact AES job output accounting."""
from __future__ import annotations

import unittest

from check_compute_host_evidence import aes_matches, aes_job_matches, destination_read_error, return_stream_error, final_aes_destination_words
from dma_golden_model import AES_KEY, encrypt_block


plain = [0x0123456789ABCDEF, 0xFEDCBA9876543210]
expected = encrypt_block(AES_KEY, plain)
inputs = [{"kind": "CHIPLET_IN", "cycle": "11", "data": f"{plain[0]:016x}"},
          {"kind": "CHIPLET_IN", "cycle": "12", "data": f"{plain[1]:016x}"}]
valid = inputs + [
    {"kind": "CHIPLET_DIE_B_OUT", "cycle": "14", "data": f"{expected[0]:016x}"},
    {"kind": "CHIPLET_DIE_B_OUT", "cycle": "15", "data": f"{expected[1]:016x}"},
]
assert aes_matches(valid, [(10, 20)])[1:] == (2, "")
assert aes_matches(valid + [{"kind": "CHIPLET_DIE_B_OUT", "cycle": "21", "data": "deadbeefcafefeed"}],
                   [(10, 20)])[2] != ""
assert aes_matches(valid + [{"kind": "CHIPLET_DIE_B_OUT", "cycle": "13", "data": "deadbeefcafefeed"}],
                   [(10, 20)])[2] != ""
print("compute-host AES exact-output checker: PASS")


class HostDestinationTests(unittest.TestCase):
    def jobs(self):
        return ([dict(kind="CHIPLET_EVT",busy="1",epoch="0",eid="1")]+
                [dict(event,epoch="0") for event in valid]+
                [dict(kind="CHIPLET_EVT",busy="0",epoch="0",eid="7")])

    def test_aes_job_exact_words_pass(self):
        self.assertEqual(aes_job_matches(self.jobs()),(2,2,""))

    def test_final_destination_uses_last_job_not_concatenated_jobs(self):
        rows = self.jobs() + self.jobs()
        self.assertEqual(final_aes_destination_words(rows), expected)

    def test_final_destination_does_not_use_pre_reset_plaintext(self):
        rows = self.jobs() + [dict(kind="RESET_ASSERT", epoch="1")]
        self.assertEqual(final_aes_destination_words(rows), [])
        rows.extend(dict(event, epoch="1") for event in self.jobs())
        self.assertEqual(final_aes_destination_words(rows), expected)

    def test_aes_output_cannot_borrow_another_epoch(self):
        rows=self.jobs()
        rows[3]["epoch"]="1"
        self.assertIn("owning AES job",aes_job_matches(rows)[2])

    def test_aes_output_cannot_borrow_a_prior_job(self):
        rows=self.jobs()
        second=[dict(kind="CHIPLET_EVT",busy="1",epoch="0",eid="8")]
        second.extend(dict(event,epoch="0") for event in inputs)
        rows.pop(4)
        second.append(dict(kind="CHIPLET_DIE_B_OUT",epoch="0",data=f"{expected[1]:016x}"))
        self.assertIn("job/block/word mismatch",aes_job_matches(rows+second)[2])

    def test_aes_reset_cancels_partial_block_not_future_output(self):
        rows=self.jobs()[:2]+[dict(kind="RESET_ASSERT",epoch="1",eid="3")]
        self.assertEqual(aes_job_matches(rows),(0,0,""))
        rows.append(dict(kind="CHIPLET_DIE_B_OUT",epoch="1",data=f"{expected[0]:016x}"))
        self.assertIn("owning AES job",aes_job_matches(rows)[2])
    def trace(self):
        return [
            {"kind": "APB", "write": "1", "addr": "50000020", "wdata": "00000020"},
            {"kind": "APB", "write": "1", "addr": "50000024", "wdata": "00000001"},
            {"kind": "APB", "write": "1", "addr": "50000058", "wdata": "00000001"},
            {"kind": "RETIRE", "mem_rmask": "f", "mem_addr": "50000028", "mem_rdata": "12345678"},
            {"kind": "RETIRE", "mem_rmask": "f", "mem_addr": "5000002c", "mem_rdata": "9abcdef0"},
        ]

    def test_actual_memory_readback_matches(self):
        self.assertEqual(destination_read_error(self.trace(), [0x9abcdef012345678]), "")

    def test_wrong_memory_data_is_rejected(self):
        self.assertIn("readback mismatch", destination_read_error(self.trace(), [0x9abcdef012345679]))

    def test_missing_memory_readback_is_rejected(self):
        self.assertIn("readback mismatch", destination_read_error(self.trace()[:-1], [0x9abcdef012345678]))

    def test_wrong_destination_address_is_rejected(self):
        trace = self.trace()
        trace[0]["wdata"] = "00000021"
        self.assertIn("readback mismatch", destination_read_error(trace, [0x9abcdef012345678]))

    def test_exact_return_stream_including_zero(self):
        trace = [{"kind": "CHIPLET_DIE_B_OUT", "data": "0000000000000000"},
                 {"kind": "CHIPLET_OUT", "data": "0000000000000000"}]
        self.assertEqual(return_stream_error(trace, False), "")
        self.assertNotEqual(return_stream_error(trace[:1], False), "")

    def test_return_cannot_cross_reset_epoch(self):
        trace = [dict(kind="CHIPLET_DIE_B_OUT", epoch="0", data="1"),
                 dict(kind="RESET_ASSERT", epoch="1"),
                 dict(kind="CHIPLET_OUT", epoch="1", data="1")]
        self.assertNotEqual(return_stream_error(trace, False), "")

    def test_return_cannot_precede_production(self):
        trace = [dict(kind="CHIPLET_OUT", epoch="0", data="1"),
                 dict(kind="CHIPLET_DIE_B_OUT", epoch="0", data="1")]
        self.assertNotEqual(return_stream_error(trace, False), "")

    def test_destination_read_pair_cannot_cross_reset(self):
        trace = self.trace()
        trace.insert(4, dict(kind="RESET_ASSERT", epoch="1"))
        self.assertNotEqual(destination_read_error(trace, [0x9abcdef012345678]), "")

    def test_return_reorder_duplicate_and_abort_are_rejected(self):
        produced = [{"kind": "CHIPLET_DIE_B_OUT", "data": f"{value:016x}"} for value in (1, 2)]
        for values in ((2, 1), (1, 1, 2), (1,)):
            returned = [{"kind": "CHIPLET_OUT", "data": f"{value:016x}"} for value in values]
            self.assertNotEqual(return_stream_error(produced + returned, False), "")
        self.assertNotEqual(return_stream_error(produced + [{"kind": "CHIPLET_OUT", "data": "1"}], True), "")


if __name__ == "__main__":
    unittest.main()
