"""An empty corpus sweep must exit 2 AND that must reach the suite. vibe-ic#1025.

#1025 asked whether `step_internal_fail_bubble_up_check --corpus` is lie-shape
#2/#3 — a gate that walked nothing and returned rc 0. MEASURED on `origin/main`
@ `3febf5372`, it is not: the empty sweep exits 2, discloses `0 published run
tree(s)`, and `tools/ci/repo_hygiene_gates.sh` dispatches it through `run`,
whose rc-2 branch is a FAIL. Both halves were already correct.

So this file is not a repair. It is the reason that answer stays true, and
#1028 is why it is worth pinning now rather than later: that PR withdraws all
14 published run roots under `benchmark-data/ic/`, so the EMPTY corpus stops
being a corner case and becomes the STEADY STATE for every consumer. From then
on, every one of the properties below is exercised on every single run — and
until this file existed, not one of them was asserted anywhere.

WHAT IS PINNED, AND WHAT EACH ONE COSTS IF IT DRIFTS
----------------------------------------------------
1. the gate's rc on an empty corpus (2, not 0), and that it PRINTS the zero
   denominator rather than merely returning a code. MEASURED counterfactual:
   with that `return 2` flipped to `return 0`, the dispatcher prints
   `repo_hygiene_gates: all 1 gate(s) passed` over a sweep that read nothing;
2. the WRAPPER on the dispatch line. `run` blocks on rc 2; the sibling
   `run_tolerating_uncheckable` records NOT_CHECKED and the suite exits 0.
   MEASURED counterfactual, same gate and same empty corpus, wrapper swapped:

       run                          -> ^^ FAILED               suite rc 1
       run_tolerating_uncheckable   -> ^^ NOT CHECKED          suite rc 0

   A one-token edit on one line moves this gate between blocking and decorative
   — lie-shape #7, wired where it can never block — and the honest-looking
   `this is NOT a pass over: step FAIL bubbles up` still prints in the rc-0
   case, so the log does not read as a regression;
3. the POSITIVE arm: a non-empty corpus that should pass still passes, and a
   non-empty corpus carrying a NEW unacknowledged FAIL is still rc 1. Without
   these two, the file above them would be satisfied by a gate that refuses
   everything — a ban rather than a check (lie-shape #5).

The corpus fixtures are built here rather than read from `benchmark-data/`,
precisely because #1028 is about to empty it. A guard whose positive arm needs
the corpus to be non-empty would go NOT CHECKED in exactly the state it exists
to watch.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
GATE = PLUGIN / "programs" / "step_internal_fail_bubble_up_check.py"
ROOT = PLUGIN.parent.parent.parent
HYGIENE = ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"

# `run` blocks on any non-zero; `run_writing_the_corpus` differs only in the
# corpus-write guard, not in its rc handling. `run_tolerating_uncheckable` is
# the one that converts rc 2 into a non-fatal NOT_CHECKED.
_BLOCKS_ON_RC2 = {"run", "run_writing_the_corpus"}
_TOLERATES_RC2 = {"run_tolerating_uncheckable"}


def _gate(*args):
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True, timeout=55)


def _corpus(root, ic="an_ic", run="clean_run_v0000_20200101", reports=None):
    """A corpus shaped like the real one: <corpus>/<ic>/clean_run_*/reports/*.

    Outside a git repository `_published_run_trees` falls back to the disk, so
    no repo is needed to exercise the sweep.
    """
    tree = root / ic / run / "reports"
    tree.mkdir(parents=True)
    for name, verdict in (reports or {}).items():
        (tree / f"{name}.json").write_text(
            json.dumps({"verdict": verdict, "tool": "test"}))
    return root


def _baseline(path, n):
    path.write_text(json.dumps({"findings_total": n}) + "\n")
    return path


# ---------------------------------------------------------------------------
# 1. the gate half — rc 2, and the denominator DISCLOSED
# ---------------------------------------------------------------------------
def test_empty_corpus_exits_2_and_discloses_the_zero_denominator(tmp_path):
    empty = tmp_path / "corpus"
    empty.mkdir()
    res = _gate("--corpus", str(empty))
    assert res.returncode == 2, (
        "a sweep that walked nothing must not share an exit code with a sweep "
        f"that walked everything and found nothing. rc={res.returncode}\n"
        f"{res.stdout}{res.stderr}")
    # rc alone is not the bar. #1025 asks for the count to be SAID, because
    # `0 trees` is only recognisable as absurd when something emits it.
    assert "0 published run tree(s)" in res.stdout, (
        f"the zero denominator was not disclosed:\n{res.stdout}")
    assert "examined nothing" in res.stdout, res.stdout


def test_absent_corpus_directory_also_exits_2(tmp_path):
    """#1028's other steady state: git does not track an empty directory, so
    once the last run root under `benchmark-data/ic/` is withdrawn the path may
    not exist at all. That must not be quieter than an empty one."""
    res = _gate("--corpus", str(tmp_path / "gone"))
    assert res.returncode == 2, (
        f"rc={res.returncode} for a corpus that is not a directory\n"
        f"{res.stdout}{res.stderr}")


# ---------------------------------------------------------------------------
# 2. the caller half — the wrapper, and what the wrapper actually does
# ---------------------------------------------------------------------------
def _dispatch_statements(script_text):
    """Yield (wrapper, whole-statement) for every gate dispatch in the script.

    Continuations are joined: the per-cell project-mode dispatch spans two
    lines, and a line-by-line reader attributes its wrapper to the wrong text.
    """
    out, cur, wrapper = [], None, None
    for raw in script_text.splitlines():
        line = raw.rstrip("\n")
        head = line.strip().split(" ", 1)[0]
        if cur is None and (head in _BLOCKS_ON_RC2 or head in _TOLERATES_RC2):
            wrapper, cur = head, line.strip()
        elif cur is not None:
            cur += " " + line.strip()
        if cur is not None and not cur.rstrip().endswith("\\"):
            out.append((wrapper, cur.replace("\\", " ")))
            cur, wrapper = None, None
    return out


def test_the_corpus_sweep_is_dispatched_by_a_wrapper_that_blocks_on_rc_2():
    stmts = [(w, s) for w, s in _dispatch_statements(HYGIENE.read_text())
             if "step_internal_fail_bubble_up_check.py" in s and "--corpus" in s]
    assert len(stmts) == 1, (
        f"expected exactly one corpus-mode dispatch, found {len(stmts)}: "
        f"{[s for _, s in stmts]}")
    wrapper, stmt = stmts[0]
    assert wrapper in _BLOCKS_ON_RC2, (
        f"the corpus sweep is dispatched by `{wrapper}`, which tolerates rc 2. "
        "After #1028 the corpus is empty on every run, so this gate returns 2 "
        "on every run — under a tolerating wrapper it would be recorded "
        "NOT_CHECKED and the suite would exit 0 forever, which is the state "
        "this gate exists to refuse.\n"
        f"  {stmt}")


def _suite(tmp_path, wrapper, rc):
    """Dispatch a stub of exit code `rc` through the REAL dispatcher."""
    stub = tmp_path / f"stub{rc}.sh"
    stub.write_text(f"#!/usr/bin/env bash\nexit {rc}\n")
    stub.chmod(0o755)
    harness = tmp_path / f"harness_{wrapper}_{rc}.sh"
    # vibe-ic#584 — a tolerating wrapper must BUY the tolerance with a dated,
    # reasoned `uncheckable_until`; wired without one it is a WIRING ERROR
    # (rc 2) rather than a NOT_CHECKED. Emitted ONLY for the tolerating
    # spelling, so this helper still builds the two harnesses that differ in
    # exactly the way the pair below is about. Both assertions are unchanged:
    # `run` still reddens rc 2, the tolerating wrapper still passes it. Without
    # the line the control would be measuring the missing exemption instead of
    # the wrapper, which is not what it was written to pin.
    buy = ('uncheckable_until 2999-01-01 "fixture: the stub stands in for a '
           'gate that cannot look"\n'
           if wrapper in _TOLERATES_RC2 else "")
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"source {DISPATCH}\n"
        f"{buy}"
        f'{wrapper} "a corpus sweep" "{tmp_path}" bash "{stub}"\n'
        "gate_dispatch_finish\n")
    return subprocess.run(["bash", str(harness)], capture_output=True,
                          text=True, cwd=str(tmp_path), timeout=55)


def test_the_dispatcher_fails_the_suite_on_rc_2_from_a_blocking_wrapper(tmp_path):
    """The assertion above is only worth making because of this one: `run` is
    what converts the gate's honest 2 into a red suite."""
    res = _suite(tmp_path, "run", 2)
    assert res.returncode == 1, (
        f"rc 2 under `run` did not fail the suite (rc={res.returncode})\n"
        f"{res.stdout}{res.stderr}")
    assert "FAILED" in res.stderr, res.stderr


def test_the_tolerating_wrapper_would_pass_the_same_rc_2(tmp_path):
    """The control for the pair. If this ALSO failed the suite, the wrapper
    assertion would be pinning nothing — both spellings would be blocking and
    the token on line 550 would not matter."""
    res = _suite(tmp_path, "run_tolerating_uncheckable", 2)
    assert res.returncode == 0, (
        f"expected the tolerating wrapper to pass rc 2 (rc={res.returncode})\n"
        f"{res.stdout}{res.stderr}")
    assert "NOT CHECKED" in res.stderr, res.stderr


# ---------------------------------------------------------------------------
# 3. the positive arm — this is a CHECK, not a ban (lie-shape #5)
# ---------------------------------------------------------------------------
def test_a_nonempty_corpus_that_should_pass_still_passes(tmp_path):
    corpus = _corpus(tmp_path / "corpus", reports={"lvs": "PASS",
                                                   "drc": "PASS"})
    res = _gate("--corpus", str(corpus),
                "--baseline", str(_baseline(tmp_path / "bl.json", 0)))
    assert res.returncode == 0, (
        f"a clean non-empty corpus must pass. rc={res.returncode}\n"
        f"{res.stdout}{res.stderr}")
    assert "1 published run tree(s)" in res.stdout, res.stdout
    assert "1 with a reports/ tree" in res.stdout, res.stdout


def test_a_nonempty_corpus_with_a_new_unacknowledged_fail_is_rc_1(tmp_path):
    """The other half of the positive arm: passing on a clean corpus is only
    meaningful if a dirty one still reddens. Otherwise the arm above is
    satisfied by a gate that has stopped looking."""
    corpus = _corpus(tmp_path / "corpus", reports={"lvs": "FAIL"})
    res = _gate("--corpus", str(corpus),
                "--baseline", str(_baseline(tmp_path / "bl.json", 0)))
    assert res.returncode == 1, (
        f"an unacknowledged FAIL above the baseline must be rc 1. "
        f"rc={res.returncode}\n{res.stdout}{res.stderr}")
    assert "GREW" in res.stdout, res.stdout
