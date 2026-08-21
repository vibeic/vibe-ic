#!/usr/bin/env python3
"""sha -> the rescue ref that ACTUALLY contains it, built by scanning the refs themselves.

The previous version was a hand-written clone -> ref table, and it was wrong for exactly one
row: a commit on .112 whose rescue ref was pushed separately, so the table named the clone's
usual anchor and the sha was not in it. jharv3 hit the identical failure from the other side.
The lesson is not "fix that row" -- it is that an annotation derived from a lookup table can
disagree with the world, while one derived from the measurement cannot. So this indexes the
real refs: every ref's tip and every ref's parents. A row can then only ever name a ref that
does contain its sha.
"""
import subprocess

R = "/home/reyerchu/vibe-ic"

def _run(*a):
    return subprocess.run(["git", "-C", R, *a], capture_output=True, text=True).stdout

_INDEX = {}
for _ref in _run("for-each-ref", "--format=%(refname:short)",
                 "refs/remotes/origin/harvest/rescue-*").split():
    _tip = _run("rev-parse", "-q", "--verify", _ref).strip()
    _short = _ref.replace("origin/", "", 1)
    if _tip:
        _INDEX.setdefault(_tip, (_short, _tip))
    for _l in _run("cat-file", "-p", _ref).splitlines():
        if _l.startswith("parent "):
            _INDEX.setdefault(_l.split()[1], (_short, _tip))

def rescue_note(host, clone, head):
    """host and clone are accepted for call-compatibility and deliberately not used: what keeps a
    commit alive is which ref contains it, not which machine or clone it came from."""
    hit = _INDEX.get(head)
    if not hit:
        return (" It has NOT been preserved anywhere; put it on a branch before removing the "
                "directory.")
    ref, anchor = hit
    how = ("IS the tip of" if anchor == head else "is a parent of")
    return (" It IS preserved: commit %s %s %s on origin, so `git fetch origin %s && "
            "git checkout %s` restores it even if the directory goes."
            % (head[:11], how, ref, ref, head[:11]))
