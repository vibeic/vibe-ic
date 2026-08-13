"""S7 (vibe-ic#1097) — a step's inputs travel as ONE file, or the bundle says so.

ORFS emits a stage's whole input set plus an environment snapshot as a single
tarball (`flow/util/utils.mk:158-167`, `flow/util/makeIssue.sh:13-45`). Measured
here before the fix: `grep -rloE 'tarfile|shutil\\.make_archive|\\.tar\\.gz'
programs/*.py` -> 0 files.

Every test drives the REAL flow definition and the REAL resolvers rather than a
fixture copy of the declarations, for the reason `step_required_inputs_check`
imports its resolver instead of owning one: two notions of "this artefact
exists" is how the two halves of one contract end up disagreeing.
"""
from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import step_repro_bundle as B  # noqa: E402

#: A real step with three declared, project-relative inputs (STA at step 23):
#:   phase3/stage3/extracted/parasitic.spef OR .../*.spef
#:   phase2/stage2/constraints/*.sdc
#:   phase2/stage2/constraints/pvt_matrix.json
STEP = "23"
#: A real step the flow declares with NO `required_inputs`.
STEP_UNDECLARED = "32"


def _project(tmp_path: Path, *, spef=True, sdc=True, pvt=True) -> Path:
    p = tmp_path / "proj"
    (p / "phase3/stage3/extracted").mkdir(parents=True)
    (p / "phase2/stage2/constraints").mkdir(parents=True)
    if spef:
        (p / "phase3/stage3/extracted/parasitic.spef").write_text("*SPEF\n")
    if sdc:
        (p / "phase2/stage2/constraints/top.sdc").write_text("create_clock\n")
    if pvt:
        (p / "phase2/stage2/constraints/pvt_matrix.json").write_text("{}\n")
    return p


def test_a_complete_bundle_contains_every_declared_input(tmp_path):
    p = _project(tmp_path)
    out = tmp_path / "b.tar.gz"
    rep = B.write_bundle(p, [STEP], out)
    assert rep["verdict"] == "COMPLETE", rep
    assert out.is_file()
    got = {f["path"] for f in rep["files"]}
    assert got == {
        "phase3/stage3/extracted/parasitic.spef",
        "phase2/stage2/constraints/top.sdc",
        "phase2/stage2/constraints/pvt_matrix.json",
    }, got
    with tarfile.open(out) as tf:
        names = set(tf.getnames())
    for rel in got:
        assert f"inputs/{rel}" in names, names


def test_an_unresolvable_input_makes_it_INCOMPLETE_and_NAMES_it(tmp_path):
    """The honesty property. A partial bundle must not read as a bundle."""
    p = _project(tmp_path, pvt=False)
    rep = B.collect(p, [STEP])
    assert rep["verdict"] == "INCOMPLETE", rep
    assert rep["ok"] is False
    missing = [m["path"] for m in rep["missing"]]
    assert any("pvt_matrix.json" in str(m) for m in missing), rep["missing"]
    # and the two that ARE there are still bundled — evidence is not withheld
    assert len(rep["files"]) == 2, rep["files"]


def test_a_step_declaring_NO_inputs_is_REFUSED_not_an_empty_success(tmp_path):
    """`UNDECLARED` is not "has none". An empty archive reported as success is
    the vacuous pass this repo removes from instruments one at a time."""
    p = _project(tmp_path)
    rep = B.collect(p, [STEP_UNDECLARED])
    assert rep["verdict"] == "REFUSED", rep
    assert rep["ok"] is False
    assert "UNKNOWN, not empty" in rep["error"], rep["error"]


def test_an_unknown_step_id_is_REFUSED(tmp_path):
    rep = B.collect(_project(tmp_path), ["NO_SUCH_STEP"])
    assert rep["verdict"] == "REFUSED", rep
    assert "no such step id" in rep["error"], rep["error"]


def test_the_manifest_travels_INSIDE_the_archive(tmp_path):
    """A bundle copied without its caller's log still states its completeness."""
    p = _project(tmp_path, pvt=False)
    out = tmp_path / "b.tar.gz"
    B.write_bundle(p, [STEP], out)
    with tarfile.open(out) as tf:
        doc = json.loads(tf.extractfile("MANIFEST.json").read().decode())
    assert doc["verdict"] == "INCOMPLETE", doc
    assert doc["missing"], doc
    assert doc["environment"]["python"], doc["environment"]


def test_an_oversized_input_is_NAMED_not_silently_dropped(tmp_path):
    """Over the cap it leaves the archive — but it leaves a record, with its
    size. Silently dropping it would make the reader think it was there."""
    p = _project(tmp_path)
    rep = B.collect(p, [STEP], max_bytes=3)
    assert rep["verdict"] == "INCOMPLETE", rep
    caps = [m for m in rep["missing"] if "over the" in m["why"]]
    assert caps, rep["missing"]
    assert all("bytes" in m for m in caps), caps


def test_the_environment_snapshot_records_absence_as_null_not_omission(tmp_path):
    """A reader must tell "we looked and there was none" from "no such field"."""
    env = B.environment(_project(tmp_path))
    for k in ("plugin_commit", "eda_image_anchor", "env_PDK_ROOT",
              "project_commit", "python", "platform"):
        assert k in env, (k, env)


# --------------------------------------------------------------------------- #
# PAIRED GUARD
# --------------------------------------------------------------------------- #
def test_a_bundle_that_resolved_NOTHING_is_not_COMPLETE(tmp_path):
    """The always-fires guard.

    A verdict function that returns COMPLETE unconditionally passes every
    positive test above. It dies here and only here: a project with none of the
    declared inputs must never come back COMPLETE, and must never come back
    with an empty `missing` list.
    """
    p = tmp_path / "bare"
    p.mkdir()
    rep = B.collect(p, [STEP])
    assert rep["verdict"] != "COMPLETE", rep
    assert rep["files"] == [], rep["files"]
    assert len(rep["missing"]) == 3, rep["missing"]


# --------------------------------------------------------------------------- #
# THE WIRED CONSUMER — a program with no caller is the #725 shape
# --------------------------------------------------------------------------- #
def test_the_preflight_refusal_path_emits_a_bundle(tmp_path, monkeypatch):
    import step_preflight as SP

    p = _project(tmp_path, spef=False, sdc=False, pvt=False)
    dec = SP.Decision(runner="r", site="s", flow_steps=[STEP],
                      project=str(p), at="now", verdict="BLOCKED",
                      allow=False, detail="d")
    got = SP._emit_repro_bundle(p, dec)
    assert got, "the refusal path produced no bundle"
    assert Path(got).is_file(), got
    with tarfile.open(got) as tf:
        doc = json.loads(tf.extractfile("MANIFEST.json").read().decode())
    # Absent BY CONSTRUCTION on this path — that IS the evidence.
    assert doc["verdict"] == "INCOMPLETE", doc
    assert len(doc["missing"]) == 3, doc["missing"]


def test_the_bundle_adds_NO_env_knob_to_the_refusal_path(tmp_path):
    """This started life as `test_the_bundle_can_be_switched_off`.

    `test_there_is_no_switch_that_turns_a_refusal_into_a_pass` caught the
    `VIBE_IC_REPRO_BUNDLE=0` opt-out and was RIGHT to: it bans every
    `os.environ.get` in `step_preflight` except `STRICT_ENV`, because "a
    weakening switch would make the refusal decorative". The knob did not
    weaken the refusal, but the ban is deliberately blanket so that nobody has
    to adjudicate per knob — so the knob went, not the ban.

    Asserted here as well as there, on the S7 side, so a future re-add of the
    switch fails in the PR that re-adds it and not only in the guard's file.
    """
    import re
    src = (_PROGRAMS / "step_preflight.py").read_text(encoding="utf-8")
    envs = set(re.findall(r"os\.environ\.get\(\s*([A-Za-z_]+|\"[^\"]+\")", src))
    assert envs <= {"STRICT_ENV"}, f"S7 re-introduced an env knob: {envs}"


def test_a_broken_bundler_NEVER_breaks_the_refusal(tmp_path, monkeypatch):
    """The load-bearing safety property: this runs on the refusal path, so a
    diagnostic that raises would cost the caller the finding it came to report.
    """
    import step_preflight as SP
    import step_repro_bundle as SRB

    def _boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(SRB, "write_bundle", _boom)
    dec = SP.Decision(runner="r", site="s", flow_steps=[STEP],
                      project=str(tmp_path), at="now", verdict="BLOCKED",
                      allow=False, detail="d")
    assert SP._emit_repro_bundle(tmp_path, dec) is None  # no raise
