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
                  This FAILS on drift rather than re-labelling: the rows RECORD the
                  main their judge used, which is the only form that cannot mislead.
                  A frozen constant lies once main moves; a live-derived label lies
                  the moment a file is regenerated without re-judging, because it
                  claims a freshness the JUDGEMENT does not have. Recorded plus
                  disclosed drift is the third option and the only safe one.
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

A claim this checker cannot READ is a failure, not a pass. Rows whose rule makes no
sha256 claim by design (L0/L2/A4) are counted separately from rows that make a claim
the parser could not consume -- conflating the two hides unchecked evidence inside an
honest-looking bucket. Both were real defects in this file's first version: it read
two of its own evidence phrasings and silently filed three claim-bearing rows under
"no-sha-pair".

Usage
  reverify_shard_c.py --repo <clone> [--verdicts F] [--roster F] [--offline]
  reverify_shard_c.py --self-test     # prove each check fires; see the red

Exit 0 only if every check passed.
"""
import argparse, hashlib, os, re, socket, subprocess, sys

VOCAB = ("RECOVER", "ABANDON", "LANDED", "UNREACHABLE")


def this_host():
    """The roster identifies hosts by the last octet of their 192.168.1.x address.

    An on-disk claim is about ONE machine's disk. Deciding whether to hash it from
    `os.path.isdir(path)` alone answers a question about host .112 with host .108's
    filesystem the moment the two share a path name -- and these hosts all use
    /home/reyerchu/_* conventions, so that collision is a matter of time, not of
    possibility. Today no shard-C remote path exists here, which makes the old code
    right by luck rather than by construction. jharv2 hit the mirror image: four rows
    read GONE from the two hosts it happened to ask, and were alive on two others.
    A path absent from the host you asked is an unasked question, not an answer.
    """
    try:
        for line in subprocess.run(["hostname", "-I"], capture_output=True,
                                   text=True, timeout=10).stdout.split():
            if line.startswith("192.168.1."):
                return line.rsplit(".", 1)[1]
    except Exception:
        pass
    return None

RE_DIFFERS = re.compile(
    r"rule \w+[^:]*: (\S+) sha256 ([0-9a-f]{16}) \((\d+) lines\) "
    r"differs from origin/main \w+'s ([0-9a-f]{16}) \((\d+) lines\)")
RE_ABSENT = re.compile(
    r"rule R2: (\S+) sha256 ([0-9a-f]{16}) \((\d+) lines\) "
    r"is ABSENT from origin/main (\w+) entirely")
RE_ONDISK = re.compile(
    r"(\S+) sha256 ([0-9a-f]{64}|[0-9a-f]{16}) \((\d+) lines\) "
    r"is on disk here and ABSENT FROM origin/main")
RE_PRESENT_ABSENT = re.compile(
    r"[Rr]ule \w+[^:]*: (\S+) sha256 ([0-9a-f]{16}|[0-9a-f]{64}) \((\d+) bytes\) "
    r"is present in this worktree, is ABSENT FROM origin/main")
RE_UNTRACKED = re.compile(
    r"UNTRACKED (\S+?),? sha256 ([0-9a-f]{16}|[0-9a-f]{64}) \((\d+) bytes\)")
RE_COMPARISON = re.compile(
    r"DIFFERS from the file of the same name in (\S+) "
    r"\(sha256 ([0-9a-f]{16}|[0-9a-f]{64}), (\d+) bytes\)")
# a hash LITERAL after the word, which "sha256 on both sides of all 28 files" is not
RE_ANY_CLAIM = re.compile(r"sha256 ([0-9a-f]{16}|[0-9a-f]{64})\b")
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
            rep.bad("B", p, "judged against %s, current origin/main is %s. "
                            "Drift direction: while main only fast-forwards, this can "
                            "make a RECOVER over-conservative (its work may have landed "
                            "since) but cannot make a LANDED or ABANDON unsafe -- main "
                            "gaining commits never removes content it already had. A "
                            "force-push or history rewrite breaks that, and then every "
                            "verdict here needs re-judging, not re-labelling."
                            % (stale[0], main))
        else:
            rep.bump("freshness-ok")


def check_content(repo, body, rep, hostof=None, here=None):
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
            _leftover(p, e, [m] + _trailing(repo, p, e, rep), rep)
            continue
        m = RE_ABSENT.search(e)
        if m:
            f, a = m.group(1), m.group(2)
            if git(repo, "cat-file", "-e", "origin/main:" + f).returncode == 0:
                rep.bad("C", p, "claims %s is absent from main, but main has it" % f)
            else:
                rep.bump("main-side-verified")
            _head_side(repo, p, e, f, a, rep)
            _leftover(p, e, [m] + _trailing(repo, p, e, rep), rep)
            continue
        # a file on DISK (uncommitted), named because counting edits is not a checkable claim.
        m = RE_ONDISK.search(e) or RE_PRESENT_ABSENT.search(e)
        if m:
            f, a = m.group(1), m.group(2)
            if git(repo, "cat-file", "-e", "origin/main:" + f).returncode == 0:
                rep.bad("C", p, "claims %s is absent from main, but main has it" % f)
            else:
                rep.bump("main-side-verified")
            _on_disk_side(p, f, a, rep, e, repo, hostof, here)
            _leftover(p, e, [m] + _trailing(repo, p, e, rep), rep)
            continue
        extra = [m for m in (RE_UNTRACKED.search(e), RE_COMPARISON.search(e)) if m]
        if extra:
            for m in extra:
                if _preserved_blob(repo, e, m.group(1), m.group(2)):
                    rep.bump("untracked-verified-from-preserved-blob")
                else:
                    rep.bump("UNDETERMINED(untracked on another host, no preserved blob matched)")
        _leftover(p, e, extra, rep)


def _preserved_blob(repo, e, f, a):
    """Untracked bytes are on no commit, so they are only checkable if somebody
    preserved them. Look for a blob with this sha256 on the rescue branches THIS ROW
    names, among files sharing the claimed name's stem -- the rescue copies rename
    (HANDOFF_TO_GATEKEEPER.md -> .drv2.md), so an exact-path lookup would miss them."""
    import posixpath
    # Deliberately BROAD: any harvest ref named anywhere in the row is a candidate to
    # look in. Widening where to SEARCH cannot manufacture a pass -- the sha256 still
    # has to match -- and rows name their rescue branch in more phrasings than the
    # strict claim-bearing forms check D uses ("pushed it as X", "Preserved as X").
    branches = {m.group(1) for m in RE_PRESERVED.finditer(e + " ")}
    branches |= {m.group(1) for m in RE_RECOVER_CMD.finditer(e)}
    branches |= set(re.findall(r"(harvest/[A-Za-z0-9._/\-]+?)(?=[,;.\s]|$)", e + " "))
    stem = posixpath.basename(f).split(".")[0]
    if not stem:
        return False
    for br in branches:
        ref = "refs/remotes/origin/" + br
        if git(repo, "rev-parse", "-q", "--verify", ref).returncode != 0:
            continue
        ls = git(repo, "ls-tree", "-r", "--name-only", ref)
        if ls.returncode != 0:
            continue
        for path in ls.stdout.decode(errors="replace").splitlines():
            if not posixpath.basename(path).startswith(stem):
                continue
            blob = git(repo, "show", "%s:%s" % (ref, path))
            if blob.returncode == 0 and hashlib.sha256(blob.stdout).hexdigest()[:len(a)] == a:
                return True
    return False


def _on_disk_side(p, f, a, rep, e="", repo=None, hostof=None, here=None):
    """The claim is about bytes on one host's disk. Hash them where that disk is THIS
    host; anywhere else say UNDETERMINED. Reporting an unreachable disk as verified is
    the manufactured pass this whole job exists to avoid."""
    import os
    # Only this host's disk may answer a claim about this host's disk.
    row_host = (hostof or {}).get(p)
    mine = (row_host is None or here is None or row_host == here)
    if not mine:
        if repo is not None and _preserved_blob(repo, e, f, a):
            rep.bump("untracked-verified-from-preserved-blob"); return
        rep.bump("UNDETERMINED(row belongs to host .%s, this is .%s)" % (row_host, here))
        return
    cand = os.path.join(p, f)
    if os.path.isdir(p) and os.path.isfile(cand):
        h = hashlib.sha256(open(cand, "rb").read()).hexdigest()
        if h[:len(a)] != a:
            rep.bad("C", p, "on-disk sha256 for %s: evidence %s, actual %s" % (f, a, h[:len(a)]))
        else:
            rep.bump("on-disk-verified")
        return
    if repo is not None and _preserved_blob(repo, e, f, a):
        rep.bump("untracked-verified-from-preserved-blob"); return
    if os.path.isdir(p):
        rep.bad("C", p, "evidence names %s on disk, but it is not there now "
                        "and no preserved blob matches" % f); return
    rep.bump("UNDETERMINED(untracked on another host, no preserved blob matched)")


def _trailing(repo, p, e, rep):
    """Untracked-file clauses attached to a row whose primary claim already parsed."""
    out = []
    # "the file of the SAME NAME in <dir>" names a directory, not a file: the filename
    # is the one the row's primary claim already gave. Reading group(1) as a filename
    # made this lookup search for a stem no file has, and report NOT FOUND for a blob
    # that was sitting on the branch the row names.
    primary = None
    for rx in (RE_PRESENT_ABSENT, RE_ONDISK, RE_UNTRACKED, RE_DIFFERS, RE_ABSENT):
        pm = rx.search(e)
        if pm:
            primary = pm.group(1); break
    for rx, m in ((RE_UNTRACKED, RE_UNTRACKED.search(e)), (RE_COMPARISON, RE_COMPARISON.search(e))):
        if not m:
            continue
        out.append(m)
        fname = primary if (rx is RE_COMPARISON and primary) else m.group(1)
        if _preserved_blob(repo, e, fname, m.group(2)):
            rep.bump("untracked-verified-from-preserved-blob")
        else:
            rep.bump("UNDETERMINED(untracked on another host, no preserved blob matched)")
    return out


def _leftover(p, e, consumed, rep):
    """Any hash literal the parser did not consume is an UNREAD claim. Silence here is
    how 3 claim-bearing rows passed as 'no-sha-pair' in the first version."""
    spans = [(m.start(), m.end()) for m in consumed]
    unread = []
    for m in RE_ANY_CLAIM.finditer(e):
        if any(s0 <= m.start() < e0 for s0, e0 in spans):
            continue
        unread.append(m.group(1))
    if not unread:
        rep.bump("fully-read" if consumed else "no-claim-by-design")
        return
    rep.bad("C", p, "evidence carries %d sha256 literal(s) this checker cannot read "
                    "(first: %s) -- an unread claim is not a pass"
                    % (len(unread), unread[0][:16]))


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
    roster_hosts = {}
    if roster:
        rr = [l for l in read_tsv(roster) if not l[0].startswith("#")]
        roster_paths = {r[1] for r in rr[1:]}
        roster_hosts = {r[1]: r[0] for r in rr[1:] if len(r) > 1}
    body = check_shape(rows, roster_paths, rep)
    hostof, here = roster_hosts, this_host()
    if here:
        rep.bump("running-on-host-.%s" % here)
    main = git(repo, "rev-parse", "origin/main").stdout.decode().strip()
    check_freshness(body, main, rep)
    check_content(repo, body, rep, hostof, here)
    check_survivability(repo, body, live_heads(repo, offline), rep)
    return rep


def self_test():
    """Each case must go RED *on the check it targets*.

    The first version of this asserted only that SOME check failed. That is a vacuous
    control: deleting check D entirely still printed "D dead rescue ref RED (detected)"
    and "all checks fire", because check B happened to fire on the same synthetic row.
    A control that cannot tell which check caught the fault cannot prove any of them
    works. Each case now names its target and passes only if that target fires.
    """
    import tempfile, os
    H = "a" * 16
    cases = [
        ("A", "shape/vocabulary",
         "path\tverdict\tevidence\n/w\tPROBABLY\tjudged against origin/main %s\n" % ("0" * 40)),
        ("A", "empty evidence",
         "path\tverdict\tevidence\n/w\tRECOVER\t\n"),
        ("B", "stale main",
         "path\tverdict\tevidence\n/w\tRECOVER\trule L0: everything matched. "
         "against origin/main %s\n" % ("0" * 40)),
        ("C", "invented sha",
         "path\tverdict\tevidence\n/w\tRECOVER\trule R2: README.md sha256 " + H +
         " (1 lines) differs from origin/main x's " + "b" * 16 + " (1 lines).\n"),
        ("C", "unreadable claim",
         "path\tverdict\tevidence\n/w\tRECOVER\trule R9: some novel phrasing carrying "
         "sha256 " + "d" * 64 + " that no pattern here consumes.\n"),
        ("D", "dead rescue ref",
         "path\tverdict\tevidence\n/w\tABANDON\trule A4: dup. Preserved as "
         "harvest/rescue-this-branch-does-not-exist, recover with: git fetch origin "
         "harvest/rescue-this-branch-does-not-exist && git checkout " + "c" * 40 + "\n"),
    ]
    repo = os.environ.get("REVERIFY_REPO", ".")
    allred = True
    for target, name, content in cases:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
            fh.write(content); tmp = fh.name
        rep = Report()
        try:
            run(repo, tmp, None, False, rep)
        finally:
            os.unlink(tmp)
        fired = {c for c, _, _ in rep.fail}
        hit = target in fired
        others = "".join(sorted(fired - {target}))
        print("  [%s] %-20s %s%s" % (
            target, name,
            "RED on %s" % target if hit else "GREEN on %s -- THIS CHECK IS BLIND" % target,
            ("   (also fired: %s)" % others) if others else ""))
        for c, _, m in rep.fail:
            if c == target:
                print("        %s" % m[:150]); break
        allred = allred and hit
    print("\nself-test:", "every check fires on its OWN target"
          if allred else "AT LEAST ONE CHECK IS BLIND ON ITS TARGET")
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
