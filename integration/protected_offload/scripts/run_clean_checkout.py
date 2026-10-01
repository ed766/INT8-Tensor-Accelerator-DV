#!/usr/bin/env python3
"""Execute strict closure in isolated Git snapshots without touching user indexes.

Snapshots are local audit objects, not release commits or publication evidence.
Only external tool caches may be shared; DUT builds and traces are regenerated.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def git(root, *args, env=None):
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   env=env, text=True).strip()


def snapshot(source, destination):
    before = git(source, "status", "--porcelain=v1")
    head = git(source, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        git(source, "read-tree", "HEAD", env=env)
        git(source, "add", "--all", env=env)
        tree = git(source, "write-tree", env=env)
        commit = subprocess.check_output(
            ["git", "-C", str(source), "commit-tree", tree, "-p", head],
            input="Local clean-checkout verification snapshot\n", text=True,
            env=dict(env, GIT_AUTHOR_NAME="Verification Audit",
                     GIT_AUTHOR_EMAIL="audit@localhost",
                     GIT_COMMITTER_NAME="Verification Audit",
                     GIT_COMMITTER_EMAIL="audit@localhost")).strip()
    subprocess.run(["git", "clone", "--no-hardlinks", "--no-checkout",
                    str(source), str(destination)], check=True)
    git(destination, "fetch", str(source), commit)
    git(destination, "checkout", "--detach", commit)
    if git(destination, "status", "--porcelain=v1"):
        raise RuntimeError("snapshot checkout is not clean")
    if git(source, "rev-parse", "HEAD") != head or git(source, "status", "--porcelain=v1") != before:
        raise RuntimeError("source changed while snapshotting; audit cannot proceed")
    return {"source_head": head, "snapshot_commit": commit, "snapshot_tree": tree}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    audit = Path(tempfile.mkdtemp(prefix="clean-checkout-", dir=ROOT / "build"))
    sources = (ROOT.parent / "ucie_chiplet_soc", ROOT)
    records = {source.name: snapshot(source, audit / source.name) for source in sources}
    chiplet = audit / "ucie_chiplet_soc"
    # The cache contains pinned third-party tools only, never DUT sources/traces.
    chiplet_build = chiplet / "chiplet_extension/build"
    chiplet_build.mkdir(parents=True, exist_ok=True)
    for name in ("external_riscv_tools", "rv32_toolchain"):
        cache = sources[0] / "chiplet_extension/build" / name
        if not cache.is_dir():
            raise SystemExit(f"required tool cache missing: {name}")
        (chiplet_build / name).symlink_to(cache, target_is_directory=True)
    records["status"] = "NOT_RUN"
    manifest = audit / "audit.json"
    manifest.write_text(json.dumps(records, indent=2) + "\n")
    print(f"CLEAN_CHECKOUT_PREPARED|directory={audit.relative_to(ROOT)}", flush=True)
    if args.prepare_only:
        return 0
    accelerator = audit / ROOT.name
    env = dict(os.environ, CHIPLET_ROOT=str(chiplet),
               OSS_CAD_SUITE=str(chiplet_build / "external_riscv_tools/oss-cad-suite/oss-cad-suite"))
    # Match CI: system Verilator brings up components; coverage and external
    # oracle targets source their pinned tool environment themselves.
    command = ["make", "compute-crossover-release-check", f"PYTHON={sys.executable}"]
    with (audit / "closure.log").open("w") as log:
        result = subprocess.run(command, cwd=accelerator, env=env,
                                stdout=log, stderr=subprocess.STDOUT)
    records["status"] = "PASS" if result.returncode == 0 else "FAIL"
    records["exit_code"] = result.returncode
    records["post_run_diff"] = git(accelerator, "diff", "--name-only")
    manifest.write_text(json.dumps(records, indent=2) + "\n")
    print(f"CLEAN_CHECKOUT_CLOSURE|status={records['status']}|exit={result.returncode}", flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
