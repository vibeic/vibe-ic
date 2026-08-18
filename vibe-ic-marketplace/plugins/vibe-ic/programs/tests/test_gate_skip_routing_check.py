#!/usr/bin/env python3
"""#528 — the enumerating check, and the four gates that land with it.

WHAT IS BEING PINNED, AND WHY IN THIS SHAPE
===========================================
#515 and #521 each fixed a batch of gates that exited 0 while their own report
said `skipped: true`, and each was driven by a BEHAVIOURAL sweep that could
reach 47% of the population — because making a gate skip needs its CLI
interface AND a crafted input, and a gate that refuses the probe's argv leaves
the denominator silently.

So the tests below are deliberately split in two, and the split is the point:

  * the ROUTING of the four gates fixed here is pinned by EXECUTION, through
    `flow_compliance_check._check_program_exit_zero` — the shipped function,
    unmocked, running the real gate as a real subprocess. Asserting `rc == 2`
    alone proves the gate changed its mind, not that the tier moved.

  * the ENUMERATION is pinned by driving `gate_skip_routing_check` over
    SYNTHETIC plugin trees built here, so its predicates are exercised on
    inputs whose right answer is known by construction — including a gate whose
    only interface is a flag, which is the shape that made the sweeps blind.

The one thing NOT tested by executing a gate is the enumeration's own reach,
because there is nothing to execute: it reads source. What IS tested is that it
FIRES on a planted defect and that its recognisers do not fire on the two
shapes measured to be false positives.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

import gate_skip_routing_check as gsrc  # noqa: E402
import _private_tree as _T  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


# ==========================================================================
# 1. THE CONSUMER CONTRACT — measured, not assumed.
#
# Everything this check decides rests on WHICH channels the tier-deciding
# consumer reads. That claim is verified against the shipped function rather
# than restated from its docstring.
# ==========================================================================
def test_consumer_reads_the_unbracketed_token_and_not_the_bracketed_one():
    """The one-character difference the three `[VACUOUS_PASS]` gates hit."""
    assert _flow._stdout_signals_vacuous("VACUOUS_PASS: nothing to examine")
    assert _flow._stdout_signals_vacuous("   VACUOUS_PASS: indented is fine")
    assert not _flow._stdout_signals_vacuous("[VACUOUS_PASS] nothing to check")
    assert not _flow._stdout_signals_vacuous("[SKIP] nothing to check")
    # And the token this check derives its predicate from is the shared one.
    assert _vx.VACUOUS_STDOUT_SENTINEL.startswith(gsrc._CONSUMER_SENTINEL)


def test_consumer_reads_only_two_channels(tmp_path, monkeypatch):
    """A JSON report saying VACUOUS_PASS is NOT a third channel.

    `_check_program_exit_zero` never opens the report file, so a gate whose
    only disclosure is `{"verdict": "VACUOUS_PASS"}` in its `--json` target is
    credited a plain PASS. This is why the check does not accept the report as
    routing.
    """
    # `_resolve_program_cmd` resolves a bare name against `_flow.PROGRAMS_DIR`,
    # which it reads at CALL time — so pointing that at a directory this test
    # owns exercises the same bare-name resolution on the same shipped
    # function. It used to be pointed at the live programs dir instead, which
    # planted this fixture beside the shipped programs for the length of the
    # test; see `_private_tree` for what a concurrent session then measures.
    gate = tmp_path / "_i528_report_only_disclosure_check.py"
    gate.write_text(textwrap.dedent('''\
        """Temporary fixture planted by test_gate_skip_routing_check."""
        import json, sys
        from pathlib import Path
        Path("out.json").write_text(json.dumps({"verdict": "VACUOUS_PASS"}))
        print("examined nothing")
        sys.exit(0)
        '''), encoding="utf-8")
    monkeypatch.setattr(_flow, "PROGRAMS_DIR", tmp_path)
    try:
        passed, out = _flow._check_program_exit_zero(
            tmp_path, "_i528_report_only_disclosure_check")
        assert passed is True, out
        assert not out.startswith("__VACUOUS_HINT__"), (
            "a report-only disclosure was promoted to VACUOUS; the check's "
            "two-channel model would then be wrong")
        assert json.loads((tmp_path / "out.json").read_text())["verdict"] == \
            "VACUOUS_PASS", "the fixture did write the report the consumer ignored"
    finally:
        gate.unlink()


# ==========================================================================
# 2. THE ENUMERATION FIRES ON A PLANTED DEFECT — and on the shapes the
#    behavioural sweeps could not reach.
# ==========================================================================
def _plugin_tree(tmp_path: Path) -> Path:
    """A minimal plugin root the check can enumerate."""
    root = tmp_path / "plugin"
    (root / "programs").mkdir(parents=True)
    (root / "flow").mkdir()
    (root / "flow" / "f.yaml").write_text("steps: []\n", encoding="utf-8")
    # A registry with one member, so tier-1 classification is exercised.
    (root / "programs" / "flow_compliance_check.py").write_text(
        '_STRUCTURAL_RTL_GATES: tuple = (\n    "registered_gate",\n)\n',
        encoding="utf-8")
    return root


def _write(root: Path, name: str, body: str) -> None:
    (root / "programs" / f"{name}.py").write_text(
        textwrap.dedent(body), encoding="utf-8")


def _run_audit(root: Path):
    return gsrc.audit(root, strict=True, inventory={})


def test_planted_unrouted_skip_is_caught(tmp_path):
    root = _plugin_tree(tmp_path)
    _write(root, "registered_gate", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            args = ap.parse_args()
            if not args.project_dir:
                print("[SKIP] nothing to examine")
                return 0
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert not res.passed
    hits = [f for f in res.findings if f.gate == "registered_gate"]
    assert len(hits) == 1
    assert hits[0].rule == "unrouted-skip-exit"
    row = next(r for r in res.rows if r.gate == "registered_gate")
    assert row.tier == gsrc.TIER_CONSUMED
    assert row.unrouted_paths == 1


def test_the_same_gate_routed_through_vacuous_exit_is_clean(tmp_path):
    """MUTATION CONTROL for the test above: only the exit changes."""
    root = _plugin_tree(tmp_path)
    _write(root, "registered_gate", '''\
        import argparse, sys
        import _vacuous_exit as _vx
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            args = ap.parse_args()
            if not args.project_dir:
                print("[SKIP] nothing to examine")
                return _vx.exit_code(passed=True, skipped=True)
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]
    row = next(r for r in res.rows if r.gate == "registered_gate")
    assert (row.skip_paths, row.routed_paths, row.unrouted_paths) == (1, 1, 0)


def test_a_flag_only_gate_is_enumerated_exactly_like_a_positional_one(tmp_path):
    """The 47% blind spot, closed by construction — and BOTH halves asserted.

    A gate whose only interface is `--rtl-dir` is what argparse rejected in
    both sweeps. This test proves the two halves separately, because asserting
    only the second would not show that the first is a real hazard:

      (a) the sweeps' own argv CANNOT drive this gate — argparse rejects it
          with rc 2, which a probe looking for rc 0 reads as "did not
          reproduce";
      (b) the enumeration reports it anyway, with a substantive row and the
          finding, because nothing here invokes it.

    Measured over the shipped tree at the same time: a positional-argv probe
    can drive 411 of 548 in-scope modules; the other 137 answer rc 2 to it,
    and the enumeration produces a substantive row for 134 of those 137 and
    names the remaining 3 as written-reason exclusions.
    """
    root = _plugin_tree(tmp_path)
    _write(root, "flag_only_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("--rtl-dir", required=True)
            args = ap.parse_args()
            if not args.rtl_dir:
                print("[SKIP] no wake/sleep signals found")
                return 0
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')

    # (a) the probe shape both sweeps used cannot drive it.
    probe = subprocess.run(
        [sys.executable, str(root / "programs" / "flag_only_check.py"), "."],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert probe.returncode == 2, probe.stderr
    assert "usage:" in probe.stderr, (
        "the rejection must be argparse's self-identifying protocol, so this "
        "test is pinning the real hazard and not some other rc 2")
    assert "[SKIP]" not in probe.stdout, (
        "the gate never reached its own skip branch — which is exactly why a "
        "behavioural sweep records it as 'did not reproduce'")

    # (b) the enumeration reports it regardless.
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "flag_only_check")
    assert row.arg_shape == "flag-only-projectish"
    assert row.tier == gsrc.TIER_GATE_SHAPED
    assert row.unanalysable is None and row.excluded_reason is None
    assert [f.rule for f in res.findings if f.gate == "flag_only_check"] == [
        "unrouted-skip-exit"]


def test_no_in_scope_module_is_silently_absent_from_the_enumeration():
    """Every in-scope module gets an ANSWER, and the answer is never silence.

    The denominator's whole value is that a module cannot leave it without
    saying so. Each in-scope row must be exactly one of: analysed, honestly
    UNANALYSABLE, or EXCLUDED with a written reason.
    """
    res = gsrc.audit(_PLUGIN)
    in_scope = [r for r in res.rows if r.tier != gsrc.TIER_NOT_A_GATE]
    assert in_scope, "the enumeration found no in-scope module at all"
    for row in in_scope:
        answers = [row.excluded_reason is not None,
                   row.unanalysable is not None,
                   row.entry is not None]
        assert any(answers), (
            f"{row.gate} has no entry, no unanalysable note and no exclusion "
            f"reason — it left the denominator silently")
    # And the census a reader sees must agree with the rows.
    assert res.summary["unanalysable_in_scope"] == sum(
        1 for r in in_scope if r.unanalysable)
    assert res.summary["in_scope"] == len(in_scope)


def test_a_gate_taking_neither_shape_is_enumerated_too(tmp_path):
    """The "45 neither-shape gates" — not excluded, not a category here."""
    root = _plugin_tree(tmp_path)
    _write(root, "neither_shape_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("--strict", action="store_true")
            args = ap.parse_args()
            if args.strict:
                print("[N/A] nothing declares this requirement")
                return 0
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "neither_shape_check")
    assert row.arg_shape == "flag-only-other"
    assert row.skip_paths == 1 and row.unrouted_paths == 1
    assert any(f.gate == "neither_shape_check" for f in res.findings)


def test_bracketed_sentinel_is_its_own_named_finding(tmp_path):
    root = _plugin_tree(tmp_path)
    _write(root, "bracketed_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[VACUOUS_PASS] bracketed_check: nothing declared")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    hits = [f for f in res.findings if f.gate == "bracketed_check"]
    assert [f.rule for f in hits] == ["bracketed-sentinel-unreadable"]


def test_unbracketed_sentinel_with_rc_zero_is_accepted_as_routed(tmp_path):
    """MUTATION CONTROL for the test above: only the brackets change.

    rc stays 0. Channel B is a real, documented channel, so demanding rc 2 here
    would make the check disagree with the consumer it derives its rule from.
    """
    root = _plugin_tree(tmp_path)
    _write(root, "bracketed_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("VACUOUS_PASS: bracketed_check: nothing declared")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]
    row = next(r for r in res.rows if r.gate == "bracketed_check")
    assert row.sentinel_only_paths == 1, (
        "a channel-B-only route must be COUNTED as fragile, not silently "
        "treated as equivalent to rc 2")


def test_structured_skip_never_read_back_is_caught(tmp_path):
    """The #515 / #521 shape: the gate knew, and the exit code never asked.

    The write is in the AUDIT helper, not in `main`, which is where every one
    of the 23 already-fixed gates put it — `main` computed `0 if
    result.passed else 1` and the conclusion the gate had already reached never
    reached the one place a consumer can see it.
    """
    root = _plugin_tree(tmp_path)
    _write(root, "structured_check", '''\
        import argparse, json, sys
        def run_audit(project):
            summary = {}
            if not (project or "").strip():
                summary["skipped"] = True
            return {"passed": True, "summary": summary}
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            args = ap.parse_args()
            result = run_audit(args.project_dir)
            print(json.dumps(result))
            return 0 if result["passed"] else 1
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert [f.rule for f in res.findings if f.gate == "structured_check"] == [
        "structured-skip-not-read-back"]


def test_the_same_gate_reading_its_skip_back_is_clean(tmp_path):
    """MUTATION CONTROL: only `main`'s last two lines change."""
    root = _plugin_tree(tmp_path)
    _write(root, "structured_check", '''\
        import argparse, json, sys
        import _vacuous_exit as _vx
        def run_audit(project):
            summary = {}
            if not (project or "").strip():
                summary["skipped"] = True
            return {"passed": True, "summary": summary}
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            args = ap.parse_args()
            result = run_audit(args.project_dir)
            print(json.dumps(result))
            return _vx.exit_code(result["passed"],
                                 _vx.summary_is_skipped(result["summary"]))
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]


def test_a_container_named_skipped_is_not_a_skip_flag(tmp_path):
    """MUTATION CONTROL and a measured false positive, both.

    `reset_dependency_check` reports `summary['skipped']` as a LIST of the
    files its scan excluded (ORGANIC #615 transparency). Driven for real it
    answers rc 0 with `skipped == []` — it examined the design. Accusing it
    would be the false-positive shape that gets a checker deleted (#439).
    """
    root = _plugin_tree(tmp_path)
    _write(root, "container_check", '''\
        import argparse, json, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            excluded = []
            summary = {"files_scanned": 3,
                       "skipped": [{"file": f} for f in excluded]}
            print(json.dumps(summary))
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]


def test_a_skip_in_one_branch_is_not_charged_to_another_branchs_exit(tmp_path):
    """MUTATION CONTROL for the block scanner's scoping."""
    root = _plugin_tree(tmp_path)
    _write(root, "two_branch_check", '''\
        import argparse, sys
        import _vacuous_exit as _vx
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            args = ap.parse_args()
            if not args.project_dir:
                print("[SKIP] nothing to examine")
                return _vx.exit_code(passed=True, skipped=True)
            print("[PASS] examined the design")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]
    row = next(r for r in res.rows if r.gate == "two_branch_check")
    assert row.skip_paths == 1


def test_a_finding_beats_a_skip(tmp_path):
    """rc 1 is never a lost skip — surfacing the violation is the safe way."""
    root = _plugin_tree(tmp_path)
    _write(root, "finding_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] partial input")
            return 1
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert res.passed, [f.message for f in res.findings]


def test_a_not_a_gate_module_is_out_of_scope_with_the_reason_recorded(tmp_path):
    root = _plugin_tree(tmp_path)
    _write(root, "thing_gen", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] nothing to generate")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    assert not any(f.gate == "thing_gen" for f in res.findings)
    row = next(r for r in res.rows if r.gate == "thing_gen")
    assert row.tier == gsrc.TIER_NOT_A_GATE
    assert row.tier_reason and "not a verdict" in row.tier_reason
    assert row.skip_paths == 1, (
        "an out-of-scope module must still be ENUMERATED — an exclusion by "
        "omission is what this check exists to prevent")


def test_a_module_with_no_main_guard_is_unanalysable_not_analysed(tmp_path):
    """The branch a surviving mutation exposed, now a decision with a test.

    `entry_function` used to fall back to a bare module-level `main` when no
    `if __name__ == "__main__"` guard called anything. Mutating that fallback
    to `return None` survived every test — because it was dead: 0 of 1032
    modules in `programs/` had an entry only the fallback could find. It was
    deleted rather than given a manufactured test, because a module with no
    guard cannot be run as a CLI and its exit code is therefore never a
    verdict. What it must NOT do is disappear: the fail-safe answer is
    "unanalysable", stated.
    """
    root = _plugin_tree(tmp_path)
    _write(root, "no_guard_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] nothing to examine")
            return 0
        ''')
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "no_guard_check")
    assert row.entry is None
    assert row.unanalysable == "no module-level entry function"
    assert not any(f.gate == "no_guard_check" for f in res.findings)
    # And it is still COUNTED, so the denominator does not quietly shrink.
    assert res.summary["unanalysable_in_scope"] >= 1


def test_the_main_guard_is_what_selects_the_entry(tmp_path):
    """MUTATION CONTROL for the test above: the same gate, plus the guard."""
    root = _plugin_tree(tmp_path)
    _write(root, "no_guard_check", '''\
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] nothing to examine")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        ''')
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "no_guard_check")
    assert row.entry == "main"
    assert row.unanalysable is None
    assert [f.rule for f in res.findings if f.gate == "no_guard_check"] == [
        "unrouted-skip-exit"]


def test_a_guard_calling_a_differently_named_entry_is_followed(tmp_path):
    """The guard is read, not the NAME `main` — a gate whose entry is called
    something else must still be analysed."""
    root = _plugin_tree(tmp_path)
    _write(root, "renamed_entry_check", '''\
        import argparse, sys
        def run_cli():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] nothing to examine")
            return 0
        if __name__ == "__main__":
            sys.exit(run_cli())
        ''')
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "renamed_entry_check")
    assert row.entry == "run_cli"
    assert [f.rule for f in res.findings if f.gate == "renamed_entry_check"] == [
        "unrouted-skip-exit"]


def test_an_unanalysable_module_is_reported_not_silently_cleared(tmp_path):
    root = _plugin_tree(tmp_path)
    (root / "programs" / "broken_check.py").write_text(
        "def main(:\n    pass\n", encoding="utf-8")
    res = _run_audit(root)
    row = next(r for r in res.rows if r.gate == "broken_check")
    assert row.unanalysable and "unparseable" in row.unanalysable
    assert res.summary["unanalysable_in_scope"] >= 1


# ==========================================================================
# 3. THE RATCHET — all four directions.
# ==========================================================================
@pytest.mark.parametrize("measured,inventory,key", [
    ({"g": 1}, {}, "new"),
    ({"g": 2}, {"g": 1}, "grown"),
    ({"g": 1}, {"g": 2}, "shrunk"),
    ({}, {"g": 1}, "fixed"),
])
def test_ratchet_fires_in_every_direction(measured, inventory, key):
    out = gsrc.ratchet(measured, inventory)
    assert out[key], out
    assert sum(len(out[k]) for k in ("new", "grown", "shrunk", "fixed")) == 1


def test_ratchet_is_silent_when_the_measurement_matches():
    assert gsrc.ratchet({"g": 3}, {"g": 3}) == {
        "new": [], "grown": [], "shrunk": [], "fixed": []}


def test_a_new_gate_with_an_unrouted_skip_fails_the_shipped_check(tmp_path):
    """The standing requirement: the class cannot grow unnoticed.

    Driven against the REAL inventory over a HARDLINK FARM of the shipped
    programs plus one planted gate — same inodes, same flow yaml, same
    ratchet, so this exercises the shipped check and not a stub. The farm is
    what keeps the plant out of the tree every concurrent pytest session is
    reading; see `_private_tree`.
    """
    plugin = _T.private_plugin(tmp_path)
    planted = plugin / "programs" / "_i528_planted_unrouted_check.py"
    planted.write_text(textwrap.dedent('''\
        """Temporary fixture planted by test_gate_skip_routing_check."""
        import argparse, sys
        def main():
            ap = argparse.ArgumentParser()
            ap.add_argument("project_dir")
            ap.parse_args()
            print("[SKIP] planted: nothing to examine")
            return 0
        if __name__ == "__main__":
            sys.exit(main())
        '''), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_skip_routing_check.py"),
         str(plugin)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, r.stdout
    assert "_i528_planted_unrouted_check" in r.stdout
    assert "RATCHET-NOT IN THE INVENTORY" in r.stdout
    _T.assert_live_tree_unplanted("_i528_*")


def test_the_shipped_tree_is_clean_under_the_ratchet():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_skip_routing_check.py"),
         str(_PLUGIN)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("[PASS]")


def test_the_published_residual_is_not_zero_and_says_so():
    """An audit that reports a clean zero it cannot back is the whole bug.

    The inventory is the count of what is still wrong. If it silently emptied,
    somebody would have to have fixed 52 gates, and this assertion is the place
    that notices the alternative — a predicate that stopped firing.
    """
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_skip_routing_check.py"),
         str(_PLUGIN), "--json", "-"],
        capture_output=True, text=True, timeout=60)
    payload = json.loads(r.stdout)
    assert payload["ratchet"]["measured_paths"] > 0
    assert payload["ratchet"]["measured_paths"] == \
        payload["ratchet"]["inventory_paths"]
    assert payload["summary"]["skip_paths_unrouted"] == \
        payload["ratchet"]["measured_paths"]


def test_strict_mode_fails_on_the_residual():
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "gate_skip_routing_check.py"),
         str(_PLUGIN), "--strict"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "unrouted-skip-exit" in r.stdout


# ==========================================================================
# 4. THE EXCLUSION REGISTRY — reasons, in the code, checked.
# ==========================================================================
def test_every_exclusion_carries_a_written_reason():
    for gate, reason in gsrc._EXCLUDED.items():
        assert isinstance(reason, str) and len(reason) > 80, gate


def test_artefact_defect_close_check_is_excluded_and_untouched():
    """#528 examined it and dismissed it; that decision is recorded, not coded
    around."""
    assert "artefact_defect_close_check" in gsrc._EXCLUDED
    reason = gsrc._EXCLUDED["artefact_defect_close_check"]
    assert "DOCUMENTED CONTRACT" in reason
    src = (_PROGRAMS / "artefact_defect_close_check.py").read_text(
        encoding="utf-8")
    assert "0 = PASS, ADVISORY-only, or SKIPPED" in src, (
        "the exclusion quotes this contract; if the header changed, the "
        "exclusion reason has to be re-derived rather than kept")
    res = gsrc.audit(_PLUGIN)
    assert not any(f.gate == "artefact_defect_close_check"
                   for f in res.findings)


def test_l9_completeness_check_stays_recorded_as_a_non_instance():
    assert "l9_completeness_check" in gsrc._EXCLUDED
    assert "PER-SECTION" in gsrc._EXCLUDED["l9_completeness_check"]


# ==========================================================================
# 5. THE FOUR GATES FIXED HERE — pinned through the REAL consumer.
# ==========================================================================
def _tier(project: Path, cmd: str) -> str:
    passed, out = _flow._check_program_exit_zero(project, cmd)
    if out.startswith("__VACUOUS_HINT__"):
        return "VACUOUS"
    return "PASS" if passed else "FAIL"


def test_marketplace_sync_missing_manifest_reaches_rc_two(tmp_path):
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "no .claude-plugin/marketplace.json" in r.stdout


def test_marketplace_sync_manifest_without_plugins_array_reaches_rc_two(
        tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "x", "plugins": "not-a-list"}), encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, (r.stdout, r.stderr)


@pytest.mark.parametrize("manifest", [
    pytest.param({"name": "x"}, id="plugins-key-ABSENT"),
    pytest.param({"name": "x", "plugins": []}, id="plugins-EMPTY-list"),
    pytest.param({"name": "x", "plugins": ["a", "b"]}, id="entries-not-dicts"),
])
def test_marketplace_sync_zero_comparisons_reaches_rc_two(tmp_path, manifest):
    """#528 follow-up — a PASS over zero version comparisons, three spellings.

    `.get("plugins", [])` hands back the default for an ABSENT key, and that
    default IS a list, so the `not isinstance(..., list)` guard never fires.
    Measured against the pre-#528 file, all three of these answered rc 0 with
    `[PASS] ... 0 plugin entr(ies)` — a plain PASS over nothing, in the gate
    `gatekeeper_review` treats as green when `rc in (0, -1)`.

    The routing is from `matched`, the gate's OWN record of what it compared,
    not from any of these input shapes — which is why one predicate covers all
    three and would cover a fourth spelling nobody has written yet.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "no version was compared" in r.stdout, r.stdout
    snippet = (r.stdout[-300:] + "\n" + r.stderr[-300:]).strip()
    assert _flow._stdout_signals_vacuous(snippet), snippet


def test_marketplace_sync_still_passes_when_it_compares_something(tmp_path):
    """MUTATION CONTROL for the three above: one real, in-sync entry.

    Without this, routing `matched == []` could be widened to route every PASS
    and no test would notice.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "x", "plugins": [
            {"name": "p", "source": "./p", "version": "1.2.3"}]}),
        encoding="utf-8")
    pj = tmp_path / "p" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text(json.dumps({"version": "1.2.3"}),
                                    encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "1 plugin entr(ies)" in r.stdout, r.stdout


def test_marketplace_sync_still_fails_on_real_drift(tmp_path):
    """MUTATION CONTROL: a drifted entry must stay rc 1, never become vacuous.

    A FINDING beats a skip. If the zero-denominator branch were ever placed
    before the findings check, real drift would be silenced — which is worse
    than the defect being fixed.
    """
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "x", "plugins": [
            {"name": "p", "source": "./p", "version": "9.9.9"}]}),
        encoding="utf-8")
    pj = tmp_path / "p" / ".claude-plugin"
    pj.mkdir(parents=True)
    (pj / "plugin.json").write_text(json.dumps({"version": "1.2.3"}),
                                    encoding="utf-8")
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run(
        [sys.executable, str(prog), "--marketplace-dir", str(tmp_path)],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, (r.stdout, r.stderr)


def test_marketplace_docstring_lists_exactly_its_three_vacuous_reasons():
    """The docstring promised a case the code did not implement.

    Round one said "a manifest with no plugins[] array", which reads like the
    ABSENT-key case; the code only covered "present and not a list". A
    docstring that describes a branch nobody wrote is how the gap survived
    review. Each reason token must appear in BOTH the module docstring and the
    code, so the two cannot drift apart again silently.
    """
    src = (_PROGRAMS / "marketplace_version_sync_check.py").read_text(
        encoding="utf-8")
    doc = ast.get_docstring(ast.parse(src)) or ""
    for reason in ("no-marketplace-json", "manifest-has-no-plugins-array",
                   "no-plugin-entries-compared"):
        assert reason in doc, f"{reason} is routed but undocumented"
        assert f'"{reason}"' in src, f"{reason} is documented but not routed"


def test_reports_taxonomy_empty_directory_is_the_same_zero_as_a_missing_one(
        tmp_path):
    """#528 follow-up, neighbour sweep — absent and empty are one denominator.

    This gate routed its vacuous tier from an INPUT SHAPE (`reports.is_dir()`).
    A reports/ that exists and holds nothing was examined exactly as much —
    zero entries — and answered `[PASS] ... all 0 reports/ entries match`.
    Both states must reach the same tier because the gate looked at the same
    nothing.
    """
    (tmp_path / "reports").mkdir()
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "VACUOUS"
    missing = tmp_path / "sibling"
    missing.mkdir()
    assert _tier(missing, "reports_subfolder_taxonomy_check .") == "VACUOUS"


def test_reports_taxonomy_still_passes_over_a_populated_directory(tmp_path):
    """MUTATION CONTROL for the test above."""
    (tmp_path / "reports" / "phase1").mkdir(parents=True)
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "PASS"


def test_top_level_outputs_already_routes_from_its_denominator(tmp_path):
    """The neighbour that was ALREADY right, pinned so it stays right.

    `top_level_outputs_in_canonical_check` computes `if not entries:
    vacuous_pass = True` — the denominator, not a directory test. Measured
    across every zero-denominator input it accepts, it answers VACUOUS; with
    one real entry it answers PASS. It is in this file because comparing it
    against `reports_subfolder_taxonomy_check` is what made the difference
    between "routes from the input shape" and "routes from the count" visible.
    """
    assert _tier(tmp_path, "top_level_outputs_in_canonical_check .") == "VACUOUS"
    populated = tmp_path / "p"
    (populated / "reports").mkdir(parents=True)
    assert _tier(populated, "top_level_outputs_in_canonical_check .") == "PASS"


@pytest.mark.parametrize("cwd,args", [
    (_PLUGIN, []),                                # repo_hygiene_gates.sh
    (_PLUGIN.parents[2], ["--marketplace-dir", str(_PLUGIN)]),  # gatekeeper
    (_PLUGIN.parents[2], ["--marketplace-dir", str(_PLUGIN.parents[1])]),
])
def test_marketplace_sync_landing_usages_are_unaffected(cwd, args):
    """Every real invocation in the repo still answers rc 0.

    `tools/ci/pre_commit_check.sh` (guarded on `.claude-plugin` existing),
    `tools/ci/repo_hygiene_gates.sh` (cwd = the plugin) and
    `.github/workflows/gatekeeper-ci.yml` (`--marketplace-dir`) all supply a
    tree where the manifest exists, so the changed branch never fires there.
    """
    prog = _PROGRAMS / "marketplace_version_sync_check.py"
    r = subprocess.run([sys.executable, str(prog), *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_marketplace_sync_gate_wrapper_no_longer_greens_an_empty_tree(tmp_path):
    """`gatekeeper_review.GateResult.green` is `rc in (0, -1)`.

    Before #528 this gate answered rc 0 over a tree with no manifest, so a
    MERGE gate was green about a comparison that never happened.
    """
    import gatekeeper_review as gr
    assert gr.marketplace_sync_gate(_PLUGIN).green is True
    assert gr.marketplace_sync_gate(tmp_path).green is False


def test_reports_taxonomy_skip_reaches_the_vacuous_tier(tmp_path):
    assert _tier(tmp_path, "reports_subfolder_taxonomy_check .") == "VACUOUS"


def test_top_level_outputs_skip_reaches_the_vacuous_tier(tmp_path):
    assert _tier(tmp_path, "top_level_outputs_in_canonical_check .") == "VACUOUS"


def test_cross_layer_reference_skip_reaches_the_vacuous_tier(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_SYSTEM_OVERVIEW.json").write_text('{"a": 1}', encoding="utf-8")
    assert _tier(tmp_path, "cross_layer_reference_check .") == "VACUOUS"


def test_cross_layer_corpus_mode_is_untouched():
    """The mode `tools/ci/repo_hygiene_gates.sh` runs returns before the
    changed branch, and that script's `run` helper treats ANY non-zero rc as a
    hard FAILED — so this is the assertion that would have caught a regression
    in CI rather than in review."""
    src = (_PROGRAMS / "cross_layer_reference_check.py").read_text(
        encoding="utf-8")
    corpus_block, _, project_block = src.partition("if not args.project:")
    assert "VACUOUS_PASS" not in corpus_block.split("def main")[-1], (
        "the corpus path must not have grown a vacuous branch; CI's `run` "
        "helper would turn its rc 2 into a hard FAILED")
    assert "_vx.exit_code" in project_block
