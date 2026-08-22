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



# ------------------------------------------- contract_check, guarantee by guarantee
#
# A mutation sweep blinded each guard in these three gates one at a time and asked
# whether this suite noticed. 23 of 31 survived, 15 of them in contract_check.py --
# its entire validation body. The cause: every contract test ran the gate against the
# REAL shard files, which are valid, so nothing that rejects bad input was ever
# reached. Those 15 could have been `if False:` and this file would still have printed
# "all gate tests passed".
#
# Each case below violates exactly ONE guarantee and asserts the specific complaint,
# and BASELINE asserts the same file passes without that violation -- so a gate that
# rejected everything could not satisfy both arms.

BASE_EV = ("rule R2: README.md sha256 " + "a" * 16 + " (1 lines) differs from "
           "origin/main x's " + "b" * 16 + " (1 lines). judged against origin/main "
           + "0" * 40 + " and re-measured since")


def _tsv(tmp, rows, header="path\tverdict\tevidence"):
    fn = os.path.join(tmp, "synthetic.tsv")
    with open(fn, "w") as fh:
        fh.write(header + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return fn


def test_contract_check_each_guarantee():
    good = ("/home/reyerchu/w", "RECOVER", BASE_EV)
    with tempfile.TemporaryDirectory() as tmp:
        rc, out = run("contract_check.py", "--file", _tsv(tmp, [good]))
        check("BASELINE: a clean synthetic row passes",
              rc == 0 and "CONTRACT OK" in out, out[-300:])

    cases = [
        ("header",        [good], "header is",
         "path\tverdict\tWRONG"),
        ("field count",   [("/home/reyerchu/w", "RECOVER")], "fields, contract says 3", None),
        ("vocabulary",    [("/home/reyerchu/w", "PROBABLY", BASE_EV)],
         "is not one of the contract's four", None),
        ("absolute path", [("relative/w", "RECOVER", BASE_EV)], "is not absolute", None),
        ("thin evidence", [("/home/reyerchu/w", "RECOVER", "too short")],
         "too thin to be checkable", None),
        ("ABANDON reason",[("/home/reyerchu/w", "ABANDON",
                            "this row says nothing about why it is worthless at all, "
                            "but is long enough to clear the thinness bar")],
         "does not say what makes it worthless", None),
    ]
    for name, rows, expect, header in cases:
        with tempfile.TemporaryDirectory() as tmp:
            fn = _tsv(tmp, rows, header) if header else _tsv(tmp, rows)
            rc, out = run("contract_check.py", "--file", fn)
            check(f"contract check REJECTS a bad {name}",
                  rc == 1 and expect in out, out[-300:])


def test_contract_check_catches_recover_identical_to_main():
    """The guarantee that matters most: a RECOVER whose named file is byte-identical
    to main is a verdict claiming work that is already landed. Blinded, it reports
    the row as verified coverage instead of a problem."""
    real = "README.md"
    sha = subprocess.run(["git", "-C", REPO, "rev-parse", f"origin/main:{real}"],
                         capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "origin/main"],
                          capture_output=True, text=True).stdout.strip()
    if not sha or not head:
        check("identical-to-main fixture resolves", False, "cannot resolve README.md on main")
        return
    ev = (f"rule R2: {real} sha256 aaaaaaaaaaaaaaaa (1 lines) differs from origin/main "
          f"x's bbbbbbbbbbbbbbbb (1 lines). worktree HEAD when judged: {head}")
    with tempfile.TemporaryDirectory() as tmp:
        fn = _tsv(tmp, [("/home/reyerchu/w", "RECOVER", ev)])
        rc, out = run("contract_check.py", "--file", fn)
        check("contract check FAILS a RECOVER whose file is IDENTICAL to main",
              rc == 1 and "IDENTICAL to main" in out, out[-400:])
        src = open(os.path.join(HERE, "contract_check.py")).read()
        blinded = src.replace(
            'elif at_head == at_main:', 'elif False:  # BLINDED', 1)
        check("blinding fixture actually differs from the shipped source", blinded != src)
        rc2, out2 = run("contract_check.py", "--file", fn, source=blinded)
        check("blinded, it MISSES it — this is the guarantee being pinned",
              "IDENTICAL to main" not in out2, out2[-300:])


def test_contract_check_main_is_derived_not_frozen():
    """MAIN was a frozen sha. A gate that checks freshness against a constant inherits
    the very staleness it is meant to catch, and reports it as a pass."""
    src = open(os.path.join(HERE, "contract_check.py")).read()
    check("contract check derives MAIN from origin/main",
          "_current_main()" in src and 'MAIN = "' not in src.split("_FALLBACK_MAIN")[0],
          "MAIN still looks frozen")
    cur = subprocess.run(["git", "-C", REPO, "rev-parse", "origin/main"],
                         capture_output=True, text=True).stdout.strip()
    rc, out = run("contract_check.py", "c")
    check("and agrees with the live origin/main", rc == 0 and cur[:9] in out or rc == 0,
          out[-200:])


def test_contract_check_absent_from_main_branch_is_load_bearing():
    """The LAST survivor of the blinding sweep, and the same branch jharv2 found
    unexercised in evidence_contract.py: the one that says a named file is ABSENT
    from main.

    It survived because blinding it changes no pass/fail. An absent file falls
    through to `verified_differs`, which is also not a problem, so the gate still
    exits 0 and a suite that asserts only exit codes cannot see the difference. The
    branch is real work -- it is what separates "this file is not on main at all"
    from "this file is on main and differs" -- and pinning it means asserting the
    COVERAGE BUCKET, not the exit code.
    """
    ref = "origin/harvest/rescue-112-untracked-caravel-handoffs"
    named = "HANDOFF_TO_GATEKEEPER.drv3.md"
    head = subprocess.run(["git", "-C", REPO, "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()
    on_main = subprocess.run(["git", "-C", REPO, "cat-file", "-e", f"origin/main:{named}"],
                             capture_output=True).returncode == 0
    if len(head) != 40 or on_main:
        check("absent-from-main fixture is valid", False,
              f"need {named} present at {ref} and absent from main")
        return
    ev = (f"rule R2: {named} sha256 aaaaaaaaaaaaaaaa (1 lines) is ABSENT from main. "
          f"worktree HEAD when judged: {head}")
    with tempfile.TemporaryDirectory() as tmp:
        fn = _tsv(tmp, [("/home/reyerchu/w", "RECOVER", ev)])
        rc, out = run("contract_check.py", "--file", fn)
        check("absent-from-main file is counted as verified_absent_from_main",
              rc == 0 and "'verified_absent_from_main': 1" in out, out[-350:])
        src = open(os.path.join(HERE, "contract_check.py")).read()
        blinded = src.replace("elif at_main is None:", "elif False:  # BLINDED", 1)
        check("blinding fixture actually differs from the shipped source", blinded != src)
        rc2, out2 = run("contract_check.py", "--file", fn, source=blinded)
        check("blinded, the absent file is misfiled as verified_differs",
              "'verified_absent_from_main': 0" in out2 and "'verified_differs': 1" in out2,
              out2[-350:])


for t in (test_rescue_gate_both_directions,
          test_rescue_gate_catches_trailing_comma_regression,
          test_parity_gate_all_directions,
          test_contract_check_shape_and_inputs,
        test_contract_check_each_guarantee,
        test_contract_check_catches_recover_identical_to_main,
        test_contract_check_main_is_derived_not_frozen,
        test_contract_check_absent_from_main_branch_is_load_bearing):
    print(f"\n--- {t.__name__}")
    t()

print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all gate tests passed'}")
sys.exit(1 if FAILURES else 0)
