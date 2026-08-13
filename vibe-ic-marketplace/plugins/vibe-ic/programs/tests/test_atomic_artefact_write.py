"""vibe-ic#1082 — the final filename must appear only when the write finished.

Adopted from ORFS `flow/scripts/flow.sh:9` (`trap 'mv …tmp.log …log' EXIT`):
"the final filename exists" should imply "the step ran to completion", by
construction rather than by convention.

Two things are under test and they are different: the SEAM
(`programs/_atomic_write.py`) must actually deliver the invariant, and the
RATCHET (`programs/atomic_artefact_write_check.py`) must actually notice a new
violation. A seam nobody adopts and a ratchet with a hole both look green.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _atomic_write as AW                      # noqa: E402
import atomic_artefact_write_check as CHECK     # noqa: E402


# ═════════════════════ the seam ═════════════════════
def test_a_failed_write_leaves_no_file_under_the_final_name(tmp_path):
    """THE INVARIANT. A write that dies mid-way must leave the final name
    absent, so `required_outputs` answering "missing" is the TRUE statement
    about what happened."""
    target = tmp_path / "reports" / "r.json"

    class Boom:
        pass

    with pytest.raises(TypeError):
        AW.write_json_atomic(target, {"bad": Boom()})
    assert not target.exists(), (
        "the final name exists after a failed write — a reader cannot tell "
        "this from a completed step")
    assert not list(tmp_path.rglob(f"*{AW.TMP_SUFFIX}*")), (
        "a temporary was stranded; a directory that slowly fills with them is "
        "its own defect")


def test_a_failed_write_does_not_destroy_the_previous_artefact(tmp_path):
    """The other half. `json.dump(obj, open(p,"w"))` truncates BEFORE it
    discovers the object is unserialisable, so a failed re-write loses the
    good file too. Serialising first is what prevents that."""
    target = tmp_path / "r.json"
    AW.write_json_atomic(target, {"good": 1})
    with pytest.raises(TypeError):
        AW.write_json_atomic(target, {"bad": object()})
    assert json.loads(target.read_text()) == {"good": 1}


def test_a_completed_write_lands_whole(tmp_path):
    target = tmp_path / "deep" / "nested" / "r.json"
    AW.write_json_atomic(target, {"a": [1, 2, 3]})
    assert json.loads(target.read_text()) == {"a": [1, 2, 3]}
    assert AW.write_text_atomic(tmp_path / "t.txt", "hello").read_text() == "hello"


def test_the_temporary_is_created_beside_the_target(tmp_path, monkeypatch):
    """NOT a detail. `os.replace` is atomic only within one filesystem, so a
    temporary in the system temp dir would degrade to copy-then-unlink and lose
    the guarantee SILENTLY — the exact failure mode this seam removes."""
    seen = {}
    real = AW.tempfile.mkstemp

    def _spy(*a, **kw):
        seen["dir"] = kw.get("dir")
        return real(*a, **kw)

    monkeypatch.setattr(AW.tempfile, "mkstemp", _spy)
    target = tmp_path / "sub" / "r.json"
    AW.write_json_atomic(target, {"x": 1})
    assert seen["dir"] == str(target.parent)


# ═════════════════════ the ratchet ═════════════════════
_OFFENDER = '''
import argparse
from pathlib import Path
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("{}")
'''

_CONVERTED = '''
import argparse
from _atomic_write import write_json_atomic
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    write_json_atomic(args.json, {})
'''


def test_the_ratchet_sees_the_dominant_spelling(tmp_path):
    """REGRESSION on this gate's own first version, which reported 533 instead
    of 548 because it matched only receivers that literally named `args.json`.
    `out = Path(args.json); out.write_text(...)` was invisible, and a new
    offender written that way would have passed. A ratchet with a hole is worse
    than none: it publishes a number nobody re-derives."""
    tree = ast.parse(_OFFENDER)
    assert CHECK._declares_json_arg(tree)
    assert CHECK._writes_through_json(tree) == 1


def test_a_converted_program_is_not_an_offender(tmp_path):
    tree = ast.parse(_CONVERTED)
    assert CHECK._imports_seam(tree)
    d = tmp_path / "programs"
    d.mkdir()
    (d / "conv.py").write_text(_CONVERTED)
    assert CHECK.offenders(d) == []


def test_a_new_offender_is_refused_against_a_baseline(tmp_path, capsys):
    """The gate must BLOCK, not merely mention it."""
    d = tmp_path / "programs"
    d.mkdir()
    (d / "bad.py").write_text(_OFFENDER)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"count": 0, "offenders": []}))
    rc = CHECK.main([str(d), "--baseline", str(bl)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "bad.py" in out


def test_writing_a_growing_baseline_is_refused_without_a_stated_reason(
        tmp_path, capsys):
    """A ratchet whose record can be raised silently is not a ratchet. The only
    way up is `--ruler-widened '<why>'`, and the reason is stored."""
    d = tmp_path / "programs"
    d.mkdir()
    (d / "bad.py").write_text(_OFFENDER)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"count": 0, "offenders": []}))
    assert CHECK.main([str(d), "--baseline", str(bl), "--write-baseline"]) == 1
    assert "refusing to GROW" in capsys.readouterr().out

    assert CHECK.main([str(d), "--baseline", str(bl), "--write-baseline",
                       "--ruler-widened", "detector now follows aliases"]) == 0
    rec = json.loads(bl.read_text())
    assert rec["offenders"] == ["bad.py"]
    assert rec["ruler_widened"] == "detector now follows aliases"


def test_the_shipped_baseline_matches_the_shipped_tree():
    """The anchor: the committed record must describe THIS tree, or the ratchet
    is measuring a tree that no longer exists."""
    bl = json.loads((PROGRAMS / CHECK.BASELINE_NAME).read_text())
    live = CHECK.offenders(PROGRAMS)
    assert sorted(bl["offenders"]) == sorted(live), (
        f"baseline {len(bl['offenders'])} vs live {len(live)}; "
        f"new={sorted(set(live) - set(bl['offenders']))[:5]} "
        f"gone={sorted(set(bl['offenders']) - set(live))[:5]}")
    assert live, "an empty offender set would make every assertion above vacuous"
