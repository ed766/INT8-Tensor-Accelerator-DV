#!/usr/bin/env python3
"""Negative controls for execution-bound native coverage reuse."""
import tempfile
import unittest
from pathlib import Path

from coverage_provenance import sha256, validate_manifest, write_manifest


class CoverageProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.case = self.root / "case"
        self.case.mkdir()
        self.source = self.root / "dut.sv"
        self.source.write_text("module dut; endmodule\n")
        for name in ("firmware.elf", "crossover.trace", "integration_coverage.dat"):
            (self.case / name).write_text(name + "\n")
        self.version = "Verilator 5.049 pinned-test"
        self.row = {"scenario": "case", "source_build_id": "build-a",
                    "elf_sha256": sha256(self.case / "firmware.elf")}
        self.write()

    def write(self, exit_code=0):
        write_manifest(self.root, self.case, [self.source], self.version,
                       "build-a", "case", exit_code)

    def check(self):
        validate_manifest(self.root, self.case, self.row, self.version)

    def test_valid_control(self):
        self.check()

    def test_old_database_has_no_provenance(self):
        (self.case / "coverage_provenance.json").unlink()
        with self.assertRaisesRegex(ValueError, "no execution-bound"):
            self.check()

    def test_each_artifact_is_bound(self):
        for name in ("firmware.elf", "crossover.trace", "integration_coverage.dat"):
            with self.subTest(name=name):
                original = (self.case / name).read_bytes()
                (self.case / name).write_bytes(b"unrelated run")
                with self.assertRaisesRegex(ValueError, "stale or altered"):
                    self.check()
                (self.case / name).write_bytes(original)

    def test_changed_source(self):
        self.source.write_text("module changed; endmodule\n")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.check()

    def test_mixed_simulator(self):
        self.version = "Verilator 5.020"
        with self.assertRaisesRegex(ValueError, "simulator version"):
            self.check()

    def test_failed_execution(self):
        self.write(exit_code=1)
        with self.assertRaisesRegex(ValueError, "failing simulation"):
            self.check()

    def test_mixed_model_row(self):
        self.row["source_build_id"] = "build-b"
        with self.assertRaisesRegex(ValueError, "source identities"):
            self.check()


if __name__ == "__main__":
    unittest.main()
