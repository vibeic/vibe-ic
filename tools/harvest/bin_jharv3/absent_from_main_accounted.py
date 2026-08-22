#!/usr/bin/env python3
"""A deletion-bound row may hold files main's TIP lacks — but only main's own.

    usage: absent_from_main_accounted.py [--repo DIR] [--verdicts F] [--measured F]
           absent_from_main_accounted.py --self-test

WHY. The L0 rule behind every LANDED row is "every file this branch owns is
byte-identical to origin/main", where "owns" means the diff against its merge-base.
That is the right scope -- a whole-tree walk counts main moving on as unlanded work,
which is the error that made a peer flip a correct LANDED to RECOVER. But the owned
set does NOT cover a file the worktree HOLDS and main's tip does not have. Such a
file is invisible to the rule, present on disk, and destroyed by the deletion the
row authorises.

They are not hypothetical. 17 of shard C's 19 deletion-bound rows hold at least one:
15 hold the same ten, one holds `RESULT.md`, one holds 17331.

WHAT MAKES ONE SAFE. Not that main "probably deleted it". The test is that the blob
at that path in HEAD is byte-identical to the blob at that path in
merge-base(HEAD, origin/main) -- the commit main itself contains. If it matches, the
file is main's own content at a point in main's history, reachable from origin
forever, and deleting the directory loses nothing. If it does NOT match, the worktree
is holding a version of that path that exists nowhere in main and the row is unsafe
as written.

The second arm covers the rest: a path absent at the merge-base too is accounted for
only if the row names a LIVE origin ref that CONTAINS the HEAD commit, because then
the whole tree survives the directory. Anything neither arm accounts for is RED.

FAILING CLOSED. A HEAD commit missing from the object store, an empty merge-base, an
unreadable tree: each is a loud exit naming the row. None of them is a zero.
"""
import argparse, os, re, subprocess, sys

DBOUND = ("LANDED", "ABANDON")
RE_REF = re.compile(r"(?:reachable from|Preserved as|preserved as) (?:origin/)?([\w./-]+)")


def sh(repo, *a, check=True):
    p = subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)
    if check and p.returncode != 0:
        return None
    return p.stdout


def repo_of_this_file():
    d = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit("FAIL: this file is not inside a git clone; pass --repo")
    return p.stdout.strip()


def load(path, want):
    if not os.path.exists(path):
        sys.exit(f"FAIL: missing input {path} -- an absent measurement is not a clean one")
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        rows = []
        for ln in fh:
            f = ln.rstrip("\n").split("\t")
            if len(f) == len(head):
                rows.append(dict(zip(head, f)))
    for c in want:
        if rows and c not in rows[0]:
            sys.exit(f"FAIL: {path} has no column {c!r}")
    return rows


def blobs(repo, rev):
    out = sh(repo, "ls-tree", "-r", rev)
    if out is None:
        return None
    m = {}
    for ln in out.splitlines():
        meta, path = ln.split("\t", 1)
        m[path] = meta.split()[2]
    return m


def check(repo, verdicts, measured, ref="origin/main", live_refs=None):
    main = blobs(repo, ref)
    if main is None:
        sys.exit(f"FAIL: cannot read {ref}")
    meas = {r["path"]: r for r in measured}
    if live_refs is None:
        ls = sh(repo, "ls-remote", "--heads", "origin", check=False) or ""
        live_refs = {l.split("refs/heads/")[-1] for l in ls.splitlines() if "refs/heads/" in l}
    bad, stats = [], {"rows": 0, "paths": 0, "same_at_merge_base": 0, "covered_by_live_ref": 0}
    for r in verdicts:
        if r["verdict"] not in DBOUND:
            continue
        p = r["path"]
        m = meas.get(p)
        if not m:
            bad.append(f"UNMEASURED {r['verdict']} row {p}")
            continue
        head = m["head"]
        if sh(repo, "cat-file", "-e", head + "^{commit}", check=False) is None or \
                subprocess.run(["git", "-C", repo, "cat-file", "-e", head + "^{commit}"],
                               capture_output=True).returncode != 0:
            bad.append(f"HEAD OBJECT ABSENT here for {p} ({head}) -- cannot judge, not clean")
            continue
        mb = (sh(repo, "merge-base", head, ref, check=False) or "").strip()
        t = blobs(repo, head)
        if t is None:
            bad.append(f"UNREADABLE TREE for {p} ({head})")
            continue
        mbt = blobs(repo, mb) if mb else {}
        stats["rows"] += 1
        named = {x for x in RE_REF.findall(r["evidence"])}
        ref_ok = any(nr in live_refs and
                     subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor",
                                     head, "origin/" + nr], capture_output=True).returncode == 0
                     for nr in named)
        for path, blob in t.items():
            if path in main:
                continue
            stats["paths"] += 1
            if mbt.get(path) == blob:
                stats["same_at_merge_base"] += 1
            elif ref_ok:
                stats["covered_by_live_ref"] += 1
            else:
                bad.append(
                    f"UNACCOUNTED {r['verdict']} {p}: holds {path} which origin/main's tip "
                    f"lacks and whose blob {blob[:11]} is not the merge-base's "
                    f"({(mbt.get(path) or 'ABSENT')[:11]}), and no live origin ref this row "
                    f"names contains {head[:11]}")
    return bad, stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--objects-repo", help="clone holding the worktree HEAD commits")
    ap.add_argument("--verdicts")
    ap.add_argument("--measured")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = a.objects_repo or a.repo or repo_of_this_file()
    v = load(a.verdicts or os.path.join(here, "..", "verdicts_shard_c.tsv"),
             ["path", "verdict", "evidence"])
    m = load(a.measured or os.path.join(here, "..", "raw_untracked_ignored_shard_c_jharv3.tsv"),
             ["path", "head"])
    print(f"objects repo {repo}")
    bad, st = check(repo, v, m)
    print(f"deletion-bound rows judged: {st['rows']}")
    print(f"paths held here that origin/main's tip lacks: {st['paths']}")
    print(f"  identical to the same path at the merge-base (main's own history): "
          f"{st['same_at_merge_base']}")
    print(f"  covered by a live origin ref containing the HEAD commit: "
          f"{st['covered_by_live_ref']}")
    if bad:
        print()
        for b in bad[:40]:
            print(b)
        if len(bad) > 40:
            print(f"... {len(bad)-40} more")
        print(f"\nFAIL: {len(bad)} finding(s).")
        return 1
    print("\nABSENT-FROM-MAIN ACCOUNTED OK — every file these rows hold that main's tip "
          "lacks is main's own content at the merge-base, or is covered by a live origin "
          "ref that contains the whole commit.")
    return 0


def self_test():
    """Both arms, on a repository built for the purpose. A gate only ever pointed at
    valid input has never been shown to reject anything."""
    import tempfile, shutil
    ok = 0
    with tempfile.TemporaryDirectory() as tmp:
        r = os.path.join(tmp, "r")
        os.makedirs(r)
        def g(*a, **k):
            return subprocess.run(["git", "-C", r] + list(a), capture_output=True, text=True, **k)
        g("init", "-q", "-b", "main")
        g("config", "user.email", "t@t"); g("config", "user.name", "t")
        open(f"{r}/keep.txt", "w").write("keep\n")
        open(f"{r}/gone.txt", "w").write("original\n")
        g("add", "keep.txt", "gone.txt"); g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD").stdout.strip()
        os.remove(f"{r}/gone.txt")
        g("rm", "-q", "gone.txt"); g("commit", "-qm", "main deletes gone.txt")
        g("update-ref", "refs/remotes/origin/main", "HEAD")
        # worktree A: sits at base -> holds gone.txt, identical to the merge-base
        # worktree B: same but with gone.txt CHANGED -- a version main never had
        g("checkout", "-q", base)
        open(f"{r}/gone.txt", "w").write("MUTATED\n")
        g("add", "gone.txt"); g("commit", "-qm", "off-main change to a deleted path")
        mutated = g("rev-parse", "HEAD").stdout.strip()

        def rows(head, verdict="LANDED", ev="no ref named"):
            v = [{"path": "/w", "verdict": verdict, "evidence": ev}]
            m = [{"path": "/w", "head": head}]
            return v, m

        v, m = rows(base)
        bad, st = check(r, v, m, ref="refs/remotes/origin/main", live_refs=set())
        clean = not bad and st["same_at_merge_base"] == 1
        print(f"[clean arm: file main deleted, unchanged since] findings={len(bad)} "
              f"accounted={st['same_at_merge_base']} -> {'OK' if clean else 'BROKEN'}")
        ok += 1 if clean else 0

        v, m = rows(mutated)
        bad, st = check(r, v, m, ref="refs/remotes/origin/main", live_refs=set())
        caught = len(bad) == 1 and "UNACCOUNTED" in bad[0]
        print(f"[G1 off-main version of a path main deleted] findings={len(bad)} "
              f"-> {'CAUGHT' if caught else 'MISSED'}")
        if bad:
            print("     " + bad[0])
        ok += 1 if caught else 0

        v, m = rows("0" * 40)
        bad, st = check(r, v, m, ref="refs/remotes/origin/main", live_refs=set())
        caught = any("HEAD OBJECT ABSENT" in b for b in bad)
        print(f"[G2 HEAD commit not in the store] -> {'CAUGHT' if caught else 'MISSED'}")
        ok += 1 if caught else 0

        v, m = rows(mutated)
        m = []
        bad, st = check(r, v, m, ref="refs/remotes/origin/main", live_refs=set())
        caught = any("UNMEASURED" in b for b in bad)
        print(f"[G3 deletion-bound row with no measurement] -> "
              f"{'CAUGHT' if caught else 'MISSED'}")
        ok += 1 if caught else 0
    print(f"\nself-test: {ok} of 4 guarantees proven load-bearing")
    return 0 if ok == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
