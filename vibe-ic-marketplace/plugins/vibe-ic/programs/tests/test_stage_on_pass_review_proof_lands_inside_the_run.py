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

import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import stage_on_pass_review as S  # noqa: E402

SUBJECT = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
STAGE, BAD, GOOD = "stage1", "reject_caravel", "accept_spm"










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





# ── ARM 2: review() called directly, bypassing main's refusal ───────────────



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
