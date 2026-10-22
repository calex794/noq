#!/usr/bin/env python3
"""Conservative PR-only selector for non-required CI work.

Only unrelated workflow YAML and the read-only CI audit scripts can use the
small matrix. Every ambiguity falls back to all tests. Required checks always
run regardless of this selector.
"""
from __future__ import annotations

import os
from pathlib import PurePosixPath
import subprocess

SAFE_AUDIT_SCRIPTS = frozenset({
    ".github/scripts/ci_impact_graph.py",
    ".github/scripts/test_ci_impact_graph.py",
})
FULL_MATRIX_WORKFLOWS = frozenset({
    ".github/workflows/ci.yml",
    ".github/workflows/tests.yaml",
})

def full_matrix_needed(paths: list[str] | None) -> bool:
    """True unless all PR changes are from a small explicitly safe group."""
    if not paths:
        return True
    for path in paths:
        if path in SAFE_AUDIT_SCRIPTS:
            continue
        parts = PurePosixPath(path).parts
        if (len(parts) == 3 and parts[:2] == (".github", "workflows")
                and path.endswith((".yml", ".yaml"))
                and path not in FULL_MATRIX_WORKFLOWS):
            continue
        return True
    return False

def changed_paths_from_pr_merge() -> list[str] | None:
    """Use both parents of the checked-out synthetic PR merge, or fail open."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    base_sha = os.environ.get("PR_BASE_SHA", "")
    if not base_sha:
        return None
    parents = subprocess.check_output(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        stderr=subprocess.DEVNULL,
    ).decode("ascii").strip().split()
    if len(parents) != 3 or parents[1] != base_sha:
        return None
    diff = subprocess.check_output(
        ["git", "diff", "--no-renames", "--name-only", "-z", "HEAD^1", "HEAD"],
        stderr=subprocess.DEVNULL,
    )
    names = diff.split(b"\0")
    if names[-1:] == [b""]:
        names.pop()
    return [name.decode("utf-8") for name in names]

def main() -> None:
    try:
        full = full_matrix_needed(changed_paths_from_pr_merge())
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        full = True
    print(f"extended={'true' if full else 'false'}")

if __name__ == "__main__":
    main()
