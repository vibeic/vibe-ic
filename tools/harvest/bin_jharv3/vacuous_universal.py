#!/usr/bin/env python3
"""A verdict that authorises deletion may not rest on a universal over an EMPTY SET.

    usage: vacuous_universal.py [--file F ...]      (default: the joined view + all
                                                     three shard files, read from REF)
    env:   VIBEIC_REPO, VIBEIC_REF
           --self-test    prove each guarantee catches something only it catches

WHY THIS EXISTS.

"all 0 file(s) this tree changed hash-match main byte for byte" is TRUE of every
empty set. It reads like a measurement and is a tautology, and 20 rows of
verdicts_joined.tsv -- the file a downstream executor actually reads -- carry it as
the sole basis for LANDED, which means "already on main, safe to delete".

For two of them the statement is not merely vacuous, it is FALSE:

    /home/reyerchu/_jd3               owns 3 files, all 3 differ from main, +212 lines
    /home/reyerchu/AI_IC_design/wt_jwire2   owns 9 files, all 9 differ,     +1683 lines

and for a third, /home/reyerchu/_a1456, the committed tree really is empty but the
directory holds 1 uncommitted edit that is on no ref anywhere -- so "0 files changed"
is true of the wrong question. All three are RECOVER in verdicts_shard_c.tsv, with
sha256 evidence that re-hashes correctly against current main.

The same shape appears twice more in this job: an A4 duplicate rule that would make
every worktree collide if the owned-set were allowed to be empty, and a negative
control that "passed" a file nothing had corrupted. A check over nothing passes.

SECOND GUARANTEE: staleness. All 44 deletion-bound rows of the joined view cite main
a00f53f20, which is not current. Judging deletion against a main that has moved is
the exact mistake the shard re-judgement was ordered to correct.

This gate does not delete or rewrite anything. It reports.
"""
import os, re, subprocess, sys

DELETION_BOUND = {"LANDED", "ABANDON"}
# a universal quantifier whose domain is stated to be empty
VACUOUS = re.compile(r"\ball\s+0\s+(?:file|path|entry)\(?s?\)?\b", re.I)
MAIN_CITE = re.compile(r"\bmain\s+([0-9a-f]{9,40})\b")
# THIRD GUARANTEE: deletion destroys untracked bytes, which are on no commit and on no
# ref. The sweep behind these rows ran `git status --porcelain -uno`, which EXCLUDES
# untracked files, so "the working tree is clean" was measured over a domain that
# cannot contain them. A deletion-bound row must therefore ACCOUNT for untracked
# content -- either state it was checked, or state it was not. Silence is the same
# unexamined-input failure as the empty-set universal, and it is what produced the one
# wrong verdict in shard C: two identical HEAD trees, two different untracked handoffs.
UNTRACKED = re.compile(r"untracked", re.I)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("VIBEIC_REPO") or subprocess.run(
    ["git", "-C", HERE, "rev-parse", "--show-toplevel"],
    capture_output=True, text=True).stdout.strip()
REF = os.environ.get("VIBEIC_REF", "origin/harvest/worktree-triage-jharvest")
DEFAULT = ["tools/harvest/verdicts_joined.tsv",
           "tools/harvest/verdicts_shard_a.tsv",
           "tools/harvest/verdicts_shard_b.tsv",
           "tools/harvest/verdicts_shard_c.tsv"]


def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True)


def current_main():
    p = git("rev-parse", "origin/main")
    return p.stdout.decode().strip() if p.returncode == 0 else ""


def columns(header):
    """Shard files are path/verdict/evidence; the joined view puts host first.
    Locating columns by NAME instead of index is why this reads both."""
    h = [c.strip() for c in header]
    def find(*names):
        for n in names:
            if n in h:
                return h.index(n)
        return None
    return find("path"), find("verdict"), find("evidence")


def scan(name, text, main, rep):
    lines = [l.rstrip("\n").split("\t") for l in text.splitlines() if l.strip()]
    if not lines:
        rep["error"].append("%s: empty" % name); return
    ip, iv, ie = columns(lines[0])
    if ip is None or iv is None or ie is None:
        rep["error"].append("%s: header %r has no path/verdict/evidence" % (name, lines[0]))
        return
    for row in lines[1:]:
        if len(row) <= max(ip, iv, ie):
            continue
        path, verdict, ev = row[ip], row[iv], row[ie]
        if verdict not in DELETION_BOUND:
            continue
        rep["deletion_bound"] += 1
        if VACUOUS.search(ev):
            rep["vacuous"].append((name, path, verdict, VACUOUS.search(ev).group(0)))
        if not UNTRACKED.search(ev):
            rep["untracked_silent"].append((name, path, verdict))
        cited = MAIN_CITE.findall(ev)
        if main and cited and not any(main.startswith(c) or c.startswith(main[:9]) for c in cited):
            rep["stale"].append((name, path, verdict, cited[0]))


def run(files, rep):
    main = current_main()
    rep["main"] = main
    for f in files:
        if os.path.exists(f):
            scan(f, open(f).read(), main, rep)
            continue
        p = git("show", "%s:%s" % (REF, f))
        if p.returncode != 0:
            rep["error"].append("cannot read %s at %s" % (f, REF)); continue
        scan(f, p.stdout.decode("utf-8", "replace"), main, rep)
    return rep


def blank():
    return {"deletion_bound": 0, "vacuous": [], "stale": [], "untracked_silent": [],
            "error": [], "main": ""}


def report(rep):
    print("current origin/main: %s" % (rep["main"] or "UNKNOWN"))
    print("deletion-bound rows examined: %d" % rep["deletion_bound"])
    for name, path, verdict, frag in rep["vacuous"]:
        print("VACUOUS  %s: %s says %s on %r -- true of every empty set"
              % (name, path, verdict, frag))
    for name, path, verdict, cited in rep["stale"]:
        print("STALE    %s: %s says %s judged against main %s, not current"
              % (name, path, verdict, cited))
    for name, path, verdict in rep["untracked_silent"]:
        print("UNTRACKED-SILENT %s: %s says %s without accounting for untracked content"
              % (name, path, verdict))
    for e in rep["error"]:
        print("ERROR    %s" % e)
    bad = (len(rep["vacuous"]) + len(rep["stale"])
           + len(rep["untracked_silent"]) + len(rep["error"]))
    print()
    print("  vacuous universals: %d" % len(rep["vacuous"]))
    print("  stale main cites  : %d" % len(rep["stale"]))
    print("  untracked unaccounted: %d" % len(rep["untracked_silent"]))
    if bad:
        print("\nFAIL: %d deletion-bound row(s) rest on evidence that cannot bear them." % bad)
        return 1
    print("\nOK: every deletion-bound row names a non-empty domain and current main.")
    return 0


def self_test():
    """Each guarantee needs a case ONLY it catches, and both arms: the unblinded
    checker must catch it and the blinded one must miss it. Requiring only the first
    arm is satisfied by a checker that fails on everything."""
    main = "1" * 40
    cases = {
        "vacuous": "path\tverdict\tevidence\n/w\tLANDED\tall 0 file(s) match main %s\n" % main,
        "stale":   "path\tverdict\tevidence\n/w\tLANDED\t3 files match main %s, untracked checked: 0\n" % ("9" * 40),
        "untracked_silent": "path\tverdict\tevidence\n/w\tLANDED\t3 files match main %s\n" % main,
    }
    clean = ("path\tverdict\tevidence\n/w\tLANDED\t3 file(s) match main %s; "
             "untracked checked: 0 files\n" % main)
    ok = True
    for guarantee, text in cases.items():
        r = blank(); scan("t", text, main, r)
        caught = len(r[guarantee]) == 1
        # blinded arm: the guarantee removed must MISS the same row
        gname = {"vacuous": "VACUOUS", "stale": "MAIN_CITE",
                 "untracked_silent": "UNTRACKED"}[guarantee]
        saved = globals()[gname]
        # blinding UNTRACKED means making it match everything (so nothing is ever silent);
        # blinding the other two means making them match nothing.
        globals()[gname] = re.compile(r"") if guarantee == "untracked_silent" else re.compile(r"(?!x)x")
        rb = blank(); scan("t", text, main, rb)
        missed = len(rb[guarantee]) == 0
        globals()[gname] = saved
        # and it must not fire on a clean row
        rc = blank(); scan("t", clean, main, rc)
        quiet = len(rc[guarantee]) == 0
        print("  %-9s unblinded=%d blinded=%d clean=%d  %s"
              % (guarantee, len(r[guarantee]), len(rb[guarantee]), len(rc[guarantee]),
                 "LOAD-BEARING" if (caught and missed and quiet) else "NOT PROVEN"))
        ok = ok and caught and missed and quiet
    print("\nself-test:", "each guarantee catches something only it catches"
          if ok else "AT LEAST ONE GUARANTEE IS NOT LOAD-BEARING")
    return 0 if ok else 1


def main_():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    files = [a for i, a in enumerate(args) if a != "--file" and (i == 0 or args[i-1] == "--file")]
    return report(run(files or DEFAULT, blank()))


if __name__ == "__main__":
    sys.exit(main_())
