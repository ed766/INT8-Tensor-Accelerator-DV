"""The clean-checkout audit must preserve the user's branch and real index."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from run_clean_checkout import git, snapshot


class CleanCheckoutTest(unittest.TestCase):
    def test_snapshot_includes_sources_not_ignored_builds_and_preserves_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            git(source, "config", "user.name", "Fixture")
            git(source, "config", "user.email", "fixture@localhost")
            (source / ".gitignore").write_text("build/\n")
            (source / "rtl.sv").write_text("initial-version\n")
            git(source, "add", "--all")
            git(source, "commit", "-qm", "Fixture baseline")
            (source / "rtl.sv").write_text("staged-version\n")
            git(source, "add", "rtl.sv")
            (source / "rtl.sv").write_text("working-version\n")
            (source / "new_driver.py").write_text("new-source\n")
            (source / "build").mkdir()
            (source / "build/stale.trace").write_text("must-not-be-reused\n")
            head = git(source, "rev-parse", "HEAD")
            index_path = source / ".git/index"
            index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
            checkout = root / "checkout"
            result = snapshot(source, checkout)
            self.assertEqual(result["source_head"], head)
            self.assertEqual(git(source, "rev-parse", "HEAD"), head)
            self.assertEqual(hashlib.sha256(index_path.read_bytes()).hexdigest(), index_hash)
            self.assertEqual(git(source, "show", ":rtl.sv"), "staged-version")
            self.assertEqual((checkout / "rtl.sv").read_text(), "working-version\n")
            self.assertEqual((checkout / "new_driver.py").read_text(), "new-source\n")
            self.assertFalse((checkout / "build").exists())
            self.assertEqual(git(checkout, "status", "--porcelain=v1"), "")


if __name__ == "__main__":
    unittest.main()
