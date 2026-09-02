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

import pytest

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




# --------------------------------------------------------------------------- #
# THE FIXTURES, AND WHY THERE ARE TWO
# --------------------------------------------------------------------------- #
# Both cases below used to drive ONE fixture: an empty project. That reached
# `run()`'s first guard, returned `status: SKIPPED`, and — since #1980 gave the
# emitter a real exit-code table — rc 2, so `assert rc == 0` failed on a
# program that was behaving exactly as designed. `_STATUS_EXIT` says rc 2 for
# SKIPPED is deliberate and is NOT rc 0, so the tier is not the thing to move.
#
# The fixture is. An empty project also never exercised the write this file is
# about: it published a four-line skip report, not a plan, so the "complete
# document" assertion was checking the smallest artefact the emitter can make.
# Both statuses are now driven, because #1082 is not about the happy path —
# `analog_a5_layout_emit` states the rule in its own words: "a run that ends in
# ENV_UNAVAILABLE is exactly the run whose report a reader most needs, so it is
# written like any other". A skip report published half-written under the name
# a `required_outputs` check opens is the same defect as a truncated plan.
_DIGITAL_CATEGORIES = [
    "Register access (read/write to all register fields)",
    "Nominal transfer / transaction across the protocol's operating modes",
    "Error and fault condition detection and handling",
    "Reset behavior verification",
    "Back-to-back / sustained operation",
]


def _write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _empty_project(tmp_path: Path) -> Path:
    """No L5, no L22 — `run()` SKIPs, and still owes a whole report."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    return project


def _analog_project(tmp_path: Path) -> Path:
    """A registry-matched analog class with structured L5 blocks, so the
    emitter reaches OK and publishes a real plan — the artefact whose
    truncation #1082 is about."""
    project = tmp_path / "proj"
    gd = project / "phase1" / "generated_docs"
    _write_json(gd / "L1_DATASHEET.json", {
        "doc_id": "L1", "class": "mixed_signal_adc",
        "description": ("A data converter with an analog conversion core and "
                        "a digital serial output bitstream."),
    })
    _write_json(gd / "L5_ADI_SPEC.json", {
        "doc_id": "L5", "no_analog": False,
        "analog_blocks": [
            {"name": "supply_regulator", "type": "ldo",
             "low_confidence": False,
             "spec": {"specs": [
                 {"name": "Line regulation", "target_raw": "<= 1",
                  "unit": "mV/V", "source": "input/docs/L5_analog.md"}]}},
            {"name": "conversion_modulator", "type": "delta_sigma",
             "low_confidence": False,
             "spec": {"specs": [
                 {"name": "SNDR", "target_raw": ">= 72", "unit": "dB",
                  "source": "input/docs/L5_analog.md"}]}},
        ],
        "signaling_summary": "Digital serial output bitstream.",
    })
    _write_json(gd / "L22_VERIFICATION_PLAN.json", {
        "doc_id": "L22", "doc_name": "L22_VERIFICATION_PLAN",
        "applicability": "APPLICABLE", "extraction_status": "EXTRACTED",
        "fields": {"coverage_goals": [], "formal_properties": [],
                   "regression_matrix": {},
                   "verification_plan_present": "implicit",
                   "verification_categories_derived_from_spec":
                       _DIGITAL_CATEGORIES},
    })
    return project


#: `(builder, expected_rc, expected_status)`. The rc is spelled literally
#: rather than read out of `L22._STATUS_EXIT`, which would make the assertion
#: agree with the table by construction and pin nothing.
_CASES = [
    (_analog_project, 0, "OK"),
    (_empty_project, 2, "SKIPPED"),
]

@pytest.mark.parametrize("build,expected_rc,expected_status", _CASES)
def test_declared_destination_is_written_through_the_helper(
        tmp_path: Path, monkeypatch, build, expected_rc,
        expected_status) -> None:
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

    project = build(tmp_path)
    dest = tmp_path / "reports" / "l22.json"
    rc = L22.main([str(project), "--dry-run", "--json", str(dest)])

    published = json.loads(dest.read_text())
    assert published["status"] == expected_status, published
    assert rc == expected_rc, (
        f"{expected_status} must reach the process boundary as rc "
        f"{expected_rc}; see l22_analog_verification_plan_emit._STATUS_EXIT")
    assert seen == [dest], (
        f"the declared destination was not written through _atomic_artefact "
        f"(helper saw {seen})")
    # and the artefact it published is a complete document, not a fragment
    assert published["tool"] == L22.TOOL


def test_the_published_report_is_whole_and_not_a_prefix(tmp_path: Path) -> None:
    """The OK path publishes the report #1082 is about, entire.

    `--json` names the emitter's RUN RECORD, not the plan document — the plan
    goes into L22 itself and `--dry-run` writes none. So "whole" is a claim
    about this record's own substantive keys: `emitted_count` and
    `blocks_total` are the last things a truncation would keep, and the skip
    report carries neither. Asserted against the analog fixture because the
    SKIPPED record is four keys long and would survive almost any prefix cut.
    """
    project = _analog_project(tmp_path)
    dest = tmp_path / "reports" / "l22.json"
    assert L22.main([str(project), "--dry-run", "--json", str(dest)]) == 0
    text = dest.read_text()
    doc = json.loads(text)                       # parses, so it is not a prefix
    assert doc["status"] == "OK"
    assert doc["emitted_count"] == 2 and doc["blocks_total"] == 2, doc
    assert text.endswith("\n")

    skip_dest = tmp_path / "reports" / "l22_skip.json"
    assert L22.main([str(_empty_project(tmp_path / "b")), "--dry-run",
                     "--json", str(skip_dest)]) == 2
    assert "emitted_count" in json.loads(skip_dest.read_text())
    assert len(text) > len(skip_dest.read_text()), (
        "the OK record must carry more than the skip record, or this file's "
        "'complete document' claim is being made about the smallest artefact "
        "the emitter can produce")


@pytest.mark.parametrize("build,expected_rc,expected_status", _CASES)
def test_no_temp_artefact_is_left_beside_the_published_report(
        tmp_path: Path, build, expected_rc, expected_status) -> None:
    """Pin: the atomic helper cleans up after itself, so the report directory
    holds the artefact and nothing else a consumer could glob into."""
    project = build(tmp_path)
    dest = tmp_path / "reports" / "l22.json"
    assert L22.main([str(project), "--dry-run", "--json",
                     str(dest)]) == expected_rc
    leftovers = [p.name for p in dest.parent.iterdir()
                 if _aa.is_temp_artefact(p)]
    assert leftovers == [], f"temp artefact(s) left behind: {leftovers}"
