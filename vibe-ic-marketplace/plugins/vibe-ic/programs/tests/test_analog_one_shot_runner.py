#!/usr/bin/env python3
"""Tests for analog_one_shot_runner.py — A1-A9 analog flow orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner walks each declared analog block through 9 steps. When no
deterministic program ships for a step it returns WAIVED with the skill
name. When no analog blocks are declared the runner SKIPs cleanly.

Cases:
  1. SKIP_PURE_DIGITAL — no analog_block_list.json + L5 absent → SKIP exit 0,
                           reports/analog_one_shot.json verdict=SKIP.
  2. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  3. PASS_WITH_WAIVERS_ONE_BLOCK — one block declared and nothing else staged
                                     → A1 refused, no later producers.
                                     The full-population row has no complete
                                     consumer. It reports NOT_MEASURED / rc1
                                     with the original required-input reason;
                                     A2-A9 are not fabricated as rows.
  4. INTEGRATION_REPORT_SHAPE — phase=analog, blocks list, steps list.
  5. SKIP_VIA_L5_NO_ANALOG — L5_ADI_SPEC.json#no_analog=true → SKIP.
  6. EDGE_BLOCKS_FILTER — `--blocks <name>` selects subset of declared blocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / \
    "analog_one_shot_runner.py"


def _run(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def _write_block_list(project: Path, blocks: list) -> None:
    a = project / "phase3" / "analog"
    a.mkdir(parents=True, exist_ok=True)
    (a / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}, indent=2))


def test_fail_no_block_list_when_missing(tmp_path):
    """v1.6.128 (#50 Fix 1) — when neither analog/analog_block_list.json
    NOR generated_docs/L5_ADI_SPEC.json exists, the runner refuses
    to silently SKIP. It emits FAIL_NO_BLOCK_LIST so the caller
    knows phase1 / spec-extract was missed.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stderr
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "FAIL_NO_BLOCK_LIST"
    assert body["blocks"] == []


def test_skip_pure_digital_with_empty_block_list(tmp_path):
    """v1.6.128 (#50 Fix 1) — explicit empty block list `[]` is the
    canonical "this project has no analog" signal. Runner SKIPs
    cleanly with rc=0 + verdict=SKIP.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [])  # explicit empty list
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[SKIP]" in cp.stdout
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "SKIP"
    assert body["blocks"] == []


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


#: THE PER-BLOCK POPULATION, BY NAME. Read from the runner's own dispatch order
#: rather than retyped, so an A-step that is renamed or dropped fails here
#: instead of being absorbed by a count that still adds up.
_A_STEPS = frozenset({
    "A1_spec_extract", "A2_topology_select", "A3_netlist_gen",
    "A4_corner_sweep", "A5_layout", "A6_block_pv", "A7_post_layout_resim",
    "A8_hardmacro_gen", "A9_hw_verify",
})


def _a_step_names(body):
    """The A1-A9 rows in the published ledger, as a SET of names."""
    return {s["name"] for s in body["steps"] if s["name"] in _A_STEPS}


def _project_row_names(body):
    """Every row that is NOT one of the nine per-block A-steps.

    These are the project-level rows: the block-list schema gate, plus
    the explicit canonical refusal when a complete row was not accepted. Returned as a set so a second one arriving
    unannounced fails the assertions above rather than moving a total nobody
    reads.
    """
    return {s["name"] for s in body["steps"] if s["name"] not in _A_STEPS}




def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [{"name": "tst_ldo"}])
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    for k in ("phase", "project", "blocks", "steps", "verdict"):
        assert k in body
    # Each step entry has name + block + status fields.
    for s in body["steps"]:
        assert "name" in s and "block" in s and "status" in s


def test_skip_via_l5_no_analog(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({"no_analog": True}))
    cp = _run([str(project)])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["verdict"] == "SKIP"


def test_edge_blocks_filter(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [
        {"name": "tst_bandgap"},
        {"name": "tst_ldo"},
        {"name": "tst_pll"},
    ])
    cp = _run([str(project), "--blocks", "tst_ldo"])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["blocks"] == ["tst_ldo"]
    # 9 A* steps × 1 SELECTED block, plus the project-level block-list schema
    # row (vibe-ic#2080). Membership, for the reason given above: `--blocks`
    # narrows the PER-BLOCK population and must not silently drop or duplicate
    # the project-level one.
    assert _a_step_names(body) == _A_STEPS
    assert _project_row_names(body) == {"block_list_schema"}
    declaration = json.loads((project / "phase3/analog/analog_block_list.json").read_text())
    assert {b["name"] for b in declaration["blocks"]} == {"tst_bandgap", "tst_ldo", "tst_pll"}


# ---------------------------------------------------------------------------
# vibe-ic#2010 items 1-2 — the macro/RTL interface check is ENFORCED at A8:
# invoked inline, per block, and its rc 1 is the block's A8 FAIL.
# ---------------------------------------------------------------------------

def _drive_a8(tmp_path, monkeypatch, iface_rc, iface_out):
    """Run A8 for one block with the two spawn channels stubbed: the
    `subprocess` module (the fail-open producers) and `_progress_run.run`
    (the gates). Returns (StepResult, argv list handed to `_pr.run`)."""
    import subprocess as _sp
    import analog_one_shot_runner as AOSR

    class _Quiet:
        def run(self, argv, **kw):
            return _sp.CompletedProcess(argv, 0, "", "")

        def __getattr__(self, name):
            return getattr(_sp, name)

    monkeypatch.setattr(AOSR, "subprocess", _Quiet())
    seen = []

    class _Gates:
        @staticmethod
        def run(*args, **kw):
            # FAITHFUL DOUBLE — it must refuse exactly what the real
            # `_progress_run.run` refuses. A `**kw` stand-in is MORE PERMISSIVE
            # than the real function and silently swallows an argument the real
            # one has no parameter for, so the test stays green while production
            # raises TypeError. Binding the REAL signature — rather than
            # rejecting one named keyword — means the NEXT argument that drifts
            # is caught the same way.
            import inspect as _inspect
            import _progress_run as _real_pr
            _inspect.signature(_real_pr.run).bind(*args, **kw)
            argv = args[0]
            seen.append([str(a) for a in argv])
            prog = Path(argv[1]).name
            if prog == "analog_macro_rtl_interface_check.py":
                return _sp.CompletedProcess(argv, iface_rc, iface_out, "")
            return _sp.CompletedProcess(argv, 0, "PASS: stubbed gate\n", "")

    monkeypatch.setattr(AOSR, "_pr", _Gates())
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog").mkdir(parents=True, exist_ok=True)
    r = AOSR.step_for_block(proj, {"name": "bandgap"}, "A8_hardmacro_gen", None)
    return r, seen


def test_a8_fails_the_block_when_the_macro_and_rtl_interfaces_disagree(
        tmp_path, monkeypatch):
    r, seen = _drive_a8(tmp_path, monkeypatch, 1,
                        "  [bandgap] MACRO_RTL_INTERFACE_DISAGREES\n"
                        "FAIL: 1/1 block(s) disagree\n")
    assert r.status == "FAIL", r
    assert "interface disagrees" in r.detail and "1/1" in r.detail
    assert r.extras["macro_rtl_interface_rc"] == 1
    iface = [c for c in seen
             if Path(c[1]).name == "analog_macro_rtl_interface_check.py"]
    assert len(iface) == 1, seen
    argv = iface[0]
    assert "--block" in argv and "bandgap" in argv and "--json" in argv, argv
    assert str(tmp_path / "proj") in argv


def test_a8_stands_on_the_gates_pass_when_the_interfaces_agree_or_cannot_compare(
        tmp_path, monkeypatch):
    r, _ = _drive_a8(tmp_path, monkeypatch, 0, "PASS: 1/1 block(s) agree\n")
    assert r.status == "PASS", r
    # rc 2 — no comparable pair yet — is a disclosed skip, not a FAIL
    r2, _ = _drive_a8(tmp_path, monkeypatch, 2, "VACUOUS: nothing could be compared\n")
    assert r2.status == "PASS", r2


def test_the_interface_check_runs_at_a8_and_only_there(tmp_path, monkeypatch):
    import subprocess as _sp
    import analog_one_shot_runner as AOSR

    class _Quiet:
        def run(self, argv, **kw):
            return _sp.CompletedProcess(argv, 0, "", "")

        def __getattr__(self, name):
            return getattr(_sp, name)

    monkeypatch.setattr(AOSR, "subprocess", _Quiet())
    seen = []

    class _Gates:
        @staticmethod
        def run(*args, **kw):
            # FAITHFUL DOUBLE — it must refuse exactly what the real
            # `_progress_run.run` refuses. A `**kw` stand-in is MORE PERMISSIVE
            # than the real function and silently swallows an argument the real
            # one has no parameter for, so the test stays green while production
            # raises TypeError. Binding the REAL signature — rather than
            # rejecting one named keyword — means the NEXT argument that drifts
            # is caught the same way.
            import inspect as _inspect
            import _progress_run as _real_pr
            _inspect.signature(_real_pr.run).bind(*args, **kw)
            argv = args[0]
            seen.append(Path(argv[1]).name)
            return _sp.CompletedProcess(argv, 0, "PASS: stubbed\n", "")

    monkeypatch.setattr(AOSR, "_pr", _Gates())
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog").mkdir(parents=True)
    for step in ("A5_layout", "A7_post_layout_resim", "A9_hw_verify"):
        seen.clear()
        AOSR.step_for_block(proj, {"name": "b"}, step, None)
        assert "analog_macro_rtl_interface_check.py" not in seen, (step, seen)

def test_no_call_site_passes_timeout_into_the_progress_run_shim():
    """No call site may pass `timeout=` into `_progress_run.run`.

    `_progress_run` is the shim that REPLACED the timeout mechanism; it has no `timeout`
    parameter and its own docstring prescribes converting a call site by DELETING the
    argument. A site that keeps it raises `TypeError: run() got an unexpected keyword
    argument 'timeout'` at run time, and the usual
    `except (OSError, subprocess.SubprocessError)` does NOT catch a TypeError, so the
    exception escapes whatever guard the author thought they had. Measured: exactly that
    killed the analog runner at every A6 dispatch.

    This asserts the INVARIANT over the whole `programs/` tree rather than over the one
    call site that was found, so a re-introduction ANYWHERE is caught. It is deliberately
    written to observe a VALUE -- the set of offending call sites, which is `[]` when the
    invariant holds and names a file:line when it does not -- rather than to notice that
    something is absent.
    """
    import ast
    from _hostpaths import require_repo
    # Driven by a REAL checked-in artefact (the shipped `programs/` tree), through the
    # sanctioned accessor rather than a hand-rolled parent-walk: on the installed plugin
    # cache, where the monorepo is not present, this SKIPS with a reason instead of
    # silently scanning whatever tree it happens to land in.
    programs_dir = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs")
    offenders = []
    scanned = 0
    for py in sorted(programs_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(errors="replace"))
        except SyntaxError:                      # not ours to police here
            continue
        scanned += 1
        # A CALL THAT PINS THE REFUSAL IS NOT AN OFFENCE (CZT2, measured RED on
        # a clean tree at fa88faa424). This guard's population is the WHOLE tree
        # including `tests/`, and a sibling test in that tree pins the
        # primitive's own contract with
        #     with pytest.raises(TypeError):
        #         _pr.run([...], timeout=30)
        # -- the call whose failure IS the assertion. Read as an offence, it
        # made this guard fail on an unmodified checkout: two tests from one
        # lane, one scanning a population that had come to contain the other.
        # Excluding `tests/` wholesale would have been the easy repair and would
        # have blinded the guard to every real offender in a test helper. The
        # shape that is genuinely exempt is the call inside
        # `pytest.raises(TypeError)`, so that is what is excluded and nothing
        # else.
        pinned = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                ctx = item.context_expr
                if (isinstance(ctx, ast.Call)
                        and isinstance(ctx.func, ast.Attribute)
                        and ctx.func.attr == "raises"
                        and ctx.args
                        and getattr(ctx.args[0], "id", None) == "TypeError"):
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call):
                            pinned.add(id(inner))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in pinned:
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            if fn.attr not in ("run", "run_or_undetermined", "run_best_effort"):
                continue
            if getattr(fn.value, "id", None) not in ("_pr", "_progress_run"):
                continue
            for kw in node.keywords:
                if kw.arg == "timeout":
                    offenders.append(
                        "%s:%d" % (py.relative_to(programs_dir), node.lineno))
    # THE DENOMINATOR, ASSERTED. "No offenders" over an unread tree is the
    # vacuous pass this repo keeps re-finding, and the exemption above is
    # exactly the kind of edit that can empty a population by accident.
    assert scanned > 500, (
        f"only {scanned} files parsed under {programs_dir} — this guard's "
        f"population collapsed, so an empty offender list means nothing")
    assert offenders == [], (
        "these call sites pass `timeout=` into _progress_run.run, which has no such "
        "parameter, so they raise TypeError at run time: " + ", ".join(offenders))
