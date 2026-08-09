#!/usr/bin/env python3
"""Check local Markdown links and reject machine-specific report paths."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    failures: list[str] = []
    for document in documents:
        text = document.read_text()
        if "/home/" in text or "/mnt/c/" in text:
            failures.append(f"machine-specific path: {document.relative_to(ROOT)}")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (document.parent / clean).resolve().exists():
                failures.append(f"broken link in {document.relative_to(ROOT)}: {target}")
    if failures:
        print("\n".join(f"DOC_FAIL|{failure}" for failure in failures))
        return 1
    print(f"DOC_CHECK_PASS|documents={len(documents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
