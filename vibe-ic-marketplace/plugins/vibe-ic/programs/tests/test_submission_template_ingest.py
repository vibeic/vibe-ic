#!/usr/bin/env python3
"""Step 0.5ic, the ingest half — the geometry is DATA, and absence has a shape.

WHAT THIS FILE PINS
-------------------
I1  a slot is recorded with its name, die rect, core rect, sizing mode and pad
    list, VERBATIM, each carrying the file it came from and that file's digest.
I2  nothing is rounded. A fractional dimension survives the record exactly, and
    the derived width/height never round-trip through a JSON float.
I3  the declared slot is the design's DECLARATION and is never invented — not
    even when the template ships exactly one slot and guessing would be right.
I4  a template that is ABSENT and a template that was NEVER LOOKED FOR are
    different records. This is the distinction the step exists for.
I5  the report is emitted on EVERY path, including both absent ones.
I6  the program never fetches. It takes a path.
I7  nothing is vendored: the operator's bytes stay where they are.
I8  a fixture whose cells could not be read records `null` and a reason — never
    an empty list. An unread file and a file with no cells are different facts.
I9  the scan is honest about what it could not parse, and about its own bounds.

EACH REFUSAL THIS FILE'S SIBLING PROVES IS PROVEN BY MUTATION; here the subject
is the RECORD, so the discriminating question is the opposite one: does the
record still say enough to be judged? A record that quietly loses the searched
path, or the file digest, or the difference between two kinds of absence, is a
record whose gate cannot fail — and `test_submission_template_check.py` breaks
each of those in turn to show that it does.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _submission_template as ST      # noqa: E402
import submission_template_ingest as ING  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures — a generic operator template. No vendor, SKU or node appears here.
# --------------------------------------------------------------------------- #
SLOT_A = """\
DIE_AREA: [0, 0, 1000, 2000]
CORE_AREA: [26, 26, 974, 1974]
SEAL_RING_WIDTH: 26
FP_SIZING: absolute
pads: [pad_n0, pad_n1, pad_s0]
"""

SLOT_B = """\
DIE_AREA: [0, 0, 4000, 5000]
CORE_AREA: [26, 26, 3974, 4974]
SEAL_RING_WIDTH: 26
FP_SIZING: absolute
pads: [pad_n0, pad_n1, pad_s0, pad_s1]
"""


def _gds(path: Path, cells) -> None:
    """A minimal GDS stream carrying `cells` as STRNAME records."""
    import struct

    def rec(rt, dt, payload=b""):
        return struct.pack(">HBB", 4 + len(payload), rt, dt) + payload

    out = rec(0x00, 0x02, b"\x00\x05") + rec(0x01, 0x02, b"\x00\x05" * 2)
    for name in cells:
        raw = name.encode("ascii")
        if len(raw) % 2:
            raw += b"\x00"
        out += rec(0x05, 0x02, b"\x00" * 24) + rec(0x06, 0x06, raw) + rec(0x07, 0x00)
    out += rec(0x04, 0x00)
    path.write_bytes(out)


@pytest.fixture()
def template(tmp_path: Path) -> Path:
    root = tmp_path / "operator_template"
    (root / "slots").mkdir(parents=True)
    (root / "slots" / "slot_a.yaml").write_text(SLOT_A)
    (root / "slots" / "slot_b.yaml").write_text(SLOT_B)
    (root / "fixtures").mkdir()
    _gds(root / "fixtures" / "die_id.gds", ["die_id_alpha", "die_id_beta"])
    return root


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    p = tmp_path / "design"
    p.mkdir()
    return p


def _run(project: Path, *argv) -> dict:
    rc = ING.main([str(project), *argv])
    assert rc == 0, f"the ingester must record on every path; rc={rc}"
    doc = json.loads((project / ST.REPORT_REL).read_text())
    assert doc["schema"] == ST.SCHEMA
    return doc["ingest"]


# --------------------------------------------------------------------------- #
# I1 / I2 — the geometry is DATA
# --------------------------------------------------------------------------- #
def test_a_slot_is_recorded_verbatim_with_the_file_it_came_from(template, project):
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    assert rec["status"] == ST.STATUS_INGESTED
    assert rec["slots_shipped"] == ["slot_a", "slot_b"]

    a = next(s for s in rec["slots"] if s["slot"] == "slot_a")
    # verbatim, exactly as the operator wrote it
    assert a["die_area"]["raw"] == [0, 0, 1000, 2000]
    assert a["core_area"]["raw"] == [26, 26, 974, 1974]
    assert a["fp_sizing"] == {"key": "FP_SIZING", "raw": "absolute"}
    assert a["pads"]["keys_matched"] == ["pads"]
    assert a["pads"]["lists"][0]["raw"] == ["pad_n0", "pad_n1", "pad_s0"]
    assert a["pads"]["count"] == 3
    assert a["pads"]["unmatched_list_keys"] == []
    assert a["ring"]["key"] == "SEAL_RING_WIDTH"
    # and traceable to the file it was read out of
    assert a["source_file"] == str(template / "slots" / "slot_a.yaml")
    assert a["source_relpath"] == "slots/slot_a.yaml"
    assert len(a["source_sha256"]) == 64

    # the declared output exists, one file per slot
    on_disk = sorted((project / ST.SLOTS_DIR_REL).glob("*.yaml"))
    assert [p.name for p in on_disk] == ["slot_a.yaml", "slot_b.yaml"]


def test_a_fractional_dimension_is_not_rounded(template, project):
    (template / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000.125, 2000.5]\n"
        "CORE_AREA: [0.5, 0.5, 999.625, 2000.0]\n"
        "FP_SIZING: absolute\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    a = next(s for s in rec["slots"] if s["slot"] == "slot_a")
    assert a["die_area"]["raw"] == [0, 0, 1000.125, 2000.5]
    # derived numbers are STRINGS on purpose: a dimension that round-trips
    # through a JSON float is a dimension that has been rounded.
    assert a["die_area"]["width"] == "1000.125"
    assert a["die_area"]["height"] == "2000.5"
    assert a["core_area"]["width"] == "999.125"
    raw = (project / ST.SLOTS_DIR_REL / "slot_a.yaml").read_text()
    assert "1000.125" in raw and "1000.13" not in raw


def test_the_declared_slot_carries_its_provenance(template, project):
    rec = _run(project, "--template", str(template), "--slot", "slot_b")
    assert rec["declared_slot"] == "slot_b"
    assert rec["declared_slot_source"] == "--slot"


# --------------------------------------------------------------------------- #
# I3 — never guessed, not even when guessing would be right
# --------------------------------------------------------------------------- #
def test_a_single_slot_template_is_still_not_defaulted(template, project):
    (template / "slots" / "slot_b.yaml").unlink()
    rec = _run(project, "--template", str(template))
    assert rec["slots_shipped"] == ["slot_a"], "the template ships exactly one"
    assert rec["declared_slot"] is None, (
        "a die that was chosen and a die that was defaulted are the same "
        "number with different provenance; this program must never supply the "
        "second")
    assert rec["declared_slot_source"] is None


# --------------------------------------------------------------------------- #
# I4 / I5 — the two kinds of absence, and the report on every path
# --------------------------------------------------------------------------- #
def test_absent_and_never_looked_for_are_different_records(tmp_path):
    absent = tmp_path / "d_absent"
    never = tmp_path / "d_never"
    absent.mkdir()
    never.mkdir()

    a = _run(absent, "--template", str(tmp_path / "not_there"))
    n = _run(never)

    assert a["status"] == ST.STATUS_ABSENT
    assert n["status"] == ST.STATUS_NOT_ATTEMPTED
    assert a["lookup"]["attempted"] is True
    assert n["lookup"]["attempted"] is False
    assert a["lookup"]["searched"] == [str(tmp_path / "not_there")]
    assert n["lookup"]["searched"] == [], (
        "a search that never happened must not name a path it did not look at")
    assert a["lookup"]["path_exists"] is False
    assert n["lookup"]["path_exists"] is False
    # and the difference survives into the prose half too
    assert "NOT_ATTEMPTED" in (never / ST.NO_DECLARATION_REL).read_text()
    assert "ABSENT" in (absent / ST.NO_DECLARATION_REL).read_text()
    # NEITHER wrote the router: this absence was searched for but not DECLARED,
    # and that one was not even searched for
    assert not (never / ST.NO_TEMPLATE_REL).exists()
    assert not (absent / ST.NO_TEMPLATE_REL).exists()
    assert a["path_selector"]["declared"] is False
    assert n["path_selector"]["declared"] is False


def test_a_path_that_exists_but_is_not_a_directory_says_so(tmp_path):
    """An archive left unextracted at the given path is not "nothing there".
    This step reads a tree and never extracts, so the two must not share an
    answer."""
    proj = tmp_path / "d"
    proj.mkdir()
    archive = tmp_path / "template.tar.gz"
    archive.write_bytes(b"not extracted")
    rec = _run(proj, "--template", str(archive))
    assert rec["status"] == ST.STATUS_ABSENT
    assert rec["lookup"]["path_exists"] is True
    assert rec["lookup"]["template_present"] is False
    assert "not a directory" in (proj / ST.NO_DECLARATION_REL).read_text()


@pytest.mark.parametrize("argv", [(), ("--template", "__nowhere__"), ("real",)])
def test_the_report_is_emitted_on_every_path(template, tmp_path, argv):
    proj = tmp_path / "p"
    proj.mkdir()
    args = ("--template", str(template)) if argv == ("real",) else argv
    ING.main([str(proj), *args])
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    assert doc["ingest"]["status"] in (
        ST.STATUS_INGESTED, ST.STATUS_ABSENT, ST.STATUS_NOT_ATTEMPTED)


def test_a_router_file_is_written_only_when_a_decision_was_made(template, tmp_path):
    """THE INVARIANT, SHARPENED BY WHAT THE FLOW DOES WITH THESE FILES.

    `slots/*.yaml` and `NO_TEMPLATE.txt` are not notes, they are ROUTERS: the
    flow makes its chip-path steps applicable on the first and its IP-path step
    on the second, by `files_exist` and nothing else. So exactly one of them
    exists when a DECISION was made, and NEITHER exists when none was — while
    the step still says out loud what happened, in a file that routes nothing.
    """
    reason = ("Delivered as a hardmacro to an integrator and never submitted "
              "to a shuttle, so this design has no slot.")
    cases = [
        ("ingested", ("--template", str(template)), True, False),
        ("declared", ("--template", str(tmp_path / "gone"),
                      "--no-template-reason", reason), False, True),
        ("undeclared", ("--template", str(tmp_path / "gone"),), False, False),
        ("never", (), False, False),
    ]
    for name, args, want_slots, want_no_tmpl in cases:
        proj = tmp_path / f"p_{name}"
        proj.mkdir()
        rec = _run(proj, *args)
        slots = bool(list((proj / ST.SLOTS_DIR_REL).glob("*.yaml")))
        no_tmpl = (proj / ST.NO_TEMPLATE_REL).is_file()
        no_decl = (proj / ST.NO_DECLARATION_REL).is_file()
        assert (slots, no_tmpl) == (want_slots, want_no_tmpl), (
            f"{name}: slots={slots} no_template={no_tmpl}")
        assert rec["path_selector"]["declared"] is (slots or no_tmpl)
        # a decision writes exactly one router; no decision writes none of them
        # and says so somewhere that selects nothing
        assert no_decl is not (slots or no_tmpl)
        assert (proj / ST.REPORT_REL).is_file(), "the report is written always"


def test_a_re_ingest_retires_only_its_own_marker(template, project, tmp_path):
    _run(project, "--template", str(tmp_path / "gone"), "--no-template-reason",
         "Delivered as a hardmacro to an integrator and never submitted to a "
         "shuttle, so this design has no slot.")     # DECLARED -> router file
    assert (project / ST.NO_TEMPLATE_REL).is_file()
    _run(project, "--template", str(template), "--slot", "slot_a")
    assert not (project / ST.NO_TEMPLATE_REL).exists()

    # a marker this step did NOT write is somebody else's evidence and is left
    # exactly where it is; the checker refuses the contradiction instead.
    foreign = project / ST.NO_TEMPLATE_REL
    foreign.write_text("hand-written by an operator, not by this step\n")
    _run(project, "--template", str(template), "--slot", "slot_a")
    assert foreign.read_text().startswith("hand-written")


# --------------------------------------------------------------------------- #
# I6 / I7 — no network, no vendoring
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mod", ["submission_template_ingest.py",
                                 "submission_template_check.py",
                                 "_submission_template.py"])
def test_the_step_never_fetches(mod):
    """A step that silently downloads its input cannot be reproduced."""
    src = (PROGRAMS / mod).read_text()
    executable = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for token in ("urllib", "requests", "httpx", "socket", "urlopen",
                  "git clone", "curl ", "wget "):
        assert token not in executable, (
            f"{mod} reaches the network via {token!r}; the template is a path, "
            f"not a download")


def test_nothing_of_the_operators_is_copied_into_the_project(template, project):
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    src_bytes = {(template / "slots" / "slot_a.yaml").read_bytes(),
                 (template / "slots" / "slot_b.yaml").read_bytes(),
                 (template / "fixtures" / "die_id.gds").read_bytes()}
    for f in project.rglob("*"):
        if f.is_file():
            assert f.read_bytes() not in src_bytes, (
                f"{f} is a byte copy of an operator file; this step records "
                f"paths and digests, it does not vendor")
    assert all(fx["vendored"] is False for fx in rec["fixtures"])
    assert rec["provenance"]["vendored_into_this_repo"] is False


# --------------------------------------------------------------------------- #
# I8 — fixtures: paths and cell names, and an unread file says so
# --------------------------------------------------------------------------- #
def test_fixtures_are_recorded_by_path_and_cell_name(template, project):
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    fx = rec["fixtures"]
    assert len(fx) == 1
    assert fx[0]["path"] == str(template / "fixtures" / "die_id.gds")
    assert fx[0]["relpath"] == "fixtures/die_id.gds"
    assert fx[0]["cells"] == ["die_id_alpha", "die_id_beta"]
    assert fx[0]["cells_unread_reason"] is None
    assert len(fx[0]["sha256"]) == 64


def test_an_unread_fixture_records_null_and_a_reason_not_an_empty_list(
        template, project, monkeypatch):
    """An unmeasured thing must not read as a measured zero."""
    monkeypatch.setattr(ST, "MAX_FIXTURE_READ_BYTES", 4)
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    fx = rec["fixtures"][0]
    assert fx["cells"] is None, (
        "cells=[] would say 'this fixture names no cells', which is a "
        "measurement nobody made")
    assert "ceiling" in fx["cells_unread_reason"]


def test_a_container_format_this_program_cannot_parse_says_so(template, project):
    (template / "fixtures" / "other.oas").write_bytes(b"%SEMI-OASIS\r\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    oas = next(f for f in rec["fixtures"] if f["kind"] == "oasis")
    assert oas["cells"] is None
    assert "not parsed" in oas["cells_unread_reason"]
    assert len(oas["sha256"]) == 64, "it is still recorded by path and digest"


# --------------------------------------------------------------------------- #
# I9 — the scan is honest about what it could not read
# --------------------------------------------------------------------------- #
def test_a_pad_list_per_die_side_is_read_as_one_slots_pads(template, project):
    """MEASURED on a real operator template: the pad list is not one key, it is
    one per die side. An ingester that looked for a single singular name found
    none and recorded a null -- a slot whose pads it had not understood, told
    apart from a slot with no pads by nothing at all."""
    (template / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\n"
        "CORE_AREA: [26, 26, 974, 1974]\n"
        "FP_SIZING: absolute\n"
        "PAD_SOUTH: [s0, s1]\n"
        "PAD_EAST: [e0]\n"
        "PAD_NORTH: [n0, n1, n2]\n"
        "PAD_WEST: [w0]\n"
        "VERILOG_DEFINES: [SOME_DEFINE]\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    a = next(s for s in rec["slots"] if s["slot"] == "slot_a")
    assert a["pads"]["keys_matched"] == ["PAD_SOUTH", "PAD_EAST", "PAD_NORTH",
                                         "PAD_WEST"]
    assert a["pads"]["count"] == 7
    assert [d["raw"] for d in a["pads"]["lists"]] == [
        ["s0", "s1"], ["e0"], ["n0", "n1", "n2"], ["w0"]]
    # and the list key that is NOT a pad list is named, not swallowed
    assert a["pads"]["unmatched_list_keys"] == ["VERILOG_DEFINES"]


def test_a_pad_list_under_an_unknown_name_is_recorded_as_unread(
        template, project):
    (template / "slots" / "slot_a.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\n"
        "CORE_AREA: [26, 26, 974, 1974]\n"
        "PAD_RING: [p0, p1]\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    a = next(s for s in rec["slots"] if s["slot"] == "slot_a")
    assert a["pads"]["lists"] == []
    assert a["pads"]["unmatched_list_keys"] == ["PAD_RING"], (
        "the key the pattern did not claim must be NAMED — that is what makes "
        "a miss visible on the first run instead of the second")


def test_a_config_that_pins_no_die_is_not_a_slot(template, project):
    (template / "tool.yaml").write_text("SOME_TOOL_OPTION: 3\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    assert rec["slots_shipped"] == ["slot_a", "slot_b"]
    assert rec["scan"]["config_files_examined"] == 3


def test_an_unparsable_config_is_recorded_not_dropped(template, project):
    bad = template / "broken.yaml"
    bad.write_text("DIE_AREA: [0, 0, 1, 1\n  oops: : :\n")
    rec = _run(project, "--template", str(template), "--slot", "slot_a")
    assert [u["file"] for u in rec["scan"]["unparsable"]] == [str(bad)]
    assert rec["scan"]["truncated"] is False


def test_a_slot_name_may_come_from_the_file_or_from_a_key(template, project):
    (template / "slots" / "slot_b.yaml").write_text(
        "SLOT: named_by_key\n" + SLOT_B)
    rec = _run(project, "--template", str(template))
    by = {s["slot"]: s["slot_name_source"] for s in rec["slots"]}
    assert by == {"slot_a": "file stem", "named_by_key": "key SLOT"}


def test_two_files_with_the_same_slot_name_both_land_on_disk(template, project):
    (template / "other").mkdir()
    (template / "other" / "slot_a.yaml").write_text(SLOT_B)
    rec = _run(project, "--template", str(template))
    assert [s["slot"] for s in rec["slots"]] == ["slot_a", "slot_a", "slot_b"]
    names = sorted(p.name for p in (project / ST.SLOTS_DIR_REL).glob("*.yaml"))
    assert names == ["slot_a.yaml", "slot_a__2.yaml", "slot_b.yaml"], (
        "neither record may overwrite the other — the collision is a fact the "
        "checker refuses, not one the ingester hides")
