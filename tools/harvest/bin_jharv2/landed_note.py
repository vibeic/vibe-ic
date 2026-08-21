#!/usr/bin/env python3
"""Per-row: WHICH form of LANDED this is, and what the worktree held before.

jharv3 generalised the reset-onto-main case: any head that is an ANCESTOR of main collapses the
owned set to empty, so every content check passes trivially. The row is then TRUE and says
nothing about what the directory used to hold. Written PER ROW from that row's own measurement —
jharv3 caught themselves applying one explanation to a population they had not checked row by
row, and the same trap is available here.
"""
import os

_M = {}
_p = "/home/reyerchu/_shb/lf_all.tsv"
if os.path.exists(_p):
    for _l in open(_p, encoding="utf-8", errors="replace").read().splitlines():
        f = _l.split("\t")
        if len(f) >= 4:
            _M[f[0]] = (f[1], f[2], f[3])

def landed_note(wt):
    hit = _M.get(wt)
    if not hit:
        return ""
    form, nown, prior = hit
    if form.startswith("STRONG"):
        s = (" [LANDED, strong form: it owns %s file(s) and every one is byte-identical to main, "
             "so the verdict rests on file-by-file identity." % nown)
    elif form == "EMPTY_head_IS_main":
        s = (" [LANDED, empty form: its head IS current main, so it owns nothing and every content "
             "check passes trivially. This says the DIRECTORY now holds main — not that any branch's "
             "work landed.")
    elif form == "EMPTY_head_ancestor_of_main":
        s = (" [LANDED, empty form: its head is already contained in main, so it owns nothing and "
             "every content check passes trivially. This says the DIRECTORY holds a state main has "
             "— not that any branch's work landed.")
    else:
        s = " [LANDED form: %s." % form
    if prior and prior != "no-prior-heads-recorded":
        if "ORPHANED_WORK" in prior:
            s += (" Its reflog holds earlier head(s) that owned files differing from main and were "
                  "on no ref: %s. Those are preserved now — see the harvest/rescue-*priorheads* "
                  "refs — but they were unpreserved work sitting behind this row." % prior)
        else:
            s += " Earlier heads in its reflog, all accounted for: %s." % prior
    else:
        s += " Its reflog records no earlier head, so nothing was displaced."
    return s + "]"
