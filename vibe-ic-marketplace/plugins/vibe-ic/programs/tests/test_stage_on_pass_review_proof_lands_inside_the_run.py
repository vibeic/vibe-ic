"""A rejection's emitted regression must land where the RUN can open it.

MEASURED ON v1.13.66, unmodified, with `--emit-test` pointed at an absolute
path outside the run:

    rc = 1                         (REJECT — the rejection stood)
    unproven_rejections = 0        (it counted as PROVEN)
    test = /tmp/.../test_r1_intent_top_not_built.py   (absolute, outside)
    and the file was really written there

`Path("/run") / "/tmp/x"` is `/tmp/x` — an absolute `emit_test_dir:` does not
join, it REPLACES. `unproven()` then asked only whether the `test` field was a
non-empty string, so a path to a file nobody at the run can open satisfied
`rejection_requires`. A rejection whose evidence lands where nobody will look is
an unproven rejection wearing a proof, and the unproven branch exists precisely
to refuse those.

REFUSED, NOT CLAMPED — the decision, and why. Clamping an out-of-run
destination back under the run would make the flow's declaration and the run's
behaviour disagree silently, which is the same defect as a field the engine
ignores, pointed the other way. The author's declaration is wrong; the engine
says so where they can fix it.

Refused in THREE places, because they close different holes:
  * `main`   — the whole run declines (rc 2) before any rule is evaluated;
  * `review` — a caller reaching the function directly writes nothing;
  * `unproven` — and if a `test` field ever arrives that the run cannot open,
    the rejection is demoted whatever wrote it.

Every arm carries a CONTROL: the shipped declaration, whose proof lands inside
the run and whose verdicts are unchanged.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import on_pass_review_declared_command_runs_check as K  # noqa: E402
import stage_on_pass_review as S  # noqa: E402

SUBJECT = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
STAGE, BAD, GOOD = "stage1", "reject_caravel", "accept_spm"


def _decl() -> dict:
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    return next(st["on_pass_review"] for st in doc["stages"]
                if str(st.get("id")) == STAGE)


def _tree(tmp_path: Path, name: str, tree: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    K.materialise(STAGE, tree, root)
    return root


def _cli(tmp_path: Path, name: str, tree: str, extra=()) -> tuple[int, str]:
    root = _tree(tmp_path, name, tree)
    rep = root / "reports" / "flow_compliance.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({"steps": [{"stage": STAGE, "status": "PASS"}]}))
    proc = subprocess.run(
        [sys.executable, str(SUBJECT), "--flow-def", str(FLOW), ".",
         "--stage", STAGE, "--json", "rec.json",
         "--compliance", "reports/flow_compliance.json"] + list(extra),
        cwd=str(root), capture_output=True, text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _control(tmp_path: Path, tag: str) -> None:
    """The shipped declaration: BAD refused with its proof inside the run,
    GOOD accepted. Asserted in every arm."""
    root = _tree(tmp_path, f"ctl_bad_{tag}", BAD)
    rec = S.review(root, STAGE, _decl())
    rej = rec.get("rejections") or []
    assert rej and not (rec.get("unproven_rejections") or [])
    assert rec["emit_outside_run"] is False
    for r in rej:
        assert S.proof_is_inside_the_run(root, r["test"]), r["test"]
        assert not Path(r["test"]).is_absolute()
    good = _tree(tmp_path, f"ctl_good_{tag}", GOOD)
    assert not (S.review(good, STAGE, _decl()).get("rejections") or [])


# ── the predicates, alone ───────────────────────────────────────────────────

def test_an_absolute_emit_dir_replaces_rather_than_joins(tmp_path):
    """The mechanism, stated as an assertion so nobody has to trust the prose."""
    assert str(Path("/run") / "/tmp/x") == "/tmp/x"
    assert S.emit_dir_escapes(tmp_path, Path("/tmp/x")) is True
    assert S.emit_dir_escapes(tmp_path, tmp_path / "reports" / "x") is False
    assert S.emit_dir_escapes(tmp_path, tmp_path) is False
    # ...and a relative walk back out is an escape too, which a string test for
    # `is_absolute()` alone would have missed.
    assert S.emit_dir_escapes(tmp_path, tmp_path / ".." / "elsewhere") is True


def test_a_proof_must_be_run_relative_AND_on_disk(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "t.py").write_text("x = 1\n")
    assert S.proof_is_inside_the_run(tmp_path, "reports/t.py") is True
    # relative but never written
    assert S.proof_is_inside_the_run(tmp_path, "reports/missing.py") is False
    # absolute, and it exists — the exact shape that read as PROVEN before
    assert S.proof_is_inside_the_run(
        tmp_path, str(tmp_path / "reports" / "t.py")) is False
    for empty in ("", None, [], 0):
        assert S.proof_is_inside_the_run(tmp_path, empty) is False


# ── ARM 1: the CLI, which is how the flow invokes it ────────────────────────

def test_arm1_an_escaping_emit_test_declines_the_run(tmp_path):
    rc, out = _cli(tmp_path, "arm1", BAD,
                   ["--emit-test", str(tmp_path / "outside")])
    assert rc == 2, out
    assert "NOT CHECKED" in out and "OUTSIDE the run" in out
    assert "REFUSED, NOT CLAMPED" in out
    assert not (tmp_path / "outside").exists(), (
        "nothing may be written outside the run, not even the refused proof")
    _control(tmp_path, "arm1")


def test_arm1_control_the_same_invocation_without_the_escape_still_rejects(
        tmp_path):
    """The arm must not be passing because the program broke. Same tree, same
    argv, no `--emit-test`: rc 1, as before the fix."""
    assert _cli(tmp_path, "arm1c", BAD)[0] == 1
    assert _cli(tmp_path, "arm1g", GOOD)[0] == 0


# ── ARM 2: review() called directly, bypassing main's refusal ───────────────

def test_arm2_review_writes_nothing_outside_and_demotes_the_rejection(
        tmp_path):
    """The second hole: a caller that never enters `main`. The rule still
    fires — this is not silencing the finding — but the rejection lands in
    `unproven_rejections` with `test` named as the missing part, which is what
    the tier means."""
    root = _tree(tmp_path, "arm2", BAD)
    outside = tmp_path / "arm2_outside"
    rec = S.review(root, STAGE, _decl(), emit_dir=outside)
    assert rec["emit_outside_run"] is True
    assert (rec.get("rejections") or []) == [], (
        "an unprovable rejection may not be reported as a proven one")
    unproven = rec.get("unproven_rejections") or []
    assert len(unproven) == 1
    assert unproven[0]["missing_evidence"] == ["test"]
    assert "emit_outside_run" in unproven[0]
    assert not outside.exists(), "nothing may be written outside the run"
    _control(tmp_path, "arm2")


# ── ARM 3: the definition of PROVEN, independent of who wrote the field ─────

@pytest.mark.parametrize("bad_test", ["/etc/passwd", "reports/never_written.py"])
def test_arm3_a_test_field_the_run_cannot_open_is_not_proof(tmp_path, bad_test):
    """`unproven()` used to accept any non-empty string. Both of these are
    non-empty and neither is a proof the run can open."""
    requires = ("intent", "artefact", "contradiction", "test")
    finding = {"intent": {"a": 1}, "artefact": {"b": 2},
               "contradiction": "x", "test": bad_test}
    assert S.unproven(finding, requires, tmp_path) == ["test"]
    # ...and the same field IS proof once it is inside the run and written.
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / "real.py").write_text("x = 1\n")
    finding["test"] = "reports/real.py"
    assert S.unproven(finding, requires, tmp_path) == []


def test_arm3_a_caller_with_no_run_keeps_the_old_field_presence_rule(tmp_path):
    """`project` is optional so this change cannot silently retier a caller
    that has no run in hand; `review()` always passes it."""
    requires = ("test",)
    assert S.unproven({"test": "/anywhere.py"}, requires) == []
    assert S.unproven({"test": ""}, requires) == ["test"]


# ── the shipped flow declares nothing that escapes ─────────────────────────

def test_every_shipped_emit_test_dir_is_run_relative():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    declared = {str(st.get("id")): st["on_pass_review"].get("emit_test_dir")
                for st in (doc.get("stages") or [])
                if isinstance(st.get("on_pass_review"), dict)}
    assert declared, "the flow declares no on-pass review at all"
    for stage, value in declared.items():
        assert value and not Path(str(value)).is_absolute(), (stage, value)
