#!/usr/bin/env python3
"""An ABANDON may only be actioned if its content demonstrably survives the deletion.

    usage: abandon_survivable.py [--file F ...]     (default: shard a/b/c + both joined views)
           abandon_survivable.py --self-test
    env:   VIBEIC_REPO, VIBEIC_REF

WHY THIS EXISTS -- it complements jharv2's predelete_guard.sh, it does not replace it.

predelete_guard.sh asks the LANDED question: does this worktree hold anything that
differs from origin/main? Run over shard C's 19 deletion-bound rows it returned
7 ALLOW and 12 REFUSE, and 11 of those refusals were correct and expected -- paths on
hosts the guard could not reach, refusing because unmeasured and clean are otherwise
identical in its output.

The 12th refusal is structural, not a defect:

    REFUSE  /home/reyerchu/wt-j63x8c  committed_differing=9

That row is an ABANDON, and ABANDON does not claim "already on main". The contract
defines it as a superseded intermediate, an empty tree, or A DUPLICATE OF ANOTHER
WORKTREE YOU NAME. A duplicate holds non-main content BY DEFINITION, so the LANDED
question refuses every duplicate-type ABANDON that will ever be written. That is
safe -- it fails closed -- and it means no gate in this tree can authorise the 30
ABANDON rows across the corpus (shard b 4, shard c 2, extras_joined 24). A verdict
nothing can ever authorise is not actionable, and an executor who notices that is one
step from waiving the guard, which is the dangerous move.

So this asks the ABANDON question instead: IF THIS DIRECTORY WERE DELETED, WHAT STILL
HOLDS ITS CONTENT? Exactly one of these must be demonstrable:

  R1  the row's commit is reachable from a ref that is LIVE ON ORIGIN, asked of origin
      by ls-remote -- refs/remotes is a local cache that outlives branches origin has
      deleted, and a cache hit here authorises deleting the last copy of something.
  R2  the named twin exists on THIS host, holds the same tree, and is a SUPERSET of
      untracked content. Tree identity alone is not enough: it is exactly what made
      the one wrong verdict in shard C, where two identical trees carried different
      untracked handoff documents.

FAILS CLOSED, on jharv2's rule. A row it cannot resolve is REFUSED, never allowed.
An unverifiable ABANDON and a survivable one must not look alike in the output.
"""
import os, re, subprocess, sys, hashlib

# Three lanes write "duplicate" three ways. Reading only my own phrasing reported 32
# rows as unresolvable that mostly say something perfectly checkable -- the same
# "unreadable claim filed as no claim" defect I flagged in others, committed here
# twenty minutes after writing the warning.
RE_TWIN = re.compile(r"(?:same tree as|byte-for-byte identical to|kept copy is) (\S+?)[,;.\s]")
# A DIFFERENT valid justification, not a weaker one: the contract admits "a superseded
# intermediate". Its content is not preserved elsewhere -- it is already ON MAIN,
# which is why main can hold it after the directory is gone.
RE_SUPERSEDED = re.compile(r"superseded intermediate.*?reverse-appl", re.I | re.S)
RE_PRUNED = re.compile(r"registration was pruned.*?no HEAD", re.I | re.S)
RE_REF = re.compile(r"(harvest/[A-Za-z0-9._/\-]+?)(?=[,;.\s]|$)")
RE_REACH = re.compile(r"reachable from origin/([\w/.\-]+?)[,;.\s]")
RE_SHA = re.compile(r"\b([0-9a-f]{40})\b")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("VIBEIC_REPO") or subprocess.run(
    ["git", "-C", HERE, "rev-parse", "--show-toplevel"],
    capture_output=True, text=True).stdout.strip()
REF = os.environ.get("VIBEIC_REF", "origin/harvest/worktree-triage-jharvest")
DEFAULT = ["tools/harvest/verdicts_shard_a.tsv", "tools/harvest/verdicts_shard_b.tsv",
           "tools/harvest/verdicts_shard_c.tsv", "tools/harvest/verdicts_joined.tsv",
           "tools/harvest/verdicts_extras_joined.tsv"]


def git(*a):
    return subprocess.run(["git", "-C", REPO, *a], capture_output=True)


def live_heads():
    p = git("ls-remote", "--heads", "origin")
    if p.returncode != 0:
        return None
    out = {}
    for line in p.stdout.decode().splitlines():
        sha, ref = line.split()
        out[ref.replace("refs/heads/", "")] = sha
    return out


def columns(h):
    h = [c.strip() for c in h]
    def f(*n):
        for x in n:
            if x in h:
                return h.index(x)
        return None
    return f("path"), f("verdict"), f("evidence")


def untracked(wt):
    """--untracked-files=all, never the default: the default collapses an untracked
    DIRECTORY to one entry, so a subtree reads as one file (or as zero once anything
    filters entries by file-ness). jharv2 lost 43 rows to exactly that."""
    p = subprocess.run(["git", "-C", wt, "status", "--porcelain",
                        "--untracked-files=all"], capture_output=True, text=True)
    return sorted(l[3:] for l in p.stdout.splitlines() if l.startswith("??"))


def resolve(path, ev, live, rep):
    shas = RE_SHA.findall(ev)
    # R1: reachable from a ref LIVE on origin
    refs = set(RE_REF.findall(ev + " ")) | set(RE_REACH.findall(ev + " "))
    if live is None:
        rep["refuse"].append((path, "cannot ask origin for live refs -- unmeasured, not safe"))
        return
    for br in refs:
        if br not in live:
            continue
        if git("rev-parse", "-q", "--verify", "refs/remotes/origin/" + br).returncode != 0:
            git("fetch", "-q", "--no-tags", "origin", br)
        tip = git("rev-parse", "-q", "--verify", "refs/remotes/origin/" + br).stdout.decode().strip()
        if not tip:
            continue
        for sha in shas:
            if git("merge-base", "--is-ancestor", sha, tip).returncode == 0:
                rep["allow"].append((path, "R1 commit %s is reachable from origin/%s, live"
                                     % (sha[:12], br)))
                return
    # R3: superseded -- the change is already on main, so main holds it after deletion.
    # Verifiable only where the worktree and its clone are on this host; elsewhere it
    # is a claim this gate has read but cannot re-measure, which is UNKNOWN, not safe.
    if RE_SUPERSEDED.search(ev):
        if os.path.isdir(path):
            rep["unknown"].append((path, "R3 claims superseded-onto-main; present here, but "
                                         "re-running the reverse-apply test needs the clone's "
                                         "origin/main pinned -- not re-measured by this gate"))
        else:
            rep["unknown"].append((path, "R3 claims superseded-onto-main (its change already "
                                         "in main); not on this host, so not re-measured"))
        return
    if RE_PRUNED.search(ev):
        rep["unknown"].append((path, "registration pruned: no HEAD and no merge-base, so neither "
                                     "R1 nor R2 applies; needs the host that holds the files"))
        return
    # R2: a named twin on this host that is a superset
    m = RE_TWIN.search(ev)
    if m:
        twin = m.group(1)
        if not os.path.isdir(twin) or not os.path.isdir(path):
            rep["unknown"].append((path, "R2 names twin %s; both trees are needed and at least "
                                         "one is not on this host -- unmeasured, NOT shown clean"
                                   % twin))
            return
        t1 = git("-C", path, "rev-parse", "HEAD^{tree}") if False else subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip()
        t2 = subprocess.run(["git", "-C", twin, "rev-parse", "HEAD^{tree}"],
                            capture_output=True, text=True).stdout.strip()
        if not t1 or t1 != t2:
            rep["refuse"].append((path, "R2 trees differ (%s vs %s) -- not a duplicate"
                                  % (t1[:9], t2[:9])))
            return
        u_self, u_twin = untracked(path), untracked(twin)
        missing = [f for f in u_self if f not in set(u_twin)]
        if missing:
            rep["refuse"].append((path, "R2 twin is NOT a superset: %d untracked file(s) here "
                                        "are absent there, first=%s" % (len(missing), missing[0])))
            return
        rep["allow"].append((path, "R2 tree %s identical to twin %s, whose untracked set (%d) "
                                   "covers this one (%d)" % (t1[:9], twin, len(u_twin), len(u_self))))
        return
    rep["refuse"].append((path, "names neither a live preserving ref nor a twin -- "
                                "nothing shows the content survives deletion"))


def scan(name, text, live, rep):
    lines = [l.rstrip("\n").split("\t") for l in text.splitlines() if l.strip()]
    if not lines:
        rep["refuse"].append((name, "empty file")); return
    ip, iv, ie = columns(lines[0])
    if None in (ip, iv, ie):
        rep["refuse"].append((name, "header has no path/verdict/evidence")); return
    for row in lines[1:]:
        if len(row) <= max(ip, iv, ie):
            continue
        if row[iv] != "ABANDON":
            continue
        rep["seen"] += 1
        resolve(row[ip], row[ie], live, rep)


def blank():
    # UNKNOWN is not REFUSE. A row whose grammar this gate cannot read has not been
    # shown unsafe; it has not been read. Collapsing the two inflates a danger count
    # with rows that are probably fine and hides the ones that are not -- and neither
    # authorises deletion, so failing closed is preserved either way.
    return {"seen": 0, "allow": [], "refuse": [], "unknown": []}


def main_():
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    files = [a for i, a in enumerate(args) if a != "--file" and (i and args[i-1] == "--file")]
    rep = blank()
    live = live_heads()
    for f in (files or DEFAULT):
        if os.path.exists(f):
            scan(f, open(f).read(), live, rep)
        else:
            p = git("show", "%s:%s" % (REF, f))
            if p.returncode != 0:
                rep["refuse"].append((f, "cannot read at %s" % REF)); continue
            scan(f, p.stdout.decode("utf-8", "replace"), live, rep)
    for p, why in rep["allow"]:
        print("ALLOW   %s\n            %s" % (p, why))
    for p, why in rep["refuse"]:
        print("REFUSE  %s\n            %s" % (p, why))
    for p, why in rep["unknown"]:
        print("UNKNOWN %s\n            %s" % (p, why))
    print("\nABANDON rows examined: %d   survivable: %d   refused: %d   unread/unmeasured: %d"
          % (rep["seen"], len(rep["allow"]), len(rep["refuse"]), len(rep["unknown"])))
    if rep["refuse"] or rep["unknown"]:
        print("\nFAIL: only a row shown survivable may be actioned. REFUSE means shown unsafe; "
              "UNKNOWN means not shown either way -- neither authorises deletion, and they are "
              "counted apart so an unread grammar is not reported as a danger.")
        return 1
    print("\nOK: every ABANDON names something that still holds its content.")
    return 0


def self_test():
    """Both arms per rule, plus the arm that matters most here: a twin that is NOT a
    superset must REFUSE. Without it, R2 degenerates into the tree-identity test that
    produced the one wrong verdict this whole shard had."""
    import tempfile, shutil
    ok = True
    tmp = tempfile.mkdtemp()
    try:
        def mk(name, untracked_files):
            d = os.path.join(tmp, name); os.makedirs(d)
            subprocess.run(["git", "-C", d, "init", "-q"], capture_output=True)
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                subprocess.run(["git", "-C", d, "config", k, v], capture_output=True)
            open(os.path.join(d, "a.txt"), "w").write("same")
            subprocess.run(["git", "-C", d, "add", "-A"], capture_output=True)
            subprocess.run(["git", "-C", d, "commit", "-qm", "i"], capture_output=True)
            for f in untracked_files:
                open(os.path.join(d, f), "w").write("x")
            return d
        a = mk("a", ["only_here.md"])
        b = mk("b", [])
        rep = blank(); resolve(a, "duplicate - same tree as %s, which is kept" % b, {}, rep)
        hit = bool(rep["refuse"]) and "NOT a superset" in rep["refuse"][0][1]
        print("  R2 twin missing this tree's untracked file -> %s"
              % ("REFUSE (correct)" if hit else "ALLOWED -- BLIND"))
        ok = ok and hit
        # control: a twin that IS a superset must ALLOW, else "refuses everything" passes above
        c = mk("c", []); d = mk("d", ["extra.md"])
        rep2 = blank(); resolve(c, "duplicate - same tree as %s, which is kept" % d, {}, rep2)
        hit2 = bool(rep2["allow"])
        print("  CONTROL twin is a superset                 -> %s"
              % ("ALLOW (correct)" if hit2 else "REFUSED -- gate refuses everything"))
        ok = ok and hit2
        rep3 = blank(); resolve("/x", "duplicate, no twin named and no ref", {}, rep3)
        hit3 = bool(rep3["refuse"])
        print("  names neither ref nor twin                 -> %s"
              % ("REFUSE (correct)" if hit3 else "ALLOWED -- BLIND"))
        ok = ok and hit3
        rep4 = blank(); resolve("/x", "Preserved as harvest/rescue-x", None, rep4)
        hit4 = bool(rep4["refuse"]) and "cannot ask origin" in rep4["refuse"][0][1]
        print("  origin unreachable                         -> %s"
              % ("REFUSE, fails closed (correct)" if hit4 else "ALLOWED -- BLIND"))
        ok = ok and hit4
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nself-test:", "each rule catches something only it catches"
          if ok else "AT LEAST ONE RULE IS BLIND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_())
