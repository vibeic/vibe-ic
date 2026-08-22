#!/usr/bin/env python3
"""Bidirectional control for step_write_ledger.

THE DEFECT BEING CONTROLLED
---------------------------
`step_output_collector.materialize()` derives every entry in `<project>/steps/`
from `required_outputs`, filtering only on `exists`. MEASURED on a real run
directory (a copy of $HOME/_sky130A_r3_run) with the step-37 GDS
truncated to 0 bytes, the pre-change collector produced:

    steps/phase3/stage4/37_gdsii_output_.../spm.gds        -> symlink, present
    steps/phase3/stage4/37_gdsii_output_.../outputs.json   -> {"size": 0}

i.e. a 0-byte GDS mirrored in and presented as step 37's produced output. The
per-step folder therefore cannot witness anything the declaration does not
already claim.

FORWARD CASE  (must FAIL against the byte-identical pre-change tree, PASS now)
    test_zero_byte_declared_output_is_not_produced
    test_dangling_symlink_declared_output_is_not_produced
        Pre-change there is no `written.json` and no `reports/write_ledger.json`
        at all, so both assertions fail on a missing artefact; and the ONE
        artefact that does exist (outputs.json) makes the opposite claim.

REVERSE CASE  (must STILL pass — the change must not just fail everything)
    test_real_output_is_recorded_as_produced
    test_untouched_project_reports_no_zero_byte_or_dangling
        A genuine non-empty file declared by a step is recorded produced=True
        with its real size, and raises NO D3 for that spec.

NEVER-FAILS-A-RUN CASE
    test_emit_never_raises_on_hostile_project
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import step_write_ledger as swl            # noqa: E402


# --------------------------------------------------------------------------- #
# Fixture: a minimal but REAL-SHAPED project. Paths and step ids are taken from
# the actual flow YAML so the residual runs against the real declaration, not a
# stub of it.
# --------------------------------------------------------------------------- #
GDS_SPEC_STEP = "37"                      # required_outputs: phase3/stage4/gds/*.gds
GDS_REL = "phase3/stage4/gds/chip.gds"
DEF_SPEC_STEP = "21"                      # required_outputs: phase3/stage3/pnr/routed.def
DEF_REL = "phase3/stage3/pnr/routed.def"


def _mk_project(tmp_path: Path, *, gds: str, routed: str) -> Path:
    """gds/routed: "real" | "zero" | "dangling" | "absent"."""
    p = tmp_path / "proj"
    (p / "reports" / "orchestrator").mkdir(parents=True)
    (p / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)

    # A run window t0 must exist or the D7 direction self-reports UNDETERMINED.
    (p / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"duration_s": 3600.0, "verdict": "PASS"}))

    def place(rel: str, mode: str, payload: bytes) -> None:
        f = p / rel
        if mode == "absent":
            return
        if mode == "real":
            f.write_bytes(payload)
        elif mode == "zero":
            f.write_bytes(b"")
        elif mode == "dangling":
            os.symlink(str(p / "nowhere" / "gone.bin"), str(f))

    place(GDS_REL, gds, b"\x00\x01GDSII" * 400)
    place(DEF_REL, routed, b"VERSION 5.8 ;\nDESIGN chip ;\nEND DESIGN\n" * 40)
    return p


def _findings(led: dict, step: str, needle: str) -> list:
    return [f for f in led["residual"]["declared_never_written"]
            if f["step"] == step and needle in f["spec"]]


def _entry(led: dict, rel: str) -> dict | None:
    for e in led["written"]:
        if e["rel"] == rel:
            return e
    return None


# --------------------------------------------------------------------------- #
# FORWARD — these fail on the pre-change tree (no ledger exists at all)
# --------------------------------------------------------------------------- #
def test_zero_byte_declared_output_is_not_produced(tmp_path):
    p = _mk_project(tmp_path, gds="zero", routed="real")
    led = swl.build(p)

    e = _entry(led, GDS_REL)
    assert e is not None, "a 0-byte declared output must still be RECORDED"
    assert e["kind"] == "empty_file"
    assert e["produced"] is False, "0 bytes is never a produced artefact"
    assert e["not_produced_reason"] == "zero_byte"

    d3 = _findings(led, GDS_SPEC_STEP, "gds")
    assert d3, "a 0-byte declared output must raise D3 against ITS OWN STEP"
    assert d3[0]["reason"] == "zero_byte"
    assert d3[0]["dimension"] == "D3"
    assert d3[0]["step"] == GDS_SPEC_STEP


def test_dangling_symlink_declared_output_is_not_produced(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="dangling")
    led = swl.build(p)

    e = _entry(led, DEF_REL)
    assert e is not None, (
        "a dangling symlink must be RECORDED, not silently dropped by a "
        "resolver that follows links")
    assert e["kind"] == "dangling_symlink"
    assert e["produced"] is False
    assert "nowhere/gone.bin" in (e.get("link_target") or "")

    d3 = _findings(led, DEF_SPEC_STEP, "routed.def")
    assert d3, "a dangling declared output must raise D3 against its own step"
    assert d3[0]["reason"] == "dangling_symlink"


def test_per_step_written_json_is_emitted_and_disagrees_with_outputs_json(tmp_path):
    """The load-bearing integration: the per-step folder must carry an
    OBSERVATION artefact next to the declaration artefact, and on a 0-byte
    output the two must DISAGREE."""
    p = _mk_project(tmp_path, gds="zero", routed="real")
    steps_dir = p / "steps" / "phase3" / "stage4" / f"{GDS_SPEC_STEP}_gdsii"
    steps_dir.mkdir(parents=True)
    (p / "steps" / "index.json").write_text(json.dumps({"steps": [
        {"id": GDS_SPEC_STEP, "folder": f"phase3/stage4/{GDS_SPEC_STEP}_gdsii"}]}))
    # What the DECLARATION-derived collector would say (size 0, still listed):
    (steps_dir / "outputs.json").write_text(json.dumps(
        {"id": GDS_SPEC_STEP, "outputs": [{"rel": GDS_REL, "size": 0}]}))

    res = swl.emit(p)
    assert res["ok"] is True
    assert (p / "reports" / "write_ledger.json").is_file()

    written = json.loads((steps_dir / "written.json").read_text())
    assert written["id"] == GDS_SPEC_STEP
    assert written["n_produced"] == 0, (
        "the observation half must not count a 0-byte file as produced, even "
        "though outputs.json lists it")
    assert any(f["dimension"] == "D3" for f in written["findings"])


# --------------------------------------------------------------------------- #
# REVERSE — must STILL pass
# --------------------------------------------------------------------------- #
def test_real_output_is_recorded_as_produced(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="real")
    led = swl.build(p)

    e = _entry(led, GDS_REL)
    assert e is not None and e["produced"] is True
    assert e["kind"] == "file"
    assert e["size"] == len(b"\x00\x01GDSII" * 400)

    assert not _findings(led, GDS_SPEC_STEP, "phase3/stage4/gds/*.gds"), \
        "a real non-empty declared output must raise NO D3"
    assert not _findings(led, DEF_SPEC_STEP, "routed.def")

    row = [r for r in led["steps"] if r["id"] == GDS_SPEC_STEP]
    assert row and row[0]["n_produced"] >= 1


def test_untouched_project_reports_no_zero_byte_or_dangling(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="real")
    led = swl.build(p)
    assert led["counts"]["zero_byte"] == 0
    assert led["counts"]["dangling_symlink"] == 0
    assert led["counts"]["produced_in_run_window"] >= 2


def test_absent_declared_output_is_absent_not_zero_byte(tmp_path):
    """The three must never be conflated: absent != 0-byte != dangling."""
    p = _mk_project(tmp_path, gds="absent", routed="real")
    led = swl.build(p)
    d3 = _findings(led, GDS_SPEC_STEP, "gds")
    assert d3 and d3[0]["reason"] == "absent"


# --------------------------------------------------------------------------- #
# Structural guarantees
# --------------------------------------------------------------------------- #
def test_undetermined_is_declared_not_guessed(tmp_path):
    """No orchestrator summary -> no run window -> D7 is UNDETERMINED, and the
    ledger says so instead of reporting a number it cannot support."""
    p = tmp_path / "bare"
    (p / "phase3").mkdir(parents=True)
    (p / "phase3" / "x.txt").write_text("hi")
    led = swl.build(p)
    assert led["run_window"]["known"] is False
    assert led["totals"]["D7"] == 0
    assert any("run window unknown" in u for u in led["undetermined"])
    assert any("provenance.jsonl absent" in u for u in led["undetermined"])


def test_emit_never_raises_on_hostile_project(tmp_path):
    """Bookkeeping must never kill a run."""
    assert swl.emit(tmp_path / "does" / "not" / "exist")["ok"] in (True, False)

    p = tmp_path / "hostile"
    p.mkdir()
    (p / "provenance.jsonl").write_text("{not json\n\x00\xff\n[]\n")
    (p / "reports").mkdir()
    (p / "reports" / "orchestrator").mkdir()
    (p / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text("<<<")
    (p / "loop").symlink_to(p)                       # symlink cycle
    res = swl.emit(p)
    assert isinstance(res, dict) and "ok" in res


def test_ledger_does_not_walk_the_declaration_view(tmp_path):
    """steps/ is the collector's declaration-derived view. Walking it would let
    the declaration re-enter the observation — the exact circularity this
    module exists to break."""
    p = _mk_project(tmp_path, gds="real", routed="real")
    (p / "steps" / "phase3" / "stage4" / "37_x").mkdir(parents=True)
    (p / "steps" / "phase3" / "stage4" / "37_x" / "chip.gds").symlink_to(p / GDS_REL)
    led = swl.build(p)
    assert not any(e["rel"].startswith("steps/") for e in led["written"])
    assert "steps" in led["capture"]["skipped_dirs"]


def test_symlink_alias_is_not_a_write(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="real")
    alias = p / "phase3" / "stage4" / "gds" / "alias.gds"
    alias.symlink_to(p / GDS_REL)
    led = swl.build(p)
    e = _entry(led, "phase3/stage4/gds/alias.gds")
    assert e is not None and e["kind"] == "symlink"
    assert e["produced"] is False and e["not_produced_reason"] == "symlink_alias"


def test_producer_is_unattributable_without_provenance(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="real")
    led = swl.build(p)
    e = _entry(led, GDS_REL)
    assert e["producer"] is None
    assert e["producer_confidence"] == "unattributable", (
        "no provenance.jsonl must read as 'cannot attribute', NEVER as "
        "'unwitnessed' — absence of a log is not evidence of a bad write")


def test_producer_window_attribution(tmp_path):
    """A write whose mtime lands in exactly one logged invocation window is
    attributed to that tool; one that lands in none is 'unwitnessed'."""
    import datetime as dt
    p = _mk_project(tmp_path, gds="real", routed="real")
    mt = (p / GDS_REL).stat().st_mtime
    ts = dt.datetime.fromtimestamp(mt, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (p / "provenance.jsonl").write_text(json.dumps({
        "record": "invocation", "tool": "klayout", "timestamp": ts,
        "duration_s": 1.0, "command": "klayout -b -r gds.rb", "exit_code": 0,
    }) + "\n")
    led = swl.build(p)
    e = _entry(led, GDS_REL)
    assert e["producer"] == "klayout"
    assert e["producer_confidence"] == "window"

    # A file written INSIDE the run window (t0 = summary mtime - 3600 s) but
    # outside every invocation window is unwitnessed, not attributed.
    stale = p / "phase3" / "stage4" / "gds" / "hand_written.gds"
    stale.write_bytes(b"x" * 10)
    os.utime(stale, (mt - 600, mt - 600))
    led2 = swl.build(p)
    e2 = _entry(led2, "phase3/stage4/gds/hand_written.gds")
    assert e2 is not None and e2["in_run_window"] is True
    assert e2["producer_confidence"] == "unwitnessed"

    # And a file written BEFORE t0 is not this run's write at all — it must not
    # be reported as an unwitnessed write of this run.
    old = p / "phase3" / "stage4" / "gds" / "preexisting.gds"
    old.write_bytes(b"y" * 10)
    os.utime(old, (mt - 99999, mt - 99999))
    led3 = swl.build(p)
    assert _entry(led3, "phase3/stage4/gds/preexisting.gds") is None


def test_provenance_contradiction_needs_no_hashing(tmp_path):
    """A provenance record naming a real digest for a path that is now 0 bytes
    is self-contradictory, and the contradiction is decidable from lstat."""
    p = _mk_project(tmp_path, gds="zero", routed="real")
    (p / "provenance.jsonl").write_text(json.dumps({
        "tool": "klayout", "timestamp": "2026-01-01T00:00:00Z", "duration_s": 1.0,
        "outputs": {GDS_REL: "sha256:" + "ab" * 32}, "exit_code": 0,
    }) + "\n")
    led = swl.build(p)
    e = _entry(led, GDS_REL)
    assert "provenance_contradiction" in e
    assert led["totals"]["provenance_contradictions"] >= 1
    d3 = _findings(led, GDS_SPEC_STEP, "gds")
    assert d3 and "provenance_contradiction" in d3[0]


def test_flattened_mtimes_withhold_every_time_derived_conclusion(tmp_path):
    """A git checkout / bulk copy stamps every file with one mtime. MEASURED:
    the published cell benchmark-data/ic/spm/v1.5.66_gf180mcuD has 98.2% of its
    216 files on a single mtime second. Time-derived conclusions must be
    WITHHELD there, not computed off a checkout timestamp."""
    p = _mk_project(tmp_path, gds="real", routed="real")
    d = p / "phase3" / "stage4" / "gds"
    for i in range(40):
        (d / f"f{i}.bin").write_bytes(b"x" * (i + 1))
    stamp = 1_700_000_000
    for f in p.rglob("*"):
        if f.is_file():
            os.utime(f, (stamp, stamp))
    led = swl.build(p)

    assert led["mtime_fidelity"]["flattened"] is True
    assert led["mtime_fidelity"]["top_mtime_share"] >= 0.5
    assert led["run_window"]["known"] is False
    assert led["run_window"]["t0_source"] == "withheld_flattened_mtimes"
    assert led["totals"]["D7"] == 0, "D7 must not be computed off a copy time"
    assert any("FLATTENED" in u for u in led["undetermined"])

    # What SURVIVES a flattened tree: existence, size, kind, and the D3
    # residual. Those never depended on mtime.
    assert led["counts"]["produced_in_run_window"] == 0
    assert any(e["rel"] == GDS_REL and e["size"] > 0 for e in led["written"])


def test_live_run_mtimes_are_not_called_flattened(tmp_path):
    """REVERSE of the above: a tree whose writes are spread over time must NOT
    be dismissed. MEASURED separation on real dirs — live runs sit at
    0.122-0.165 top-share, copies at 0.884-0.981."""
    p = _mk_project(tmp_path, gds="real", routed="real")
    d = p / "phase3" / "stage4" / "gds"
    base = (p / GDS_REL).stat().st_mtime
    for i in range(40):
        f = d / f"f{i}.bin"
        f.write_bytes(b"x" * (i + 1))
        os.utime(f, (base - i * 7, base - i * 7))
    led = swl.build(p)
    assert led["mtime_fidelity"]["flattened"] is False
    assert led["run_window"]["known"] is True
    assert led["totals"]["D7"] >= 1


def test_path_named_provenance_survives_flattened_mtimes(tmp_path):
    """A provenance record that names a path does not depend on mtime, so it
    must keep working when window attribution is withheld."""
    p = _mk_project(tmp_path, gds="real", routed="real")
    (p / "provenance.jsonl").write_text(json.dumps({
        "tool": "klayout", "timestamp": "2026-01-01T00:00:00Z", "duration_s": 1.0,
        "outputs": {GDS_REL: "sha256:" + "cd" * 32}, "exit_code": 0,
    }) + "\n")
    for i in range(40):            # flattening is only decided at n >= 20
        (p / "phase3" / "stage4" / "gds" / f"f{i}.bin").write_bytes(b"x" * (i + 1))
    stamp = 1_700_000_000
    for f in p.rglob("*"):
        if f.is_file():
            os.utime(f, (stamp, stamp))
    led = swl.build(p)
    assert led["mtime_fidelity"]["flattened"] is True
    e = _entry(led, GDS_REL)
    assert e["producer"] == "klayout"
    assert e["producer_confidence"] == "provenance_output"


def test_d7_written_never_declared(tmp_path):
    p = _mk_project(tmp_path, gds="real", routed="real")
    (p / "phase3" / "stage4" / "gds" / "undeclared_artifact.bin").write_bytes(b"z" * 32)
    led = swl.build(p)
    d7 = [f for f in led["residual"]["written_never_declared"]
          if f["rel"].endswith("undeclared_artifact.bin")]
    assert d7, "a real write matching no required_outputs spec is a D7 candidate"
    assert d7[0]["dimension"] == "D7" and d7[0]["kind"] == "candidate"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
