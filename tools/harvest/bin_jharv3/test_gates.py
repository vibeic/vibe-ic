#!/usr/bin/env python3
"""Tests for the three harvest gates.

    usage: test_gates.py            (needs network: reads origin and the branch)
    env:   VIBEIC_REPO   the vibe-ic clone

WHY THESE EXIST, WHICH IS NOT A FORMALITY.
Five defects were found in these three scripts on the night they were written.
Four were false REDS -- an extension allowlist missing `.inc`, a dotfile with no
extension, "untracked" where the pattern knew only "uncommitted", a parser
cross-joining two claims in one row. Every one was caught, because a red makes
somebody go and look.

The fifth was a false GREEN. `rescue_contradiction.py` printed
"OK: no shard file contradicts a rescue ref" while four rows really did, because
`uncommitted work in (\\S+)` captured the path WITH THE TRAILING COMMA from its
own commit sentence and every lookup missed. It was caught only because the
expected answer was already known to be 4. Written before the measurement, it
would have passed and been shipped as proof the shards were consistent.

A gate nobody has watched fail is not a gate. So each test below asserts BOTH
directions, and `test_rescue_gate_catches_trailing_comma_regression` is a direct
regression test for that false green: it reintroduces the greedy pattern and
requires the gate to stop detecting a contradiction it is looking straight at.
That test goes RED if the fix is reverted, which is the point of it.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("VIBEIC_REPO") or subprocess.run(
    ["git", "-C", HERE, "rev-parse", "--show-toplevel"],
    capture_output=True, text=True).stdout.strip()
if not REPO:
    sys.exit("test_gates: cannot locate the vibe-ic clone; set VIBEIC_REPO")

REF = os.environ.get("VIBEIC_REF", "origin/harvest/worktree-triage-jharvest")
ENV = {**os.environ, "VIBEIC_REPO": REPO, "VIBEIC_REF": REF}
FAILURES = []


def run(script, *args, source=None):
    """Run a gate (optionally from patched source) and return (rc, output)."""
    if source is None:
        path = os.path.join(HERE, script)
    else:
        fd, path = tempfile.mkstemp(suffix=".py")
        os.write(fd, source.encode())
        os.close(fd)
    p = subprocess.run([sys.executable, path, *args], capture_output=True,
                       text=True, env=ENV)
    if source is not None:
        os.unlink(path)
    return p.returncode, p.stdout + p.stderr


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def shard_files(tmp, rows_by_shard):
    for shard, rows in rows_by_shard.items():
        with open(os.path.join(tmp, f"verdicts_shard_{shard}.tsv"), "w") as fh:
            fh.write("path\tverdict\tevidence\n")
            for path, verdict in rows:
                fh.write(f"{path}\t{verdict}\tsynthetic row for the gate's own test\n")


GUARDED = "/home/reyerchu/_wt_1486"          # has a falselanded rescue ref on origin
UNGUARDED = "/home/reyerchu/_not_a_real_worktree_xyz"


# ---------------------------------------------------------------- rescue gate
def test_rescue_gate_both_directions():
    with tempfile.TemporaryDirectory() as tmp:
        shard_files(tmp, {"a": [(GUARDED, "LANDED")], "b": [(UNGUARDED, "LANDED")],
                          "c": [(UNGUARDED, "RECOVER")]})
        rc, out = run("rescue_contradiction.py", "--shard-dir", tmp)
        check("rescue gate FAILS when a guarded path is called LANDED",
              rc == 1 and "CONTRADICTION" in out, out[-300:])

        shard_files(tmp, {"a": [(GUARDED, "RECOVER")], "b": [(UNGUARDED, "LANDED")],
                          "c": [(UNGUARDED, "RECOVER")]})
        rc, out = run("rescue_contradiction.py", "--shard-dir", tmp)
        check("rescue gate PASSES when that same path is called RECOVER",
              rc == 0 and "CONTRADICTION" not in out, out[-300:])

        shard_files(tmp, {"a": [(GUARDED, "ABANDON")], "b": [(UNGUARDED, "LANDED")],
                          "c": [(UNGUARDED, "RECOVER")]})
        rc, out = run("rescue_contradiction.py", "--shard-dir", tmp)
        check("rescue gate FAILS on ABANDON too, not only LANDED", rc == 1, out[-300:])


def test_rescue_gate_catches_trailing_comma_regression():
    """The false green, pinned.

    Reintroduce the greedy `(\\S+)` and the gate stops seeing a contradiction it
    is staring at. This test goes RED if the fix is ever reverted.
    """
    src = open(os.path.join(HERE, "rescue_contradiction.py"), encoding="utf-8").read()
    broken = src.replace(r'r"uncommitted work in (\S+?)[,.;:]?(?:\s|$)"',
                         r'r"uncommitted work in (\S+)"')
    check("regression fixture actually differs from the shipped source",
          broken != src, "the pattern under test was not found -- fixture is stale")
    with tempfile.TemporaryDirectory() as tmp:
        shard_files(tmp, {"a": [(GUARDED, "LANDED")], "b": [(UNGUARDED, "LANDED")],
                          "c": [(UNGUARDED, "RECOVER")]})
        rc_fixed, _ = run("rescue_contradiction.py", "--shard-dir", tmp)
        rc_broken, out_broken = run(None, "--shard-dir", tmp, source=broken)
        check("shipped pattern DETECTS the contradiction", rc_fixed == 1)
        check("greedy pattern MISSES it — this is the false green being pinned",
              rc_broken == 0, f"broken build still failed; fixture no longer reproduces: {out_broken[-200:]}")


# ---------------------------------------------------------------- parity gate
def test_parity_gate_all_directions():
    real = subprocess.run(["git", "-C", REPO, "show",
                           f"{REF}:tools/harvest/verdicts_joined.tsv"],
                          capture_output=True, text=True).stdout
    if not real.strip():
        check("parity fixture: joined view readable", False, "could not read joined view")
        return
    with tempfile.TemporaryDirectory() as tmp:
        j_real = os.path.join(tmp, "j_real.tsv")
        open(j_real, "w").write(real)
        rc, out = run("joined_parity.py", "--joined", j_real)
        check("parity gate FAILS on the real files", rc == 1 and "disagree" in out)

        # rebuild the joined view so its verdict column agrees with every shard
        want = {}
        for shard in ("a", "b", "c"):
            body = subprocess.run(["git", "-C", REPO, "show",
                                   f"{REF}:tools/harvest/verdicts_shard_{shard}.tsv"],
                                  capture_output=True, text=True).stdout
            for ln in body.split("\n")[1:]:
                f = ln.split("\t")
                if len(f) >= 2 and f[0].startswith("/"):
                    want[f[0]] = f[1]
        out_lines = []
        for i, ln in enumerate(real.split("\n")):
            f = ln.split("\t")
            if i and len(f) > 2 and f[1] in want:
                f[2] = want[f[1]]
                ln = "\t".join(f)
            out_lines.append(ln)
        j_agree = os.path.join(tmp, "j_agree.tsv")
        open(j_agree, "w").write("\n".join(out_lines))
        rc, out = run("joined_parity.py", "--joined", j_agree)
        check("parity gate PASSES when the joined view is made to agree",
              rc == 0 and "OK:" in out, out[-300:])

        j_empty = os.path.join(tmp, "j_empty.tsv")
        open(j_empty, "w").write("")
        rc, out = run("joined_parity.py", "--joined", j_empty)
        check("parity gate REFUSES an empty joined view instead of reporting 0",
              rc == 1 and "parsed 0 paths" in out, out[-300:])


# -------------------------------------------------------------- contract check
def test_contract_check_shape_and_inputs():
    rc, out = run("contract_check.py", "c")
    check("contract check PASSES on shard c as pushed", rc == 0 and "CONTRACT OK" in out,
          out[-300:])
    for shard in ("a", "b"):
        rc, out = run("contract_check.py", shard)
        check(f"contract check does not fail shard {shard} for using another grammar",
              rc == 0, out[-400:])
    rc, out = run("contract_check.py", "zzz")
    check("contract check rejects a bad shard name", rc == 1 and "shard must be" in out)
    p = subprocess.run([sys.executable, os.path.join(HERE, "contract_check.py"), "c"],
                       capture_output=True, text=True,
                       env={**ENV, "VIBEIC_REF": "origin/no-such-branch-xyz"})
    check("contract check names an unresolvable ref instead of passing",
          p.returncode == 1 and "does not resolve" in (p.stdout + p.stderr))


for t in (test_rescue_gate_both_directions,
          test_rescue_gate_catches_trailing_comma_regression,
          test_parity_gate_all_directions,
          test_contract_check_shape_and_inputs):
    print(f"\n--- {t.__name__}")
    t()

print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all gate tests passed'}")
sys.exit(1 if FAILURES else 0)
