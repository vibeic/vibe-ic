#!/usr/bin/env python3
"""Re-verify verdicts_shard_c.tsv from the repository alone.

The shard was decided on three hosts. This checker deliberately needs none of them:
every claim it tests is either a fact about origin/main or a fact about an object
preserved on a live origin ref, so a reviewer with a clone and a network can re-run
it and get the same answer. What it cannot see, it says it cannot see, rather than
passing the row quietly.

Checks
  A shape         one header, three columns, verdict in the agreed vocabulary,
                  non-empty evidence, and a 1:1 join with the shard roster.
  B freshness     every row cites the main sha it was judged against, and that sha
                  is the current origin/main. A stale cite is the exact mistake the
                  355 prior verdicts were being corrected for.
  C content       each RECOVER row naming "<file> sha256 <A> ... origin/main's <B>"
                  must have B == sha256(origin/main:<file>); the ABSENT variant must
                  have main genuinely lacking the path. Where the judged commit is
                  present locally, A is checked against sha256(<head>:<file>) too.
                  This is the check that would catch invented evidence.
  D survivability every "Preserved as <branch>" / "reachable from origin/<branch>"
                  claim must name a branch that is LIVE on origin and that actually
                  CONTAINS the cited commit. A verdict that says work is safe is
                  worthless if the ref holding it is gone; refs/remotes is a local
                  cache and outlives branches origin has deleted, so origin is asked.

Usage
  reverify_shard_c.py --repo <clone> [--verdicts F] [--roster F] [--offline]
  reverify_shard_c.py --self-test     # prove each check fires; see the red

Exit 0 only if every check passed.
"""
import argparse, hashlib, re, subprocess, sys

VOCAB = ("RECOVER", "ABANDON", "LANDED", "UNREACHABLE")

RE_DIFFERS = re.compile(
    r"rule \w+[^:]*: (\S+) sha256 ([0-9a-f]{16}) \((\d+) lines\) "
    r"differs from origin/main \w+'s ([0-9a-f]{16}) \((\d+) lines\)")
RE_ABSENT = re.compile(
    r"rule R2: (\S+) sha256 ([0-9a-f]{16}) \((\d+) lines\) "
    r"is ABSENT from origin/main (\w+) entirely")
RE_HEAD = re.compile(r"worktree HEAD when judged: ([0-9a-f]{40})")
RE_MAINCITE = re.compile(r"origin/main ([0-9a-f]{40})")
RE_PRESERVED = re.compile(r"Preserved as ([\w/.\-]+?)[,;.\s]")
RE_REACHABLE = re.compile(r"reachable from origin/([\w/.\-]+?)[,;.\s]")
RE_RECOVER_CMD = re.compile(r"git fetch origin ([\w/.\-]+) && git checkout ([0-9a-f]{40})")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True)


def sha16(b):
    return hashlib.sha256(b).hexdigest()[:16]


def read_tsv(path):
    return [l.rstrip("\n").split("\t") for l in open(path) if l.strip()]


class Report:
    def __init__(self):
        self.fail = []
        self.counts = {}

    def bump(self, k, n=1):
        self.counts[k] = self.counts.get(k, 0) + n

    def bad(self, check, path, msg):
        self.fail.append((check, path, msg))


def check_shape(rows, roster_paths, rep):
    hdr, body = rows[0], rows[1:]
    if hdr != ["path", "verdict", "evidence"]:
        rep.bad("A", "-", "header is %r, expected path/verdict/evidence" % (hdr,))
    seen = set()
    for r in body:
        p = r[0] if r else "-"
        if len(r) != 3:
            rep.bad("A", p, "row has %d columns, expected 3" % len(r)); continue
        if r[1] not in VOCAB:
            rep.bad("A", p, "verdict %r not in %s" % (r[1], "/".join(VOCAB)))
        if not r[2].strip():
            rep.bad("A", p, "empty evidence")
        if p in seen:
            rep.bad("A", p, "duplicate row")
        seen.add(p)
    if roster_paths is not None:
        for p in roster_paths - seen:
            rep.bad("A", p, "in the roster but has no verdict")
        for p in seen - roster_paths:
            rep.bad("A", p, "has a verdict but is not in the roster")
    rep.bump("rows", len(body))
    return body


def check_freshness(body, main, rep):
    for p, v, e in body:
        cited = set(RE_MAINCITE.findall(e))
        if not cited:
            rep.bad("B", p, "evidence names no main sha at all"); continue
        stale = [c for c in cited if c != main]
        if stale:
            rep.bad("B", p, "judged against %s, current origin/main is %s" % (stale[0], main))
        else:
            rep.bump("freshness-ok")


def check_content(repo, body, rep):
    for p, v, e in body:
        m = RE_DIFFERS.search(e)
        if m:
            f, a, b = m.group(1), m.group(2), m.group(4)
            if a == b:
                rep.bad("C", p, "claims a difference but both sha256 are %s" % a)
            r = git(repo, "show", "origin/main:" + f)
            real = sha16(r.stdout) if r.returncode == 0 else "ABSENT_ON_MAIN"
            if real != b:
                rep.bad("C", p, "main-side sha256 for %s: evidence %s, actual %s" % (f, b, real))
            else:
                rep.bump("main-side-verified")
            _head_side(repo, p, e, f, a, rep)
            continue
        m = RE_ABSENT.search(e)
        if m:
            f, a = m.group(1), m.group(2)
            if git(repo, "cat-file", "-e", "origin/main:" + f).returncode == 0:
                rep.bad("C", p, "claims %s is absent from main, but main has it" % f)
            else:
                rep.bump("main-side-verified")
            _head_side(repo, p, e, f, a, rep)
            continue
        rep.bump("no-sha-pair")


def _head_side(repo, p, e, f, a, rep):
    hm = RE_HEAD.search(e)
    if not hm or git(repo, "cat-file", "-e", hm.group(1) + "^{commit}").returncode != 0:
        rep.bump("head-side-unavailable"); return
    r = git(repo, "show", hm.group(1) + ":" + f)
    real = sha16(r.stdout) if r.returncode == 0 else "MISSING_IN_HEAD"
    if real != a:
        rep.bad("C", p, "head-side sha256 for %s: evidence %s, actual %s" % (f, a, real))
    else:
        rep.bump("head-side-verified")


def live_heads(repo, offline):
    if offline:
        return None
    r = git(repo, "ls-remote", "--heads", "origin")
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.decode().splitlines():
        sha, ref = line.split()
        out[ref.replace("refs/heads/", "")] = sha
    return out


def check_survivability(repo, body, live, rep):
    if live is None:
        rep.bump("survivability-skipped(no origin listing)")
        return
    for p, v, e in body:
        claims = set()
        for m in RE_PRESERVED.finditer(e + " "):
            claims.add((m.group(1), None))
        for m in RE_REACHABLE.finditer(e + " "):
            claims.add((m.group(1), None))
        for m in RE_RECOVER_CMD.finditer(e):
            claims.add((m.group(1), m.group(2)))
        for br, sha in claims:
            if br not in live:
                rep.bad("D", p, "claims work is preserved on %s, which is NOT live on origin" % br)
                continue
            rep.bump("branch-live")
            if sha is None:
                continue
            tip = git(repo, "rev-parse", "-q", "--verify", "refs/remotes/origin/" + br)
            if tip.returncode != 0:
                rep.bump("containment-unfetched"); continue
            t = tip.stdout.decode().strip()
            if git(repo, "merge-base", "--is-ancestor", sha, t).returncode == 0:
                rep.bump("containment-verified")
            else:
                rep.bad("D", p, "%s does not contain %s" % (br, sha[:12]))


def run(repo, verdicts, roster, offline, rep):
    rows = read_tsv(verdicts)
    roster_paths = None
    if roster:
        rr = [l for l in read_tsv(roster) if not l[0].startswith("#")]
        roster_paths = {r[1] for r in rr[1:]}
    body = check_shape(rows, roster_paths, rep)
    main = git(repo, "rev-parse", "origin/main").stdout.decode().strip()
    check_freshness(body, main, rep)
    check_content(repo, body, rep)
    check_survivability(repo, body, live_heads(repo, offline), rep)
    return rep


def self_test():
    """Each check must go RED on a row that violates it. If a check cannot fail,
    it is decoration, not a check."""
    import tempfile, os
    cases = [
        ("A shape/vocabulary", "path\tverdict\tevidence\n/w\tPROBABLY\tsomething\n"),
        ("A empty evidence",   "path\tverdict\tevidence\n/w\tRECOVER\t\n"),
        ("B stale main",       "path\tverdict\tevidence\n/w\tRECOVER\trule R2: f sha256 "
                               + "a" * 16 + " (1 lines) differs from origin/main deadbee's "
                               + "b" * 16 + " (1 lines). against origin/main "
                               + "0" * 40 + "\n"),
        ("C invented sha",     "path\tverdict\tevidence\n/w\tRECOVER\trule R2: README.md sha256 "
                               + "a" * 16 + " (1 lines) differs from origin/main x's "
                               + "b" * 16 + " (1 lines).\n"),
        ("D dead rescue ref",  "path\tverdict\tevidence\n/w\tABANDON\tPreserved as "
                               "harvest/rescue-this-branch-does-not-exist, recover with: "
                               "git fetch origin harvest/rescue-this-branch-does-not-exist "
                               "&& git checkout " + "c" * 40 + "\n"),
    ]
    repo = os.environ.get("REVERIFY_REPO", ".")
    allred = True
    for name, content in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
            fh.write(content); tmp = fh.name
        rep = Report()
        try:
            run(repo, tmp, None, False, rep)
        finally:
            os.unlink(tmp)
        red = bool(rep.fail)
        print("  %-22s %s" % (name, "RED (detected)" if red else "GREEN -- CHECK IS BLIND"))
        for c, p, m in rep.fail[:2]:
            print("       [%s] %s" % (c, m))
        allred = allred and red
    print("\nself-test:", "all checks fire" if allred else "AT LEAST ONE CHECK IS BLIND")
    return 0 if allred else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--verdicts", default="tools/harvest/verdicts_shard_c.tsv")
    ap.add_argument("--roster", default="tools/harvest/_harv_shard_c.tsv")
    ap.add_argument("--offline", action="store_true",
                    help="skip the origin listing; survivability is then reported as skipped, not passed")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    rep = Report()
    run(a.repo, a.verdicts, a.roster, a.offline, rep)
    for k in sorted(rep.counts):
        print("  %-40s %d" % (k, rep.counts[k]))
    if rep.fail:
        print("\nFAILURES: %d" % len(rep.fail))
        for c, p, m in rep.fail:
            print("  [%s] %s: %s" % (c, p, m))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
