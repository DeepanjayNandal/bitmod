"""Identify the code that produced a result, not just the last commit.

Every artifact written during the calibration work recorded the same commit
hash — 3229d6dc — regardless of what was in the working tree, because none of
the code being measured was committed while it was being measured. A hash that
is identical across runs of materially different code cannot tie a number to the
thing that produced it, which is the only job it has.

So the tree is fingerprinted alongside it. Two runs sharing a commit *and* a
tree hash ran the same code. Two runs with different tree hashes did not,
whatever the commit says.

Every tool in this directory that writes a result file records this.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess


def _git(*args: str) -> str:
    git = shutil.which("git") or "git"
    return subprocess.run(  # noqa: S603
        [git, *args], capture_output=True, text=True, check=False
    ).stdout


def provenance() -> dict:
    """Commit, working-tree fingerprint, and whether anything was uncommitted."""
    diff = _git("diff", "HEAD")
    untracked = _git("ls-files", "--others", "--exclude-standard")
    return {
        "commit": _git("rev-parse", "HEAD").strip(),
        "tree_sha256": hashlib.sha256((diff + untracked).encode()).hexdigest()[:16],
        "dirty": bool(diff.strip() or untracked.strip()),
        "untracked_files": len([line for line in untracked.splitlines() if line]),
    }
