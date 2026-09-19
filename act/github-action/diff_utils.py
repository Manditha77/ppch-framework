"""Determines which lines in a file's HEAD version are new or modified
relative to its BASE version, using Python's difflib - no GitHub PR-files API
call needed, just the two raw file contents (already fetchable via
fetch_source.py). Used to scope the ILP refactoring target to the method(s)
a PR actually touched, rather than the single most complex method anywhere
in the whole file (which is often unrelated to the PR's real changes)."""

import difflib


def changed_line_numbers(base_text: str, head_text: str) -> set:
    """Return the set of 1-indexed line numbers in `head_text` that are new
    or modified compared to `base_text` (i.e. lines introduced or changed by
    this PR). Uses SequenceMatcher's opcodes ('replace'/'insert' blocks on
    the head side); unchanged ('equal') and deleted ('delete', head-side
    empty) lines are excluded."""
    base_lines = base_text.splitlines()
    head_lines = head_text.splitlines()
    matcher = difflib.SequenceMatcher(a=base_lines, b=head_lines, autojunk=False)

    changed = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            # j1/j2 are 0-indexed, exclusive-end; convert to 1-indexed inclusive
            changed.update(range(j1 + 1, j2 + 1))
    return changed