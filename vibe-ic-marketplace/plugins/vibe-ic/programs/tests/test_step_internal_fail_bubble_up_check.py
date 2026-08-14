"""Tests for step_internal_fail_bubble_up_check.py (v1.6.44)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "programs"))

import step_internal_fail_bubble_up_check as g  # noqa: E402


def _proj(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "phase3").mkdir(parents=True)
    return p


def _write_report(p: Path, name: str, verdict: str,
                  subdir: str = "phase3") -> Path:
    rp = p / "reports" / subdir / f"{name}.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": verdict, "tool": "test"}))
    return rp


def _write_waivers(p: Path, entries):
    (p / "waivers.json").write_text(json.dumps({
        "_doc": "test waivers",
        "waived_steps": entries,
    }))


def test_no_reports_tree_is_NOT_EXAMINED(tmp_path):
    """Nothing to look at is not a clean result. Through v1.9.62 this returned
    VACUOUS_PASS and the CLI exited 0 for it — the same exit code as a run that
    read 68 reports and found every FAIL acknowledged."""
    p = tmp_path / "empty"
    p.mkdir()
    verdict, findings, examined = g.audit(p)
    assert verdict == "NOT_EXAMINED"
    assert examined == 0


def test_reports_read_and_none_failing_is_a_REAL_pass(tmp_path):
    """The property genuinely holds here, over a population of 1. Calling it
    VACUOUS_PASS put it in the same class as "there was nothing to look at",
    and the denominator that separates the two was never reported."""
    p = _proj(tmp_path)
    _write_report(p, "foo", "PASS")
    verdict, findings, examined = g.audit(p)
    assert verdict == "PASS"
    assert examined == 1


def test_fail_when_no_waiver_no_bubble(tmp_path):
    """The escape this gate exists to catch."""
    p = _proj(tmp_path)
    _write_report(p, "lvs", "FAIL")
    verdict, findings, examined = g.audit(p)
    assert verdict == "FAIL"
    assert findings[0].rule == "STEP_FAIL_NOT_BUBBLED"
    assert "lvs" in findings[0].report_file


def test_pass_when_waiver_mentions_name(tmp_path):
    """The standard happy path: waiver text references the gate name."""
    p = _proj(tmp_path)
    _write_report(p, "lvs", "FAIL")
    _write_waivers(p, [{
        "id": 29,
        "reason": "LVS deferred to Calibre",
        "ticket": "BACKLOG-step29-lvs",
        "evidence": "no LVS artefact",
    }])
    verdict, findings, examined = g.audit(p)
    assert verdict == "PASS", findings


def test_pass_when_bubble_up_records_fail(tmp_path):
    """Even without a waiver, an orchestrator record naming the FAIL
    is enough — overall verdict reflects the failure."""
    p = _proj(tmp_path)
    _write_report(p, "antenna", "FAIL")
    odir = p / "reports" / "orchestrator"
    odir.mkdir(parents=True)
    (odir / "phase3_one_shot.json").write_text(json.dumps({
        "summary": "antenna gate FAIL — see reports/phase3/antenna.json",
        "verdict": "FAIL",
    }))
    verdict, findings, examined = g.audit(p)
    assert verdict == "PASS", findings


def test_neutral_verdicts_skipped(tmp_path):
    """INSUFFICIENT_DATA, FALLBACK, SKELETON_EMITTED, WAIVED do not
    trigger the gate — they're orthogonal to bubble-up enforcement."""
    p = _proj(tmp_path)
    for v in ("INSUFFICIENT_DATA", "FALLBACK", "SKELETON_EMITTED",
              "WAIVED"):
        _write_report(p, f"r_{v.lower()}", v)
    verdict, findings, examined = g.audit(p)
    assert verdict == "PASS"
    assert examined == 4, "each neutral report was READ; it is skipped, not unseen"


def test_audit_dir_excluded(tmp_path):
    """reports/audit/ files are human-authored; gate must not flag
    their `verdict: FAIL` as escapes."""
    p = _proj(tmp_path)
    audit_dir = p / "reports" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "human_review.json").write_text(json.dumps({
        "verdict": "FAIL",
        "reviewer": "human",
    }))
    verdict, findings, examined = g.audit(p)
    assert verdict == "NOT_EXAMINED", (
        "the only verdict-bearing file is the excluded human review, so this "
        "project genuinely has nothing in scope — and must not read as clean")
    assert examined == 0


def test_waiver_matches_via_step_id(tmp_path):
    """Waiver `id: 29` matches reports referencing `step29` / step-29
    via the `step{id}` corpus expansion."""
    p = _proj(tmp_path)
    rp = p / "reports" / "phase3" / "step29.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"verdict": "FAIL"}))
    _write_waivers(p, [{
        "id": 29,
        "reason": "deferred",
        "ticket": "T-29",
        "evidence": "x",
    }])
    verdict, findings, examined = g.audit(p)
    assert verdict == "PASS", findings


def test_short_candidates_filtered(tmp_path):
    """Two-letter parent dirs / stem fragments must NOT cause spurious
    matches against random corpus text."""
    p = _proj(tmp_path)
    # "em.json" stem split would yield "em" (2 chars) — but we keep
    # the full stem candidate "em" (2 chars) intentionally below the
    # 3-char minimum, so it must NOT match "memory" in waiver text.
    _write_report(p, "em", "FAIL")
    _write_waivers(p, [{
        "id": 99,
        "reason": "memory leak deferred",
        "ticket": "X",
        "evidence": "y",
    }])
    verdict, findings, examined = g.audit(p)
    # Should FAIL — `em` is too short to match anything reliably.
    assert verdict == "FAIL"
    assert findings[0].rule == "STEP_FAIL_NOT_BUBBLED"


# --- the CLI layer: the gate had, one layer up, the defect it exists to catch

def _cli():
    import step_internal_fail_bubble_up_check as M
    return M


def test_an_unacknowledged_fail_exits_1(tmp_path, monkeypatch):
    """THE point of this file.

    Every test above drives `audit()` and asserts on the VERDICT. None of them
    touches `main()`, so the verdict -> exit-code mapping was unmeasured — and
    the flow reads the exit code, not the verdict. `gate_cli_mutation_probe`
    neutered the CLI so it could never return non-zero and all nine passed.

    Which makes this gate the plainest example in the repo of a checker
    exhibiting the defect it checks for: its subject is an inner FAIL that never
    reaches the outer exit code, and that is exactly what it had.
    """
    M = _cli()
    from dataclasses import dataclass

    @dataclass
    class F:
        rule: str = "unacknowledged"
        report_file: str = "reports/step07/lint.json"
        verdict: str = "FAIL"
        detail: str = ""
    monkeypatch.setattr(M, "audit", lambda proj: ("FAIL", [F()], 7))
    assert M.main([str(tmp_path)]) == 1


def test_pass_exits_0(tmp_path, monkeypatch):
    """…or the test above is met by a gate that always returns 1."""
    M = _cli()
    monkeypatch.setattr(M, "audit", lambda proj: ("PASS", [], 7))
    assert M.main([str(tmp_path)]) == 0


def test_nothing_examined_exits_2_not_0(tmp_path, monkeypatch):
    """This test used to assert the OPPOSITE, one line above the test below
    that states the rule it broke:

        "VACUOUS_PASS means nothing was examined. It exits 0 deliberately."
        "\"I could not look\" must never share an exit code with \"I looked
         and it was clean\""

    Both were in this file at once. The first is the defect the second names,
    and a step that crashed before writing any report produced exactly it.
    """
    M = _cli()
    monkeypatch.setattr(M, "audit", lambda proj: ("NOT_EXAMINED", [], 0))
    assert M.main([str(tmp_path)]) == 2


def test_a_missing_project_dir_is_rc_2_not_rc_0(tmp_path):
    """"I could not look" must never share an exit code with "I looked and it
    was clean" — the absence-renders-as-a-pass shape this repo keeps finding."""
    M = _cli()
    assert M.main([str(tmp_path / "no-such-project")]) == 2


# ── the corpus sweep must not depend on how the caller spells the root (#1025) ──
def _corpus_tree(root):
    """Two ICs, each with a `clean_run_*` tree, at the depth the real corpus uses:
    <corpus>/ic/<IC>/clean_run_*/ — i.e. TWO levels below the corpus root, not one."""
    for ic, n in (("alpha", "clean_run_v1_20200101"), ("beta", "clean_run_v2_20200101")):
        d = root / "ic" / ic / n / "reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / "some_gate.json").write_text('{"verdict": "PASS"}', encoding="utf-8")
    return root


def test_the_sweep_reaches_the_same_trees_however_the_root_is_spelled(tmp_path):
    """vibe-ic#1025. `_published_run_trees` globbed `*/clean_run_*` — run trees
    exactly ONE level below the root. Real trees sit TWO levels down
    (`ic/<IC>/clean_run_*`), so `--corpus benchmark-data` reached NOTHING while
    `--corpus benchmark-data/ic` reached everything.

    MEASURED on the real corpus at the commit this was fixed:

        --corpus benchmark-data     ->  0 tree(s), VACUOUS_PASS, rc 2
        --corpus benchmark-data/ic  -> 13 tree(s), 5 unacknowledged FAIL(s)

    Same repo, same commit, same question; the answer depended on how many path
    components the caller typed. This asserts the two agree.
    """
    import step_internal_fail_bubble_up_check as M
    root = _corpus_tree(tmp_path / "bd")
    outer = M._published_run_trees(root)
    inner = M._published_run_trees(root / "ic")
    assert len(outer) == 2, [str(p) for p in outer]
    assert {p.name for p in outer} == {p.name for p in inner}


def test_a_narrower_root_still_narrows_the_population(tmp_path):
    """THE PAIRED GUARD. The fix must not turn the root argument into a no-op:
    pointing at ONE IC must still sweep only that IC. A depth-insensitive search
    that ignores where it was pointed would pass the test above and be useless."""
    import step_internal_fail_bubble_up_check as M
    root = _corpus_tree(tmp_path / "bd")
    one = M._published_run_trees(root / "ic" / "alpha")
    assert len(one) == 1, [str(p) for p in one]
    assert one[0].name == "clean_run_v1_20200101"

import subprocess
PROG = Path(__file__).resolve().parents[1] / 'step_internal_fail_bubble_up_check.py'



# ── #1025: a paid debt that stays on the register is slack, not a pass ───────

def _fail_report(root, ic: str, run: str, name: str):
    d = root / "ic" / ic / run / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(
        json.dumps({"program": name, "verdict": "FAIL",
                    "detail": "unacknowledged"}) + "\n", encoding="utf-8")


#: Every inner subprocess bound in this file. MEASURED, not tuned (#1241).
#:
#: The harness runs pytest at `--timeout=180` and kills the SESSION, not the
#: test, so any inner bound above the per-call ceiling of 60s (= 180 // 3, a
#: figure `ci_harness_timeout_ceiling_check` DERIVES from the workflows rather
#: than a convention) is a promise the harness will not keep: the session dies
#: first and takes every other test with it.
#:
#: The number comes from a run, not from picking something comfortably small:
#: the whole 19-test file completes in 1.03s and its slowest test is 0.17s
#: (`test_the_shipped_register_agrees_with_the_shipped_corpus`, the only one
#: that sweeps the real corpus). 30s is ~175x the slowest observed call and
#: still less than the ceiling.
#:
#: That corpus test is fast because the sweep walks PUBLISHED RUN TREES, not
#: all 17216 tracked files under `benchmark-data` — verified real rather than
#: assumed: 13 run trees, 3 carrying a `reports/` tree, 5 findings, 0.161s. A
#: sweep that found nothing because it looked at nothing would also be fast.
_BOUND_S = 30


def _sweep(corpus, baseline, *extra):
    import subprocess
    prog = Path(__file__).resolve().parents[1] / "step_internal_fail_bubble_up_check.py"
    return subprocess.run(
        [sys.executable, str(prog), "--corpus", str(corpus),
         "--baseline", str(baseline), *extra],
        capture_output=True, text=True, timeout=_BOUND_S)


def test_a_baseline_that_still_claims_a_PAID_debt_fails(tmp_path):
    """THE PAIRED GUARD for #1025's remaining half.

    The shrink path printed "lower the baseline" and returned 0, and NO test
    covered it. So nothing ever forced the number down: measured on a38902d1
    the shipped register claimed 7 while the sweep measured 5, and a regrowth
    back to 7 would then have read as "no NEW unacknowledged FAIL". Two
    findings of permission, granted by a suggestion nobody had to act on.

    The same rule `evidence_citation_resolves_check` already enforces one gate
    over: "the debt was paid and the register must be updated, else the
    register slowly turns into permission."
    """
    root = _corpus_tree(tmp_path / "bd")
    _fail_report(root, "alpha", "clean_run_v1_20200101", "step_x_check")
    bl = tmp_path / "bl.json"
    assert _sweep(root, bl, "--write-baseline").returncode == 0
    # pay the debt: the FAIL report goes away, the register still claims it
    (root / "ic" / "alpha" / "clean_run_v1_20200101" / "reports"
     / "step_x_check.json").unlink()
    r = _sweep(root, bl)
    assert r.returncode == 1, r.stdout
    assert "PAID and still on the register" in r.stdout, r.stdout


def test_re_recording_the_register_clears_it(tmp_path):
    """The inverse. Without it the guard above is satisfied by a gate that
    fails on every shrink and can never be cleared — a ban, not a check."""
    root = _corpus_tree(tmp_path / "bd")
    _fail_report(root, "alpha", "clean_run_v1_20200101", "step_x_check")
    bl = tmp_path / "bl.json"
    assert _sweep(root, bl, "--write-baseline").returncode == 0
    (root / "ic" / "alpha" / "clean_run_v1_20200101" / "reports"
     / "step_x_check.json").unlink()
    assert _sweep(root, bl).returncode == 1
    assert _sweep(root, bl, "--write-baseline").returncode == 0
    r = _sweep(root, bl)
    assert r.returncode == 0, r.stdout
    assert "no NEW unacknowledged step-internal FAIL" in r.stdout, r.stdout


def test_growth_is_still_told_apart_from_a_paid_debt(tmp_path):
    """Shrink now fails too, so this pins that the two remain distinguishable.
    A gate that said the same thing about both would have made the ratchet
    directionless — it could no longer tell a regression from progress."""
    root = _corpus_tree(tmp_path / "bd")
    _fail_report(root, "alpha", "clean_run_v1_20200101", "step_x_check")
    bl = tmp_path / "bl.json"
    assert _sweep(root, bl, "--write-baseline").returncode == 0
    _fail_report(root, "beta", "clean_run_v2_20200101", "step_y_check")
    r = _sweep(root, bl)
    assert r.returncode == 1, r.stdout
    assert "GREW" in r.stdout, r.stdout
    assert "PAID and still on the register" not in r.stdout, r.stdout


def test_the_shipped_register_agrees_with_the_shipped_corpus():
    """The register and the tree must agree on THIS commit, not on whichever
    day somebody last ran it by hand. Without this, #1025 recurs in silence."""
    import subprocess
    prog = Path(__file__).resolve().parents[1] / "step_internal_fail_bubble_up_check.py"
    repo = prog.resolve().parents[4]
    r = subprocess.run(
        [sys.executable, str(prog), "--corpus", str(repo / "benchmark-data")],
        capture_output=True, text=True, timeout=_BOUND_S, cwd=str(repo))
    assert r.returncode == 0, r.stdout + r.stderr
