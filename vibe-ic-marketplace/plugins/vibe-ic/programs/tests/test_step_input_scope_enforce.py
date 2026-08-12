"""§4.05 must be a MECHANISM, and a mechanism has to be shown ACTING.

vibe-ic#1079. The load-bearing tests here are not the ones where the enforcer
reports clean — they are the two-arm pair the issue itself asked for: a step
that reaches for an out-of-scope path must FAIL with enforcement on and must
SUCCEED with it off. Without the second arm this is a ban, not a check.

Every program under test is a real file executed by a real subprocess through
the real `run_scoped`, because the thing being tested is what a CHILD PROCESS
is able to do — which a fixture standing in for the child cannot answer.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import step_input_scope_enforce as se  # noqa: E402
import _reference_flow_boundary as _rfb  # noqa: E402

_T = 55

#: A real QoR-rules artifact by the AUTHORITY's own predicate — metric name ->
#: {value, compare}. Asserted below rather than assumed, so a change to the
#: predicate breaks the fixture instead of silently making the test vacuous.
_ORACLE_JSON = json.dumps({
    "worst_slack": {"value": 0.12, "compare": ">="},
    "total_power_mw": {"value": 41.7, "compare": "<="},
})

#: A RECIPE under the same mixed tree: a setting, never a threshold.
_RECIPE_JSON = json.dumps({"core_utilization": 45, "place_density": 0.6})


def _proj(tmp_path: Path, files: dict) -> Path:
    root = tmp_path / "proj"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def _prog(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "child.py"
    p.write_text(textwrap.dedent(body))
    return p


def _run(project: Path, child: Path, *extra: str):
    return se.main(["--project", str(project), *extra, "--",
                    sys.executable, str(child)])


# --------------------------------------------------------------------------
# THE TWO-ARM CONTROL the issue asked for, and the reason it is two arms:
# "a step that reaches for an out-of-scope path must FAIL with the enforcement
# on, and must succeed with it off. Without the second arm this is a ban rather
# than a check."
# --------------------------------------------------------------------------

def test_enforcement_ON_makes_the_oracle_read_IMPOSSIBLE(tmp_path, capsys):
    """Not "reported" — impossible. The child's own `open()` raises."""
    project = _proj(tmp_path, {"input/spec.md": "spec",
                               "golden/answer.txt": "42"})
    child = _prog(tmp_path, """
        import sys
        try:
            open("golden/answer.txt").read()
        except PermissionError as exc:
            print("DENIED:", exc); sys.exit(3)
        print("READ THE GOLDEN"); sys.exit(0)
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "golden/answer.txt" in out and "OFF-LIMITS" in out, out
    assert "child rc=3" in out, out          # the read did not succeed
    assert "was DENIED" in out, out


def test_enforcement_OFF_lets_the_same_step_finish(tmp_path, capsys):
    """The other arm. Same project, same child, enforcement off — the read
    goes through, so what the ON arm proved is the enforcement and not the
    child simply being broken."""
    project = _proj(tmp_path, {"input/spec.md": "spec",
                               "golden/answer.txt": "42"})
    child = _prog(tmp_path, """
        import sys
        try:
            open("golden/answer.txt").read()
        except PermissionError as exc:
            print("DENIED:", exc); sys.exit(3)
        print("READ THE GOLDEN"); sys.exit(0)
        """)
    rc = _run(project, child, "--observe-only")
    out = capsys.readouterr().out
    assert "child rc=0" in out, out          # the read SUCCEEDED
    assert "was allowed (observe-only)" in out, out
    # observing is not forgiving: the violation is still the verdict
    assert rc == 1, out


def test_a_step_that_stays_in_scope_passes(tmp_path, capsys):
    project = _proj(tmp_path, {"input/spec.md": "spec",
                               "golden/answer.txt": "42"})
    child = _prog(tmp_path, """
        print(open("input/spec.md").read())
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "no OFF-LIMITS path reached" in out, out


# --------------------------------------------------------------------------
# The MIXED tree. `reference_flow/` is recipe AND oracle and the boundary runs
# between FILES inside it, so a name rule would ban the recipe the flow is
# supposed to read.
# --------------------------------------------------------------------------

def test_the_fixture_really_is_what_the_authority_calls_oracle():
    """Pins the fixture to the predicate. Without this, a change to
    `is_oracle_qor_rules` would leave the two tests below passing for the
    wrong reason — both files simply allowed."""
    assert _rfb.is_oracle_qor_rules(_ORACLE_JSON) is True
    assert _rfb.is_oracle_qor_rules(_RECIPE_JSON) is False


def test_a_RECIPE_under_the_mixed_tree_is_allowed(tmp_path, capsys):
    project = _proj(tmp_path, {"reference_flow/config.json": _RECIPE_JSON})
    child = _prog(tmp_path, """
        print(open("reference_flow/config.json").read())
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 0, out


def test_an_ORACLE_under_the_same_mixed_tree_is_denied(tmp_path, capsys):
    """Same directory, same suffix — only the CONTENT differs, and only the
    content decides."""
    project = _proj(tmp_path, {"reference_flow/config.json": _RECIPE_JSON,
                               "reference_flow/metadata.json": _ORACLE_JSON})
    child = _prog(tmp_path, """
        import sys
        open("reference_flow/config.json").read()      # legal
        try:
            open("reference_flow/metadata.json").read()
        except PermissionError:
            sys.exit(3)
        sys.exit(0)
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "reference_flow/metadata.json" in out, out
    assert "config.json" not in out, out
    assert "child rc=3" in out, out


# --------------------------------------------------------------------------
# The instrument's own failure modes. "What would this look like if it were
# broken?" must not have the same answer as "what does it look like when it is
# fine."
# --------------------------------------------------------------------------

def test_a_shim_that_did_not_load_REFUSES_and_never_passes(tmp_path, capsys, monkeypatch):
    """`sitecustomize` loses to any earlier one on PYTHONPATH, and loses
    SILENTLY: the log stays empty and every run reports no violation. Scoring
    that PASS would make the enforcement's failure mode a green tick."""
    monkeypatch.setattr(se, "write_shim",
                        lambda where: (where.mkdir(parents=True, exist_ok=True)
                                       or where))
    project = _proj(tmp_path, {"golden/answer.txt": "42"})
    child = _prog(tmp_path, """
        open("golden/answer.txt").read()
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "REFUSED" in out and "did not load" in out, out


def test_it_refuses_when_given_no_command(tmp_path, capsys):
    project = _proj(tmp_path, {"input/spec.md": "spec"})
    rc = se.main(["--project", str(project)])
    assert rc == 2, capsys.readouterr().out


def test_it_refuses_when_the_project_is_not_a_directory(tmp_path, capsys):
    rc = se.main(["--project", str(tmp_path / "nope"), "--", "true"])
    assert rc == 2, capsys.readouterr().out


# --------------------------------------------------------------------------
# Scope of the judgement.
# --------------------------------------------------------------------------

def test_WRITING_into_an_oracle_named_path_is_not_a_violation(tmp_path, capsys):
    """§4.05 bans READING the answer. A run that creates its own
    `reports/.../golden_summary` is not consulting one, and scoring writes
    would make the enforcement fire on the flow's own output."""
    project = _proj(tmp_path, {"input/spec.md": "spec"})
    child = _prog(tmp_path, """
        import pathlib
        p = pathlib.Path("golden/mine.txt")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("produced here")
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 0, out


def test_paths_OUTSIDE_the_project_are_not_judged(tmp_path, capsys):
    """The PDK, the plugin's own source and the standard library all live
    outside the design tree. Judging them would make every step a violation."""
    outside = tmp_path / "elsewhere" / "golden"
    outside.mkdir(parents=True)
    (outside / "answer.txt").write_text("42")
    project = _proj(tmp_path, {"input/spec.md": "spec"})
    child = _prog(tmp_path, f"""
        print(open({str(outside / 'answer.txt')!r}).read())
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 0, out


def test_the_segments_come_from_the_AUTHORITY_not_a_local_copy():
    """`_reference_flow_boundary` exists because two shipped programs once held
    contradictory positions about the same directory. A second copy of that
    vocabulary in this file would recreate exactly that, so the enforcer must
    have none — it must follow the module if the module changes.
    """
    src = (_PROGRAMS / "step_input_scope_enforce.py").read_text()
    for seg in sorted(_rfb.ORACLE_TREE_SEGMENTS | _rfb.REFERENCE_FLOW_TREE_SEGMENTS):
        assert f'"{seg}"' not in src and f"'{seg}'" not in src, (
            f"{seg!r} is spelled literally in the enforcer; it must come from "
            f"_reference_flow_boundary so the two can never disagree")


def test_the_report_names_what_it_watched(tmp_path):
    """A verdict whose scope is not written down cannot be audited later."""
    project = _proj(tmp_path, {"input/spec.md": "spec"})
    child = _prog(tmp_path, "print(open('input/spec.md').read())")
    out = tmp_path / "r.json"
    rc = se.main(["--project", str(project), "--step", "9",
                  "--json", str(out), "--", sys.executable, str(child)])
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "PASS"
    assert doc["step"] == "9"
    assert doc["enforced"] is True
    assert set(doc["segments"]) == set(_rfb.ORACLE_TREE_SEGMENTS)


def test_it_runs_as_a_cli(tmp_path):
    """The gate has to work the way the flow would invoke it, not only the way
    the tests import it."""
    project = _proj(tmp_path, {"input/spec.md": "spec", "golden/a.txt": "42"})
    child = _prog(tmp_path, "open('golden/a.txt').read()")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "step_input_scope_enforce.py"),
         "--project", str(project), "--", sys.executable, str(child)],
        capture_output=True, text=True, timeout=_T)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "golden/a.txt" in r.stdout, r.stdout


# --------------------------------------------------------------------------
# The three channels the first draft did not have. Each is here because it is
# a read the earlier `io.open`-rebinding version could not see or a case it
# judged wrongly — so each test fails if that capability is taken back out.
# --------------------------------------------------------------------------

def test_the_hook_sees_a_read_that_BYPASSES_the_python_open_name(tmp_path, capsys):
    """Rebinding `io.open` misses anything that did not go through the name.

    This child captures `open` into a local BEFORE the read and reaches the
    file through `os.open` at the descriptor level — neither touches the
    rebound `builtins.open`. `sys.addaudithook` sits under both because
    CPython raises the `open` event from C.
    """
    project = _proj(tmp_path, {"golden/answer.txt": "42"})
    child = _prog(tmp_path, """
        import os, sys
        try:
            fd = os.open("golden/answer.txt", os.O_RDONLY)
        except PermissionError:
            sys.exit(3)
        os.close(fd); sys.exit(0)
        """)
    rc = _run(project, child)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "child rc=3" in out, out          # the descriptor was never handed out


def test_a_DECLARED_input_is_not_denied_even_inside_an_oracle_named_tree(
        tmp_path, capsys, monkeypatch):
    """The declaration WINS. A step cannot be denied its own declared input.

    Used as an EXCEPTION to the ban, never as an allow-list: measured, the
    declared set covers 29% of real reads, so as an allow-list it would deny
    two reads in three.
    """
    project = _proj(tmp_path, {"golden/answer.txt": "42"})
    monkeypatch.setattr(se, "declared_paths",
                        lambda project, step_id, flow=None:
                        ["golden/answer.txt"] if step_id else [])
    child = _prog(tmp_path, """
        print(open("golden/answer.txt").read())
        """)
    assert _run(project, child, "--step", "9") == 0, capsys.readouterr().out
    # and WITHOUT the declaration the very same read is refused
    capsys.readouterr()
    assert _run(project, child) == 1, capsys.readouterr().out


def test_an_env_var_pointing_at_the_oracle_is_removed_from_the_child(tmp_path, monkeypatch):
    """The second channel. Small here by measurement — the plugin's whole env
    surface is container images, PDK roots and tool paths — but real, and
    closing it costs one pass over the environment."""
    project = _proj(tmp_path, {"reference_flow/metadata.json": _ORACLE_JSON,
                               "reference_flow/config.json": _RECIPE_JSON})
    oracle = [r for r, _s in se.resolve_oracle_files(project)]
    assert oracle == ["reference_flow/metadata.json"], oracle
    env = {"ANSWER_KEY": str(project / "reference_flow" / "metadata.json"),
           "FLOW_CFG": str(project / "reference_flow" / "config.json"),
           "PATH": "/usr/bin:/bin"}
    out, dropped = se.scrub_env(env, project, oracle)
    assert dropped == ["ANSWER_KEY"], dropped
    assert "ANSWER_KEY" not in out
    assert out["FLOW_CFG"] == env["FLOW_CFG"]   # the recipe survives
    assert out["PATH"] == env["PATH"]
