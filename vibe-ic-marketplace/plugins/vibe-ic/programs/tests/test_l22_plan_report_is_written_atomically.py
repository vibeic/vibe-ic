#!/usr/bin/env python3
"""vibe-ic#1082 — L22's declared report destination is written atomically.

`l22_analog_verification_plan_emit.py` landed at v1.14.53 writing its `--json`
destination with a direct `out.write_text(...)`, which made it the ONE new
offender `atomic_artifact_write_check` reported against the #1082 residual
baseline (still the only one at v1.14.66, v1.14.71 and on main at v1.14.75 —
the shard simply surfaced it late, it did not land in that window).

Why it matters here specifically: `--json` names the path the flow's `gate:`
line hands to `check_step`, so a `required_outputs` check reads the file's mere
EXISTENCE as "the step produced this". `write_text` creates the final name
first and fills it second, so an emitter that dies in between publishes a
truncated L22 plan under exactly that name.

Both tests below are RED against the pre-fix emitter and GREEN after it is
routed through `_atomic_artefact.write_json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import atomic_artifact_write_check as G  # noqa: E402
import _atomic_artefact as _aa  # noqa: E402
import l22_analog_verification_plan_emit as L22  # noqa: E402

_EMITTER = PROGRAMS / "l22_analog_verification_plan_emit.py"


def test_emitter_is_not_a_new_offender_of_the_1082_gate() -> None:
    """The gate's own AST audit finds no direct write to the declared dest."""
    hits = G.scan_program(_EMITTER)
    assert hits == [], (
        "l22_analog_verification_plan_emit writes its declared report "
        f"destination non-atomically at line(s) "
        f"{[h['line'] for h in hits]} — route it through _atomic_artefact")


def test_gate_over_the_real_programs_dir_reports_no_new_offender(
        capsys) -> None:
    """End-to-end: the shipped gate, the shipped residual, the real tree."""
    rc = G.main([str(PROGRAMS)])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "l22_analog_verification_plan_emit" not in out.err


def test_declared_destination_is_written_through_the_helper(
        tmp_path: Path, monkeypatch) -> None:
    """The `--json` path is published by `_atomic_artefact`, not by a bare
    `write_text`. Recorded at the helper so the assertion is about the write
    that actually happens, not about the source text."""
    seen: list[Path] = []
    real = _aa.write_json

    def _spy(path, obj, *a, **kw):
        seen.append(Path(path))
        return real(path, obj, *a, **kw)

    monkeypatch.setattr(_aa, "write_json", _spy)
    monkeypatch.setattr(L22, "_atomic_write_json", _spy, raising=False)

    project = tmp_path / "proj"
    project.mkdir()
    dest = tmp_path / "reports" / "l22.json"
    rc = L22.main([str(project), "--dry-run", "--json", str(dest)])

    assert rc == 0
    assert seen == [dest], (
        f"the declared destination was not written through _atomic_artefact "
        f"(helper saw {seen})")
    # and the artefact it published is a complete document, not a fragment
    assert json.loads(dest.read_text())["tool"] == L22.TOOL


def test_no_temp_artefact_is_left_beside_the_published_report(
        tmp_path: Path) -> None:
    """Pin: the atomic helper cleans up after itself, so the report directory
    holds the artefact and nothing else a consumer could glob into."""
    project = tmp_path / "proj"
    project.mkdir()
    dest = tmp_path / "reports" / "l22.json"
    assert L22.main([str(project), "--dry-run", "--json", str(dest)]) == 0
    leftovers = [p.name for p in dest.parent.iterdir()
                 if _aa.is_temp_artefact(p)]
    assert leftovers == [], f"temp artefact(s) left behind: {leftovers}"
