"""Unit tests for `analog_hardmacro_gds_emit` — the A8 GDS producer.

The program shells out to Magic inside an EDA container. These tests do NOT
require one: `Stage.sh` / `Stage.put` / `Stage.get` are the seam, and a fake
stage stands in for the container so every branch of the rc contract is
exercised deterministically. The one thing a fake can never prove — that Magic
really turns a `.mag` into a GDS carrying geometry — is proved separately by
`test_matrix_d3_outputs_produced.py`'s reproducibility guard, which re-runs the
real producer whenever the container is reachable.

Every assertion below names the rc, because "a skip is not a success and not a
failure" is the whole contract:

    rc 0  produced, or skipped for a named disclosed reason
    rc 1  Magic ran and the result is not a layout
    rc 2  the capability is absent
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401  — puts programs/ on sys.path

import analog_hardmacro_gds_emit as A8G


# ── a GDSII stream with, and without, geometry ────────────────────────────
def _gds_record(rec_type: int, payload: bytes = b"") -> bytes:
    import struct
    return struct.pack(">HH", len(payload) + 4, rec_type) + payload


def _gds_with_geometry() -> bytes:
    """HEADER + UNITS + one BOUNDARY/XY pair + ENDLIB."""
    import struct
    out = b""
    out += _gds_record(0x0002, struct.pack(">h", 600))
    out += _gds_record(0x0800)                       # BOUNDARY
    out += _gds_record(0x1003, struct.pack(">8i", 0, 0, 0, 10, 10, 10, 10, 0))
    out += _gds_record(0x0400)                       # ENDLIB-ish filler
    return out


def _gds_without_geometry() -> bytes:
    import struct
    return _gds_record(0x0002, struct.pack(">h", 600)) + _gds_record(0x0400)


class FakeStage:
    """Stands in for the container. Records what was asked of it."""

    def __init__(self, *, magic=True, magicrc=True, gds: bytes = b"",
                 open_ok=True):
        self.path = "/stage"
        self._magic = magic
        self._magicrc = magicrc
        self._gds = gds
        self._open_ok = open_ok
        self.commands = []
        self.staged = []
        self.closed = False

    def open(self):
        return (True, "") if self._open_ok else (False, "no container here")

    def put(self, src, name):
        self.staged.append(name)
        return True, ""

    def put_text(self, text, name):
        self.staged.append(name)
        return True, ""

    def get(self, name, dst):
        if not self._gds:
            return False, "no such file"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self._gds)
        return True, ""

    def sh(self, cmd, timeout=900):
        self.commands.append(cmd)
        if "command -v magic" in cmd:
            return (0 if self._magic else 1), "", ""
        if cmd.startswith("test -e"):
            return (0 if self._magicrc else 1), "", ""
        return 0, "MAGIC_GDS_WRITE_DONE", ""

    def exists(self, path):
        return self.sh(f"test -e {path}")[0] == 0

    def close(self):
        self.closed = True


def _project(tmp_path: Path, *, mag_body: str | None = None,
             blocks=("blk_a",)) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog").mkdir(parents=True)
    (proj / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": b} for b in blocks]}))
    for b in blocks:
        d = proj / "phase3" / "analog" / b
        d.mkdir(parents=True, exist_ok=True)
        if mag_body is not None:
            (d / "layout.mag").write_text(mag_body)
    return proj


_REAL_MAG = "magic\ntech some_tech\ntimestamp 1\n<< metal1 >>\nrect 0 0 4 4\n<< end >>\n"


def _run(proj: Path, stage: FakeStage, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(A8G, "Stage", lambda *a, **k: stage)
    return A8G.run(proj, "fake-container", "/pdks", None, tmp_path / "hosttmp")


# ── the happy path ────────────────────────────────────────────────────────
def test_a_real_layout_is_streamed_and_lands_with_geometry(tmp_path,
                                                           monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)

    assert rc == 0, report
    assert report["verdict"] == "PASS"
    got = proj / "phase3/analog/hardmacro/blk_a/blk_a.gds"
    assert got.is_file() and got.stat().st_size > 0
    only = report["results"][0]
    assert only["rule"] == "A8GDS_PRODUCED"
    assert only["geometry_records"] >= 1
    # The technology came from the LAYOUT, never a default.
    assert only["tech"] == "some_tech"
    assert any("/pdks/some_tech/libs.tech/magic/some_tech.magicrc" in c
               for c in stage.commands), stage.commands
    assert stage.closed, "the staging dir must be removed even on success"


# ── rc 1: Magic ran and the result is not a layout ────────────────────────
def test_a_geometry_free_gds_is_rc1_and_the_hollow_file_is_removed(
        tmp_path, monkeypatch):
    """THE falsifier. A GDS with no BOUNDARY/PATH/SREF/AREF/BOX record is the
    exact artefact that used to buy `analog_hardmacro_check` a PASS (500 bytes
    of noise). The producer must never leave one on disk to be counted."""
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(gds=_gds_without_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)

    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    assert report["results"][0]["rule"] == "A8GDS_NO_GEOMETRY"
    assert not (proj / "phase3/analog/hardmacro/blk_a/blk_a.gds").exists(), (
        "a geometry-free GDS was left on disk where a presence check would "
        "read it as produced")


def test_magic_writing_nothing_is_rc1(tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(gds=b"")
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 1 and report["results"][0]["rule"] == "A8GDS_NOT_WRITTEN"


# ── rc 2: the capability is absent, disclosed by name ─────────────────────
def test_no_container_is_rc2_not_a_silent_pass(tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(open_ok=False)
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 2 and report["verdict"] == "UNAVAILABLE"
    assert report["results"][0]["rule"] == "A8GDS_NO_STAGE"


def test_no_magic_is_rc2_and_names_the_tool(tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(magic=False)
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 2 and report["results"][0]["rule"] == "A8GDS_NO_MAGIC"
    assert "magic" in report["reason"]


def test_a_tech_with_no_magicrc_is_unavailable_not_a_wrong_layer_gds(
        tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = FakeStage(magicrc=False, gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 2, report
    assert report["results"][0]["rule"] == "A8GDS_NO_TECH"
    assert not (proj / "phase3/analog/hardmacro/blk_a/blk_a.gds").exists()


# ── rc 0 skips, each one NAMED ────────────────────────────────────────────
def test_a_deterministic_stub_layout_is_skipped_so_the_stub_tier_survives(
        tmp_path, monkeypatch):
    """`analog_lef_gds_outline_check` credits a stub hardmacro with NO .gds as
    STUB_NOT_PACKAGED. Streaming stub padding would replace that disclosed skip
    with an outline mismatch, i.e. a new red on a legitimate state."""
    stub = ("# deterministic_stub extraction_strategy=deterministic_stub "
            "low_confidence=true\nmagic\ntech some_tech\n<< end >>\n")
    proj = _project(tmp_path, mag_body=stub)
    stage = FakeStage(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 0 and report["results"][0]["rule"] == "A8GDS_STUB_LAYOUT"
    assert not (proj / "phase3/analog/hardmacro/blk_a/blk_a.gds").exists()


def test_a_layout_with_no_tech_line_is_skipped_not_guessed(tmp_path,
                                                           monkeypatch):
    proj = _project(tmp_path, mag_body="magic\ntimestamp 1\n<< end >>\n")
    stage = FakeStage(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 0 and report["results"][0]["rule"] == "A8GDS_NO_TECH_LINE"


def test_no_layout_at_all_is_a_named_skip(tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=None)
    stage = FakeStage(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 0 and report["results"][0]["rule"] == "A8GDS_NO_LAYOUT"


def test_an_existing_gds_is_never_overwritten(tmp_path, monkeypatch):
    proj = _project(tmp_path, mag_body=_REAL_MAG)
    keep = proj / "phase3/analog/hardmacro/blk_a/blk_a.gds"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"signoff-artefact")
    stage = FakeStage(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 0 and report["results"][0]["rule"] == "A8GDS_ALREADY_PRESENT"
    assert keep.read_bytes() == b"signoff-artefact"


def test_a_project_with_no_analog_blocks_is_vacuous_pass(tmp_path,
                                                         monkeypatch):
    proj = tmp_path / "digital"
    proj.mkdir()
    report, rc = A8G.run(proj, "fake", "/pdks", None, tmp_path / "t")
    assert rc == 0 and report["verdict"] == "VACUOUS_PASS"


# ── the flow declaration and the program must not drift apart ─────────────
def test_the_flow_declares_this_producer_at_a8_and_keeps_it_out_of_the_gate():
    """A8's `.gds` was declared and produced by nothing. Two halves, opposite
    directions, and BOTH have to hold:

    * the step must still declare the producer and still declare the `.gds`;
    * the producer must NOT appear in A8's gate. `flow_compliance_check` reads
      that gate, and it is the acceptance auditor — a clause there writes a
      declared `required_output` into the very tree the audit is judging, so
      `analog_hardmacro_check` and `analog_lef_gds_outline_check` end up
      reading a file the audit itself created moments earlier. Measured
      2026-07-28: with the clause present, auditing a copy of the analog
      reference run manufactured delta_sigma.gds (2042 B) and ldo.gds (1706 B);
      without it, zero files.
    """
    from matrix import flowref as F

    outs = list(F.required_outputs("A8"))
    assert any(o.endswith("*.gds") for o in outs), outs
    assert "analog_hardmacro_gds_emit" in F.declared_programs("A8")
    cmds = [c.command for c in F.gate_clauses("A8") if c.command]
    assert not any(c.split()[0] == "analog_hardmacro_gds_emit" for c in cmds), (
        f"the producer is back in A8's gate: {cmds}. Production belongs to "
        f"analog_one_shot_runner; an auditor must not create the artefact it "
        f"then certifies.")


def test_the_analog_runner_invokes_this_producer_at_a8_and_only_there(
        tmp_path, monkeypatch):
    """The runner half, measured by DISPATCH — not by grepping the source.

    2026-07-28, adversarial finding (LOW), accepted: with the producer wired
    into both A8's gate and `analog_one_shot_runner`, only the gate half was
    guarded. Replacing `if step_name == "A8_hardmacro_gen":` with `if False:`
    left 95 tests passing. The gate half has since been withdrawn on purpose,
    so this IS the wiring now and an unguarded one would be no wiring at all.

    A recording stand-in replaces the runner's `subprocess` module, so what is
    asserted is the argv the runner actually dispatches.
    """
    import subprocess as _sp

    import analog_one_shot_runner as AOSR

    class _Recorder:
        def __init__(self):
            self.calls = []

        def run(self, argv, **kw):
            self.calls.append([str(a) for a in argv])
            return _sp.CompletedProcess(argv, 0, "VACUOUS_PASS: stubbed", "")

        def __getattr__(self, name):        # everything else stays real
            return getattr(_sp, name)

    rec = _Recorder()
    monkeypatch.setattr(AOSR, "subprocess", rec)

    proj = tmp_path / "proj"
    proj.mkdir()

    def dispatched(step_name):
        rec.calls.clear()
        AOSR.step_for_block(proj, {"name": "blk_a"}, step_name, None)
        return [c for c in rec.calls
                if Path(c[1]).name == "analog_hardmacro_gds_emit.py"]

    at_a8 = dispatched("A8_hardmacro_gen")
    assert len(at_a8) == 1, (
        f"analog_one_shot_runner dispatched the A8 GDS producer {len(at_a8)} "
        f"times at A8_hardmacro_gen; the .gds is declared by the step and "
        f"written by nothing else in a real analog run. All dispatches: "
        f"{rec.calls}")
    argv = at_a8[0]
    assert str(proj) in argv, argv
    assert "--block" in argv and "blk_a" in argv, argv

    for other in ("A5_layout", "A7_post_layout_resim", "A9_hw_verify"):
        assert not dispatched(other), (
            f"the A8 GDS producer ran at {other}; it streams A8's hardmacro "
            f"artefact and must not fire on another step")


def test_the_gds_write_tcl_is_the_flows_own_emitter_not_a_local_copy(
        tmp_path, monkeypatch):
    """The staged TCL must be byte-identical to what the shared emitter returns.

    `magic_port_extract_emit.build_gds_write_tcl` shipped in v0.1.114 with a
    unit test and NO caller; a second, local copy of the same three lines is
    exactly how the two drift apart, so this compares the bytes that actually
    reached the stage rather than grepping the source."""
    from magic_port_extract_emit import build_gds_write_tcl

    class Recording(FakeStage):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.texts = {}

        def put_text(self, text, name):
            self.texts[name] = text
            return super().put_text(text, name)

    proj = _project(tmp_path, mag_body=_REAL_MAG)
    stage = Recording(gds=_gds_with_geometry())
    report, rc = _run(proj, stage, monkeypatch, tmp_path)
    assert rc == 0, report
    assert stage.texts["blk_a_gds_write.tcl"] == build_gds_write_tcl(
        top_cell="blk_a", layout_mag="blk_a", out_gds="blk_a.gds")
