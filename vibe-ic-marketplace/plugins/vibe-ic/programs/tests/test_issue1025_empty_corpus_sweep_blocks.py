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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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
    return _pr.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True)


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
    # `previous_findings_total: None` spells FIRST WRITE — the register states
    # that it moved from nothing, which is what `--write-baseline` records the
    # first time it runs. The key being ABSENT is a different fact (vibe-ic#1704:
    # a register no writer that records provenance ever touched), and the gate
    # answers NOT DETERMINED to it. These fixtures are about the sweep, so they
    # declare the honest first-write form rather than the undecidable one.
    path.write_text(json.dumps({"findings_total": n,
                                "previous_findings_total": None,
                                "previous_runs_swept": None,
                                "previous_runs_with_reports": None}) + "\n")
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
    # vibe-ic#1025 follow-up — a SECOND gate that DECIDES, and it is the
    # fixture that needed it, not the assertions. `gate_dispatch_finish` now
    # refuses a run in which NO gate reached a verdict (rc 2), so a sweep whose
    # ONLY gate is the tolerated refusal is vacuous BY CONSTRUCTION: both
    # spellings would come back non-zero and the pair below would be comparing
    # two vacuous sweeps instead of two wrappers. With a deciding gate present
    # the aggregate rc is once again a fact about the WRAPPER, which is the
    # only thing this pair was ever written to pin — and it is also the shape
    # the real sweep has, where this gate is one of 63.
    decides = tmp_path / "decides.sh"
    decides.write_text("#!/usr/bin/env bash\necho 'PASS (1 item examined)'\n")
    decides.chmod(0o755)
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"source {DISPATCH}\n"
        f'run "a gate that decided" "{tmp_path}" bash "{decides}"\n'
        f"{buy}"
        f'{wrapper} "a corpus sweep" "{tmp_path}" bash "{stub}"\n'
        "gate_dispatch_finish\n")
    return _pr.run(["bash", str(harness)], capture_output=True,
                          text=True, cwd=str(tmp_path))


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


# ---------------------------------------------------------------------------
# 4. what the WRAPPER on the real line still has to buy (vibe-ic#1025, 2026-08-28)
#
# The wrapper assertion above pins a TOKEN. These pin the PROPERTY that token
# exists to protect, measured against the gate's actual exit codes rather than
# against the ones the 2026-08-25 landing believed it had.
#
# THE MEASUREMENT THAT MOTIVATES THEM. `--corpus-may-be-absent` has been on the
# real dispatch line since bd3c3a4c3 (2026-08-17), and it splits two facts that
# used to share rc 2:
#
#     corpus ABSENT (moved to its own repo in v1.10.56)   -> rc 0, NO_CORPUS
#     pointer SET AND WRONG                               -> rc 2
#     corpus present but not a git checkout               -> rc 2
#     --write-baseline with no corpus                     -> rc 2  (the #1025
#                                                             destruction refusal)
#
# So EVERY rc 2 this gate can still emit is a state that must block, and the
# one state a tolerating wrapper was bought for does not produce rc 2 at all.
# That is the whole content of the wrapper question, and until these existed
# nothing asserted it — which is how a wrapper could be swapped in the belief
# that it covered "the corpus is gone" while what it actually covered was
# "somebody's pointer is broken" and "a write that would destroy the register".
# ---------------------------------------------------------------------------
def _gate_env(*args, env=None):
    """`_gate`, but with VIBE_IC_BENCHMARK_DATA under the test's control.

    The pointer is READ from the ambient environment, so a host that happens to
    export it turns the NO_CORPUS assertions below into UNDETERMINED ones and
    the file would pass or fail for a reason that is not about this repo.
    """
    import os
    e = dict(os.environ)
    e.pop("VIBE_IC_BENCHMARK_DATA", None)
    e.update(env or {})
    return _pr.run([sys.executable, str(GATE), *args],
                   capture_output=True, text=True, env=e)


def _said(res):
    """Everything the gate emitted, both streams.

    The NO_CORPUS banners go to stderr while the NOT_EXAMINED ones a few
    assertions up go to stdout. Which stream carries a sentence is an
    incidental of the branch that prints it; that the sentence is SAID AT ALL
    is the property these assertions are about, so pinning the stream would be
    pinning the wrong half.
    """
    return res.stdout + res.stderr


def _wired_wrapper():
    """The wrapper the corpus sweep is ACTUALLY dispatched by, on this tree."""
    stmts = [(w, s) for w, s in _dispatch_statements(HYGIENE.read_text())
             if "step_internal_fail_bubble_up_check.py" in s and "--corpus" in s]
    assert len(stmts) == 1, f"expected exactly one corpus-mode dispatch: {stmts}"
    return stmts[0][0]


def test_a_pointer_that_is_set_and_wrong_is_rc_2_and_says_it_is_not_excused(
        tmp_path):
    """rc 2 #1 of 3. The gate REFUSES to let `--corpus-may-be-absent` cover a
    broken pointer, and says so in words. If this ever became rc 0, a CI host
    with a stale export would sweep nothing and be recorded as having swept."""
    res = _gate_env("--corpus", str(tmp_path / "unused"),
                    "--corpus-may-be-absent",
                    env={"VIBE_IC_BENCHMARK_DATA": str(tmp_path / "gone")})
    assert res.returncode == 2, (
        f"a pointer set and wrong must not be excused. rc={res.returncode}\n"
        f"{res.stdout}{res.stderr}")
    assert "UNDETERMINED" in _said(res), _said(res)
    assert "--corpus-may-be-absent does not excuse it" in _said(res), _said(res)


def test_write_baseline_with_no_corpus_is_refused_at_rc_2(tmp_path):
    """rc 2 #2 of 3, and it is THE #1025 destruction. `--write-baseline` over a
    corpus that was never opened would record `findings_total=0` as a
    measurement and lose the reference point. The register is copied to
    tmp_path first, so a regression that stopped refusing cannot damage the
    real one while proving that it stopped."""
    real = GATE.parent / "step_internal_fail_bubble_up_baseline.json"
    bl = tmp_path / "baseline.json"
    bl.write_text(real.read_text())
    before = bl.read_text()
    res = _gate_env("--corpus", str(tmp_path / "gone"), "--corpus-may-be-absent",
                    "--baseline", str(bl), "--write-baseline")
    assert res.returncode == 2, (
        f"a write from a scan that did not happen must be refused. "
        f"rc={res.returncode}\n{res.stdout}{res.stderr}")
    assert "REFUSED" in res.stderr, res.stderr
    assert bl.read_text() == before, "the register was rewritten anyway"


def test_the_no_corpus_pass_must_say_that_nothing_was_measured(tmp_path):
    """The rc-0 arm is only honest because it is LOUD. A silent 0 here is
    indistinguishable from a sweep that read fourteen cells and found them
    clean, which is the exact confusion #1025 was filed about."""
    res = _gate_env("--corpus", str(tmp_path / "gone"), "--corpus-may-be-absent")
    assert res.returncode == 0, (
        f"an absent corpus is opted-in NO_CORPUS, not a failure. "
        f"rc={res.returncode}\n{res.stdout}{res.stderr}")
    assert "NO_CORPUS" in _said(res), _said(res)
    assert "0 published run tree(s)" in _said(res), _said(res)
    assert "NOT RE-MEASURED" in _said(res), _said(res)


def test_the_wired_wrapper_still_blocks_a_real_finding_at_rc_1(tmp_path):
    """rc 1 is the gate LOOKING AND FINDING A DEFECT — an unacknowledged FAIL,
    or a register whose counts fell with nobody on record. It must fail the
    suite under whatever wrapper this tree actually uses. This holds for every
    wrapper in the file today, and it is the assertion that stays true if the
    dispatch line is ever legitimately re-spelled."""
    res = _suite(tmp_path, _wired_wrapper(), 1)
    assert res.returncode == 1, (
        f"rc 1 under `{_wired_wrapper()}` did not fail the suite "
        f"(rc={res.returncode})\n{res.stdout}{res.stderr}")
    assert "FAILED" in res.stderr, res.stderr


def test_the_wired_wrapper_still_blocks_every_rc_2_this_gate_can_emit(tmp_path):
    """The assertion that would have caught the 2026-08-25 landing.

    It does not name a token. It asks the only question that matters: of the
    states this gate can actually reach, is there one it refuses in and the
    suite shrugs at? Because `--corpus-may-be-absent` already routed the absent
    corpus to rc 0, every REMAINING rc 2 is a broken configuration or a refused
    destruction — so a wrapper that tolerates rc 2 is tolerating exactly those,
    and nothing else."""
    res = _suite(tmp_path, _wired_wrapper(), 2)
    assert res.returncode == 1, (
        f"the corpus sweep is dispatched by `{_wired_wrapper()}`, under which "
        f"rc 2 does not fail the suite (rc={res.returncode}).\n"
        "Every rc 2 this gate can still emit is a MUST-BLOCK state: a pointer "
        "that is set and wrong, a corpus that is not a git checkout, and "
        "`--write-baseline` refusing to record findings_total=0 as a "
        "measurement. The absent corpus — the one state a tolerance would be "
        "bought for — exits 0 and needs none.\n"
        f"{res.stdout}{res.stderr}")
