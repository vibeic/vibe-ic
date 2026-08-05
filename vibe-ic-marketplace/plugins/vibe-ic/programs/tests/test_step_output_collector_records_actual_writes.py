#!/usr/bin/env python3
"""BIDIRECTIONAL CONTROL at the artefact the owner asked for: the per-step
output folder.

    "we define each step's input and output. why we didnt check each step's
     output? let the output folder"                        — owner, 2026-07-27

This module imports ONLY `step_output_collector`, which exists on both sides of
the change, so it is a control on BEHAVIOUR — not on whether a new file was
added. Run it against a byte-identical pre-change checkout and it fails on a
missing/contradicting EVIDENCE ARTEFACT, with a real assertion, not an
ImportError.

PRE-CHANGE (measured, HEAD 1ea6689b, on a copy of a real run directory with the
step-37 GDS truncated to 0 bytes):

    steps/phase3/stage4/37_gdsii_output_.../spm.gds       symlink -> the 0-byte file
    steps/phase3/stage4/37_gdsii_output_.../outputs.json  {"rel": ".../spm.gds",
                                                           "size": 0}
    reports/write_ledger.json                             ABSENT
    steps/.../written.json                                ABSENT

Every entry in that folder is derived from `required_outputs`; nothing in it
records what the run actually WROTE, so a 0-byte GDS reads as step 37's
produced output.

MEASURED, both directions, same test file:

  pre-change tree (git archive HEAD; collector sha256 58c84bfe1a7b…, verified
  identical to `git show HEAD:…`):        4 failed, 2 passed
  post-change tree:                       6 passed

  FORWARD  (FAIL pre-change -> PASS post-change)
    test_collector_emits_an_observation_of_what_was_written
        AssertionError: the per-step output view must be accompanied by a
        record of what the run ACTUALLY WROTE
    test_zero_byte_declared_output_is_not_counted_as_produced
        AssertionError: no observation artefact exists pre-change
    test_real_output_still_reads_as_produced
        FileNotFoundError: …/37_gdsii_…/written.json
    test_materialize_survives_a_ledger_that_cannot_be_written
        ModuleNotFoundError: No module named 'step_write_ledger'

  REVERSE  (PASS pre-change AND PASS post-change — the change must not have
            been bought by breaking or weakening what already worked)
    test_collector_still_builds_the_nested_symlink_tree
    test_materialize_still_returns_its_original_keys

  test_real_output_still_reads_as_produced doubles as the anti-"flag
  everything" guard: the new artefact must say PRODUCED for a genuine
  non-empty file and raise no D3 for it.
  test_zero_byte_declared_output_is_not_counted_as_produced additionally
  asserts that outputs.json STILL mirrors the 0-byte file in — so the control
  cannot pass by having weakened the collector.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import step_output_collector as soc          # noqa: E402  (exists both sides)


GDS_REL = "phase3/stage4/gds/chip.gds"       # matches step 37's required_outputs
GDS_STEP = "37"


def _mk_project(tmp_path: Path, *, zero_byte: bool) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "orchestrator").mkdir(parents=True)
    (p / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (p / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"duration_s": 3600.0, "verdict": "PASS"}))
    (p / GDS_REL).write_bytes(b"" if zero_byte else b"\x00\x01GDSII" * 400)
    (p / "phase3" / "stage3" / "pnr" / "routed.def").write_bytes(b"DESIGN c ;\n" * 40)
    return p


def _step_dir(p: Path, step_id: str) -> Path | None:
    idx_f = p / "steps" / "index.json"
    if not idx_f.is_file():
        return None
    for s in json.loads(idx_f.read_text()).get("steps", []):
        if str(s.get("id")) == step_id:
            return p / "steps" / str(s.get("folder"))
    return None


# --------------------------------------------------------------------------- #
# FORWARD — fails against the byte-identical pre-change collector
# --------------------------------------------------------------------------- #
def test_collector_emits_an_observation_of_what_was_written(tmp_path):
    p = _mk_project(tmp_path, zero_byte=False)
    soc.materialize(p)

    ledger = p / "reports" / "write_ledger.json"
    assert ledger.is_file(), (
        "the per-step output view must be accompanied by a record of what the "
        "run ACTUALLY WROTE; pre-change the whole tree is derived from "
        "required_outputs and witnesses nothing")

    led = json.loads(ledger.read_text())
    # It must be an OBSERVATION: sizes and mtimes read off the filesystem.
    assert led["capture"]["method"].startswith("post-hoc os.walk")
    assert led["capture"]["entries_walked"] > 0
    assert any(e["rel"] == GDS_REL and e["mtime"] > 0 and e["size"] > 0
               for e in led["written"])

    sdir = _step_dir(p, GDS_STEP)
    assert sdir is not None and (sdir / "written.json").is_file(), (
        "each step folder must carry an observation artefact next to its "
        "declaration artefact (outputs.json)")


def test_zero_byte_declared_output_is_not_counted_as_produced(tmp_path):
    """THE distinction. Pre-change, outputs.json lists the 0-byte GDS and the
    symlink to it is materialized — it reads as step 37's produced artefact."""
    p = _mk_project(tmp_path, zero_byte=True)
    soc.materialize(p)

    sdir = _step_dir(p, GDS_STEP)
    assert sdir is not None

    # The pre-change artefact, kept here so the contradiction is visible and
    # so this control also documents that the declaration half is unchanged.
    outputs = json.loads((sdir / "outputs.json").read_text())["outputs"]
    assert any(o["rel"] == GDS_REL and o["size"] == 0 for o in outputs), (
        "declaration half unchanged: outputs.json still mirrors the 0-byte "
        "file in — this control must not be passing because the collector "
        "was weakened")

    written_f = sdir / "written.json"
    assert written_f.is_file(), "no observation artefact exists pre-change"
    written = json.loads(written_f.read_text())

    assert written["n_produced"] == 0, (
        "a 0-byte declared output must never be recorded as produced")
    d3 = [f for f in written["findings"] if f["dimension"] == "D3"]
    assert d3, "declared-but-not-written must raise D3 ATTRIBUTED TO THIS STEP"
    assert d3[0]["step"] == GDS_STEP
    assert d3[0]["reason"] == "zero_byte"


# --------------------------------------------------------------------------- #
# REVERSE — must STILL pass; the change must not just fail everything
# --------------------------------------------------------------------------- #
def test_real_output_still_reads_as_produced(tmp_path):
    p = _mk_project(tmp_path, zero_byte=False)
    soc.materialize(p)
    sdir = _step_dir(p, GDS_STEP)
    written = json.loads((sdir / "written.json").read_text())
    assert written["n_produced"] >= 1
    assert not [f for f in written["findings"] if f["dimension"] == "D3"]
    assert any(x["rel"] == GDS_REL and x["size"] > 0 for x in written["produced"])


def test_collector_still_builds_the_nested_symlink_tree(tmp_path):
    """The owner's tree (nested phase/stage/step, symlinks only) is untouched."""
    p = _mk_project(tmp_path, zero_byte=False)
    soc.materialize(p)
    sdir = _step_dir(p, GDS_STEP)
    assert sdir is not None
    assert len(sdir.relative_to(p / "steps").parts) == 3, "phase/stage/step"
    link = sdir / "chip.gds"
    assert link.is_symlink() and link.resolve() == (p / GDS_REL).resolve()
    assert (sdir / "outputs.json").is_file()
    assert (p / "steps" / "index.json").is_file()


def test_materialize_still_returns_its_original_keys(tmp_path):
    p = _mk_project(tmp_path, zero_byte=False)
    res = soc.materialize(p)
    for k in ("steps_root", "n_steps", "n_with_outputs"):
        assert k in res, f"existing caller contract lost key {k!r}"
    assert res["n_steps"] > 0


def test_materialize_survives_a_ledger_that_cannot_be_written(tmp_path, monkeypatch):
    """A run must not die because its bookkeeping failed."""
    p = _mk_project(tmp_path, zero_byte=False)
    import step_write_ledger as swl

    def boom(_project):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(swl, "emit", boom)

    res = soc.materialize(p)                      # must NOT raise
    assert res["n_steps"] > 0
    assert res["write_ledger"]["ok"] is False
    assert "disk on fire" in res["write_ledger"]["error"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
