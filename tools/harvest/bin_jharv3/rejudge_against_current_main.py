#!/usr/bin/env python3
"""Re-judge verdicts_shard_c.tsv against whatever origin/main is NOW.

    usage: rejudge_against_current_main.py [--repo DIR] [--from SHA] [--to SHA]
                                           [--dry-run] [--allow-flip PATH=VERDICT]

WHY THIS IS NOT A RELABEL. The contract's whole point is that the 355 prior verdicts
were stale, and re-using a stale judgement is the mistake being corrected. When main
moves, the answer is not to rewrite the cited sha -- that is a lie about a
measurement -- but to redo the measurement and write down what it now says.

So every number this touches is recomputed from the repository:

  * the main-side sha256 and line count of each row's named file, from the NEW main;
  * whether an "ABSENT from main" claim is still true;
  * whether a "differs from main" claim is still true -- and if the file is now
    IDENTICAL, that is a RECOVER whose ground has gone, and this script REFUSES to
    rewrite it silently. It stops and names the row.

A verdict change is never automatic. `--allow-flip <path>=<verdict>` is how an
operator says "I measured that one myself and here is the answer", and a flip toward
a deletion-authorising verdict still has to satisfy every deletion-bound gate
afterwards. Drifting main into a LANDED without looking at the directory is exactly
the failure the untracked and ignored gates exist to prevent.

DRIFT DIRECTION, WRITTEN DOWN BECAUSE IT IS THE ONLY THING THAT MAKES THIS SAFE.
While main only FAST-FORWARDS, gaining commits can make a RECOVER over-conservative
(its work may have landed) but cannot make a LANDED or ABANDON unsafe -- main never
loses content it already had; a file deleted at the tip is still in main's history.
This script VERIFIES the fast-forward before it will touch anything. On a rewrite it
refuses outright: then every verdict needs re-judging, not re-citing.
"""
import argparse, hashlib, os, re, subprocess, sys

RE_DIFFERS = re.compile(
    r"(?P<pre>rule \w+[^:]*: )(?P<file>\S+) sha256 (?P<a>[0-9a-f]{16}) "
    r"\((?P<an>\d+) lines\) differs from origin/main (?P<m>\w+)'s "
    r"(?P<b>[0-9a-f]{16}) \((?P<bn>\d+) lines\)")
RE_ABSENT = re.compile(
    r"(?P<pre>rule R2: )(?P<file>\S+) sha256 (?P<a>[0-9a-f]{16}) "
    r"\((?P<an>\d+) lines\) is ABSENT from origin/main (?P<m>\w+) entirely")


def sh(repo, *a):
    return subprocess.run(["git", "-C", repo] + list(a), capture_output=True)


def blob(repo, rev, path):
    p = sh(repo, "show", f"{rev}:{path}")
    return None if p.returncode else p.stdout


def h16(b):
    return hashlib.sha256(b).hexdigest()[:16]


def nlines(b):
    return b.count(b"\n") + (0 if (not b or b.endswith(b"\n")) else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--verdicts")
    ap.add_argument("--from", dest="old", required=True)
    ap.add_argument("--to", dest="new", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-flip", action="append", default=[])
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = a.repo or subprocess.run(
        ["git", "-C", here, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True).stdout.strip()
    src = a.verdicts or os.path.join(here, "..", "verdicts_shard_c.tsv")
    flips = dict(x.split("=", 1) for x in a.allow_flip)

    old = sh(repo, "rev-parse", a.old).stdout.decode().strip()
    new = sh(repo, "rev-parse", a.new).stdout.decode().strip()
    if sh(repo, "merge-base", "--is-ancestor", old, new).returncode != 0:
        sys.exit(f"REFUSING: {old[:11]} is not an ancestor of {new[:11]}. main was "
                 f"rewritten, so every verdict needs re-judging, not re-citing.")
    n_commits = sh(repo, "rev-list", "--count", f"{old}..{new}").stdout.decode().strip()
    print(f"main {old[:11]} -> {new[:11]}, fast-forward, {n_commits} commits")

    lines = open(src, encoding="utf-8").read().splitlines()
    out, stats, problems = [], {"differs_refreshed": 0, "absent_confirmed": 0,
                                "became_identical": 0, "became_present": 0,
                                "no_claim": 0, "flipped": 0}, []
    for i, ln in enumerate(lines):
        f = ln.split("\t")
        if i == 0 or len(f) != 3:
            out.append(ln)
            continue
        path, verdict, ev = f
        m = RE_DIFFERS.search(ev)
        if m:
            b = blob(repo, new, m.group("file"))
            if b is None:
                ev = ev.replace(m.group(0),
                                f"{m.group('pre')}{m.group('file')} sha256 {m.group('a')} "
                                f"({m.group('an')} lines) is ABSENT from origin/main "
                                f"{new[:9]} entirely")
                stats["absent_confirmed"] += 1
            elif h16(b) == m.group("a"):
                stats["became_identical"] += 1
                if flips.get(path):
                    verdict = flips[path]
                    stats["flipped"] += 1
                else:
                    problems.append(
                        f"{path}: named file {m.group('file')} is now IDENTICAL to main "
                        f"{new[:9]} -- the RECOVER's ground is gone. Measure the directory "
                        f"and pass --allow-flip '{path}=<VERDICT>'; this will not guess.")
                    out.append(ln)
                    continue
            else:
                ev = ev.replace(m.group(0),
                                f"{m.group('pre')}{m.group('file')} sha256 {m.group('a')} "
                                f"({m.group('an')} lines) differs from origin/main "
                                f"{new[:9]}'s {h16(b)} ({nlines(b)} lines)")
                stats["differs_refreshed"] += 1
        else:
            m2 = RE_ABSENT.search(ev)
            if m2:
                b = blob(repo, new, m2.group("file"))
                if b is not None:
                    stats["became_present"] += 1
                    problems.append(
                        f"{path}: {m2.group('file')} was ABSENT from main and is now "
                        f"PRESENT at {new[:9]}. Re-measure; this will not guess.")
                    out.append(ln)
                    continue
                ev = ev.replace(m2.group(0),
                                f"{m2.group('pre')}{m2.group('file')} sha256 {m2.group('a')} "
                                f"({m2.group('an')} lines) is ABSENT from origin/main "
                                f"{new[:9]} entirely")
                stats["absent_confirmed"] += 1
            else:
                stats["no_claim"] += 1
        ev = ev.replace(old, new).replace(old[:9], new[:9]).replace(old[:11], new[:11])
        out.append("\t".join([path, verdict, ev]))

    print("  " + "  ".join(f"{k}={v}" for k, v in stats.items()))
    if problems:
        print()
        for p in problems:
            print("REFUSED " + p)
        print(f"\nFAIL: {len(problems)} row(s) need a measurement, not a rewrite. "
              f"Nothing written.")
        return 1
    if a.dry_run:
        print("--dry-run: nothing written")
        return 0
    open(src, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"wrote {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
