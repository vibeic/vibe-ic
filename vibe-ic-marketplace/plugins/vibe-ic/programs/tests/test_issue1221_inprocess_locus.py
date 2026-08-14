#!/usr/bin/env python3
"""#1221 — the §4.05 boundary needs a locus IN THIS PROCESS, and a guard that
fails while it has none.

#1079 was consolidated into main as `step_input_scope` (#1158, `6011b4886`).
That merge landed the boundary and the CHILD-process mechanism. Measured on
`origin/main` `75776dbbb`, the result enforces nothing in production:

    VIBEIC_STEP_SCOPE=1, run_supervised(cmd)                  <- production shape
        scope record : {'enforced': False}
        child said   : CHILD-READ-OK:{"secret": "the oracle"}

    VIBEIC_STEP_SCOPE=1, run_supervised(cmd, scope_step="23") <- test shape
        scope record : {'enforced': True, ..., 'liveness': 'confirmed'}
        child said   : CHILD-DENIED: vibe-ic §4.05 ... may not read golden/qor.json

The mechanism works; nothing reaches it. `scope_step` is passed by NO caller of
`_watchdog.run_supervised`, so the owner's switch is not wired to anything —
and all three callers that exist (`_docker_watchdog.py:210`,
`phase3_one_shot_runner.py:953`, `regmap_transaction_tb_gen.py:688`) launch a
NON-Python child, which the audit hook cannot cover in any case:

    non-python child, scope_step passed : enforced=False, read=True

Both were true because the four competing PRs on #1079 disagreed about exactly
this — WHERE the boundary is installed — and the half that said "in-process"
(#1105) is the half that did not land. #1221's adjudication had already called
that the whole finding:

    "The runners read the design IN-PROCESS — `phase1_one_shot_runner`
     ingesting documents into L1-L27 is the §4.05-sensitive path and never
     forks for it — so a child-only mechanism would never see the read that
     matters most."

Nothing in the shipped suite asks whether the boundary is REACHABLE, which is
why a mechanism that enforces nowhere passed every test it had. This file is
that question, in both directions.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import step_input_scope as S                                  # noqa: E402
import step_preflight as SP                                   # noqa: E402


@pytest.fixture(autouse=True)
def _never_leak_an_armed_hook():
    """CPython cannot remove an audit hook. A test that armed one and died
    would impose §4.05 on the REST OF THE SESSION, and the resulting failures
    would be attributed to whatever ran next. Disarm unconditionally."""
    yield
    S.disarm_in_process()


def _project(tmp_path: Path) -> Path:
    """A synthetic run that DISPATCHES: step 31's one declared input
    (step 21's `routed.def`) is present, so `gate()` reaches the step rather
    than refusing for want of it. Same shape as `test_step_preflight`'s
    `_synthetic_run(with_routed_def=True)`, plus an oracle to reach for."""
    p = tmp_path / "run"
    (p / "golden").mkdir(parents=True)
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase3/stage3/pnr").mkdir(parents=True)
    (p / "reports").mkdir(parents=True)
    (p / "golden" / "qor.json").write_text('{"secret": "the oracle"}\n')
    (p / "phase2/stage1/rtl/top.v").write_text("module top(); endmodule\n")
    (p / "phase2/stage2/synth/netlist.v").write_text("module top(); endmodule\n")
    (p / "phase3/stage3/pnr/routed.def").write_text("DESIGN top ;\nEND DESIGN\n")
    (p / "reports" / "drc.rpt").write_text("0 violations\n")
    return p


# --------------------------------------------------------------------------- #
# OFF by default — the merge's own property, which this must not disturb
# --------------------------------------------------------------------------- #
def test_off_by_default_arms_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(S.ENV_SWITCH, raising=False)
    p = _project(tmp_path)
    rec = S.arm_in_process(p, step_id="23")
    assert rec == {"enforced": False}, rec
    assert S.inproc_state()["armed"] is False
    # and the read is untouched
    assert (p / "golden" / "qor.json").read_text().strip().endswith("}")


# --------------------------------------------------------------------------- #
# FORWARD — the read the child locus structurally cannot see
# --------------------------------------------------------------------------- #
def test_an_in_process_oracle_read_is_DENIED(tmp_path, monkeypatch):
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    with S.scoped(p, step_id="23") as rec:
        assert rec["enforced"] is True and rec["locus"] == "in-process"
        with pytest.raises(PermissionError) as ei:
            (p / "golden" / "qor.json").read_text()
    assert "§4.05" in str(ei.value)
    assert "golden/qor.json" in str(ei.value)


def test_observe_mode_RECORDS_rather_than_raising(tmp_path, monkeypatch):
    """The DEFAULT. A misfire here fails every run of the flow, so the default
    must not raise — but a boundary that recorded a crossing and told nobody
    has not observed anything either."""
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.delenv(S.ENV_INPROC, raising=False)
    p = _project(tmp_path)
    with S.scoped(p, step_id="23") as rec:
        assert rec["mode"] == "observe"
        got = (p / "golden" / "qor.json").read_text()      # allowed through …
    assert "the oracle" in got
    assert any("golden/qor.json" in v for v in rec["violations"]), rec


# --------------------------------------------------------------------------- #
# REVERSE — the control that stops "deny everything" from passing the above
# --------------------------------------------------------------------------- #
def test_a_legitimate_design_path_is_NOT_denied(tmp_path, monkeypatch):
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    with S.scoped(p, step_id="23") as rec:
        assert (p / "phase2/stage1/rtl/top.v").read_text().startswith("module")
        assert (p / "reports" / "drc.rpt").read_text().startswith("0")
    assert rec["violations"] == [], rec


def test_a_path_OUTSIDE_the_project_is_untouched(tmp_path, monkeypatch):
    """The deny is scoped to the project so the hook cannot brick the
    interpreter's own imports. A file named `golden/...` elsewhere is not this
    boundary's business."""
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    outside = tmp_path / "golden"
    outside.mkdir()
    (outside / "elsewhere.json").write_text("not the project\n")
    with S.scoped(p, step_id="23"):
        assert (outside / "elsewhere.json").read_text().startswith("not")


def test_the_declaration_WINS_over_the_deny_list(tmp_path, monkeypatch):
    """`required_inputs` is the declared exception, exactly as for the child.
    A step that legitimately reads a flagged path DECLARES it."""
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    S.arm_in_process(p, step_id="23")
    with pytest.raises(PermissionError):
        (p / "golden" / "qor.json").read_text()
    S.disarm_in_process()
    # same file, same mode — declared this time
    S._INPROC.update({"armed": True,
                      "root": str(p.resolve()).rstrip(os.sep) + os.sep,
                      "step": "23", "mode": "deny",
                      "specs": ("golden/qor.json",),
                      "deny": frozenset(S.deny_segments()),
                      "file_re": S._INPROC["file_re"], "violations": []})
    assert "the oracle" in (p / "golden" / "qor.json").read_text()


# --------------------------------------------------------------------------- #
# THE REACHABILITY GUARD — the question nothing in the suite was asking
# --------------------------------------------------------------------------- #
def test_gate_IMPOSES_the_scope_on_the_dispatch(tmp_path, monkeypatch):
    """The one that fails on `origin/main` 75776dbbb.

    `gate()` is the function every declared dispatch site passes through, and
    `test_every_declared_site_is_wired_at_a_real_call_site` already pins that.
    So a boundary installed here is reachable from every step by a guarantee
    that already exists. Before this change, `gate()` dispatched with no scope
    imposed at all and this assertion had nothing to hold.
    """
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    seen = {}

    def _step(*a, **kw):
        seen["state"] = S.inproc_state()
        try:
            (p / "golden" / "qor.json").read_text()
            seen["read"] = "ALLOWED"
        except PermissionError as exc:
            seen["read"] = f"DENIED: {exc}"

        class R:
            name, status, detail = "spy", "PASS", "ran"
        return R()

    SP.gate(p, "phase3_one_shot_runner", "drc",
            lambda d, e: None, _step, p, "top", None, "")

    assert seen, "the step was never dispatched — the fixture, not the boundary"
    assert seen["state"]["armed"] is True, (
        "gate() dispatched the step with NO §4.05 scope imposed on the "
        "process: the boundary is unreachable from the one chokepoint every "
        "step goes through")
    assert seen["read"].startswith("DENIED"), seen["read"]


def test_the_scope_is_LIFTED_after_the_dispatch(tmp_path, monkeypatch):
    """An enforcement that outlived its dispatch would impose one step's scope
    on the next, and the failures would be attributed to the wrong step."""
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)

    class R:
        name, status, detail = "spy", "PASS", "ran"

    SP.gate(p, "phase3_one_shot_runner", "drc",
            lambda d, e: None, lambda *a, **k: R(), p, "top", None, "")

    assert S.inproc_state()["armed"] is False
    assert "the oracle" in (p / "golden" / "qor.json").read_text()


def test_every_dispatch_in_gate_routes_through_the_scope():
    """A THIRD dispatch path added to `gate()` later would bypass the boundary
    silently. There were exactly two, and both had to be routed; this fails if
    a new one is added raw."""
    src = (PROGRAMS / "step_preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "gate")
    raw = [n for n in ast.walk(fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "fn"]
    assert raw == [], (
        f"{len(raw)} dispatch(es) in gate() call fn() directly instead of "
        f"through _scoped_dispatch, so §4.05 is not imposed on them")
    scoped = [n for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_scoped_dispatch"]
    assert len(scoped) == 2, f"expected both dispatches routed, found {len(scoped)}"


# --------------------------------------------------------------------------- #
# PAIRED GUARD
# --------------------------------------------------------------------------- #
def test_a_boundary_that_denies_EVERYTHING_is_not_a_boundary(tmp_path,
                                                             monkeypatch):
    """The always-fires guard.

    A hook that raised on every `open` under the project would satisfy every
    FORWARD assertion above. It dies here: with the scope armed in its
    strictest mode, the design's own tree, the reports tree and the process's
    own imports must all still work. This is also the test that would catch
    the hook re-entering itself — an implementation that imported a module or
    read a file to make its decision recurses on the first `open`.
    """
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    with S.scoped(p, step_id="23"):
        for _ in range(50):                     # re-entrancy would blow up here
            assert (p / "phase2/stage1/rtl/top.v").read_text()
        # the interpreter's own machinery, inside the armed window
        import json as _json                    # noqa: PLC0415
        assert _json.loads("{}") == {}
        assert (p / "reports" / "drc.rpt").read_text()
    assert "phase2" not in S.deny_segments()
    assert "reports" not in S.deny_segments()


def test_the_in_process_locus_and_the_child_agree_on_the_boundary(tmp_path,
                                                                  monkeypatch):
    """Two loci, ONE boundary. The merge's stated property was that parent and
    child consult one list by construction; a second locus must not become the
    second definition the module docstring exists to warn about."""
    monkeypatch.setenv(S.ENV_SWITCH, "1")
    monkeypatch.setenv(S.ENV_INPROC, "deny")
    p = _project(tmp_path)
    _env, meta = S.child_env({S.ENV_SWITCH: "1"}, project=p, step_id="23",
                             guard_dir=p / "_g")
    rec = S.arm_in_process(p, step_id="23")
    assert rec["deny_segments"] == meta["deny_segments"]
    assert sorted(S.inproc_state()["deny"]) == sorted(S.deny_segments())
