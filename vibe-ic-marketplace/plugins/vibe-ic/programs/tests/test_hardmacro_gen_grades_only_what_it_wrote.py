#!/usr/bin/env python3
"""G18 — step 37.5ip graded a kit it had not written, and could not repair one.

MEASURED 2026-09-02 on host 8HD-4, live main v1.16.21 (694fef5cb302), against
`spm x gf180mcuD` staged 2026-09-01 02:07 (before #1991 taught this producer to
expose the rails).  `digital_hardmacro_gen` skipped every view because a kit was
already on disk, then applied its supply acceptance to those untouched bytes:

    $ python3 programs/digital_hardmacro_gen.py . \\
        --pdk-root /foss/pdks/gf180mcuD --cell-lef <gf180 mcu7t5v0 LEF>
    [REFUSED_NOT_INTEGRABLE] digital_hardmacro_gen — the staged hardmacro views
    did not preserve the exact derived supply interface:
    expected {'VDD': 'POWER', 'VSS': 'GROUND'}; LEF has {}; Liberty has {}
    -> rc 1, and `ls -la phase3/stage4/hardmacro/` unchanged: 九  1 02:07

    $ rm -rf phase3/stage4/hardmacro && <the identical command>
    [PRODUCED] digital_hardmacro_gen; produced spm.gds, spm.v, spm.lib, spm.lef
    -> rc 0, and the new LEF carries USE POWER / USE GROUND, the .lib two
       pg_pin groups.

TWO FAULTS, ONE SENTENCE.  "Magic dropped a port out of the LEF I just wrote"
(#1991's subject, a real bug in this producer) and "I wrote nothing and am
describing an older run's kit" print the same refusal, and they need opposite
fixes.  The second also had no exit: no re-run healed the tree, only `rm -rf`
did, so every cell published before 2026-09-01 was stuck at step 37.5ip.

THE REFUSAL IS NOT THE DEFECT.  A kit with no physical supplies is not
deliverable and must still be refused — #1991's check is asserted here, in both
directions, so a fix to the attribution cannot quietly remove it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(os.environ.get(
    "VIBEIC_CONTRACT_PROGRAMS",
    str(Path(__file__).resolve().parent.parent))).resolve()
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import digital_hardmacro_gen as gen  # noqa: E402

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
from test_issue1991_hardmacro_supply_pins import (  # noqa: E402
    _fake_magic, _lef_from_def, _pdk, _project, DEF_NO_TOP_PG, _FakeSite)


#: What the pre-#1991 producer left on disk: a complete-looking four-view kit
#: whose LEF has every signal pin and NO supply pin, and whose Liberty has no
#: `pg_pin` group at all.  Shape copied from the measured `spm` kit.
STALE_LEF = """VERSION 5.8 ;
MACRO macro_a
  SIZE 100 BY 50 ;
  PIN clk
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER metal2 ;
      RECT 1 1 2 2 ;
    END
  END clk
END macro_a
END LIBRARY
"""

STALE_LIB = """library (macro_a) {
  cell (macro_a) {
    pin (clk) { direction : input ; }
  }
}
"""


def _stale_kit(project: Path, design: str = "macro_a") -> Path:
    """A kit from an earlier run, exactly as `rm -rf` was the only cure for."""
    hm = project / "phase3" / "stage4" / "hardmacro"
    hm.mkdir(parents=True, exist_ok=True)
    (hm / f"{design}.lef").write_text(STALE_LEF)
    (hm / f"{design}.lib").write_text(STALE_LIB)
    (hm / f"{design}.v").write_text(
        f"module {design} (input clk);\nendmodule\n")
    (hm / f"{design}.gds").write_bytes(b"old-signoff-gds-bytes\n")
    return hm


# ── the defect: attribution ───────────────────────────────────────────────

def test_a_stale_kit_is_re_produced_instead_of_refused(tmp_path, monkeypatch):
    """The measured tree, hermetically: a run over a pre-#1991 kit must heal
    it.  `rm -rf phase3/stage4/hardmacro` is not a step of this flow."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    hm = _stale_kit(project)
    _fake_magic(monkeypatch, {})

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == 0, (record.status, record.reason)
    lef = (hm / "macro_a.lef").read_text()
    lib = (hm / "macro_a.lib").read_text()
    assert "PIN rail_hi" in lef and "USE POWER" in lef
    assert "PIN rail_lo" in lef and "USE GROUND" in lef
    assert "pg_pin (rail_hi) { pg_type : primary_power ; }" in lib
    assert "pg_pin (rail_lo) { pg_type : primary_ground ; }" in lib


def test_the_acceptance_reports_only_views_this_run_wrote(tmp_path,
                                                          monkeypatch):
    """`staged_lef_power_ground` is this run's OWN output, graded.  Publishing
    it for a file the run never opened for writing is the misattribution: a
    reader cannot then tell a dropped port from somebody else's kit."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    _stale_kit(project)
    _fake_magic(monkeypatch, {})

    _rc, record = gen.run(project, str(pdk), False, False)

    for view, key in (("macro_a.lef", "staged_lef_power_ground"),
                      ("macro_a.lib", "staged_liberty_power_ground")):
        if key in record.interface:
            assert view in record.produced, (
                f"{key} grades {view}, which this run did not write; "
                f"produced={record.produced}")


def test_replacing_a_delivered_kit_is_a_stated_decision(tmp_path, monkeypatch,
                                                        capsys):
    """A kit is a delivery.  Repairing one is allowed; swapping one out from
    under a consumer without saying so is the other half of the same fault."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    _stale_kit(project)
    _fake_magic(monkeypatch, {})
    monkeypatch.setattr(sys, "argv", ["prog"])

    rc = gen.main([str(project), "--pdk-root", str(pdk)])
    said = capsys.readouterr()

    assert rc == 0
    assert "REPLACED" in (said.out + said.err)
    assert "macro_a.lef" in (said.out + said.err)


def test_the_record_names_every_view_it_displaced_and_why(tmp_path,
                                                          monkeypatch):
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    _stale_kit(project)
    _fake_magic(monkeypatch, {})

    _rc, record = gen.run(project, str(pdk), False, False)

    assert set(record.replaced) >= {"macro_a.lef", "macro_a.lib"}
    assert set(record.replaced) <= set(record.produced)
    assert record.replaced_reason
    assert "rail_hi" in record.replaced_reason


def test_a_stale_kit_is_kept_when_no_replacement_can_be_written(tmp_path,
                                                                monkeypatch):
    """Removing a delivery this run cannot re-produce would leave the tree
    with LESS than it started with.  Magic unreachable -> the old kit stands,
    untouched, and the run says it is an absent capability (rc 2), not a
    verdict on a kit."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    hm = _stale_kit(project)
    monkeypatch.setattr(gen, "find_magic_site",
                        lambda _container="": _FakeSite())
    monkeypatch.setattr(gen, "write_lef_with_magic",
                        lambda *_a, **_k: (False, "magic is not reachable"))

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == gen.RC_NO_CAPABILITY, (record.status, record.reason)
    assert (hm / "macro_a.lef").read_text() == STALE_LEF
    assert (hm / "macro_a.lib").read_text() == STALE_LIB
    assert record.replaced == []


# ── the control, forward: a kit that is already right is left alone ───────

def _good_kit(project: Path, pdk: Path):
    """A kit that already carries the interface this run would derive, built
    from the producer's OWN emitters so "already correct" means what the
    producer means by it."""
    hm = project / "phase3" / "stage4" / "hardmacro"
    hm.mkdir(parents=True, exist_ok=True)
    augmented, pins, why = gen.add_supply_pins_to_def(
        DEF_NO_TOP_PG, gen.discover_stdcell_rails(
            (pdk / "libs.ref/cells/lef/cells.lef").read_text(), "metal"))
    assert augmented is not None, why
    (hm / "macro_a.lef").write_text(_lef_from_def(augmented, "macro_a"))
    (hm / "macro_a.lib").write_text(gen.emit_liberty("macro_a", pins))
    (hm / "macro_a.v").write_text(gen.emit_verilog("macro_a", pins))
    (hm / "macro_a.gds").write_bytes(b"a staged sign-off gds\n")
    return hm


def test_a_pg_complete_existing_kit_still_passes_untouched(tmp_path,
                                                           monkeypatch):
    """FORWARD CONTROL, stated in terms BOTH trees can answer.

    This arm carries no reference to anything the fix adds, so it is
    measurable against the unfixed producer too — and it is GREEN there.  That
    is what makes it a control: the fix must not buy the stale-kit repair by
    turning the producer into something that rewrites, or re-verdicts, a kit
    that was already right.
    """
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    hm = _good_kit(project, pdk)
    before = {q.name: q.read_bytes() for q in sorted(hm.iterdir())}

    def _never(*_a, **_k):  # pragma: no cover - the assertion is the point
        raise AssertionError("a PG-complete kit must not be rewritten")

    monkeypatch.setattr(gen, "write_lef_with_magic", _never)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == 0, (record.status, record.reason)
    assert {q.name: q.read_bytes() for q in sorted(hm.iterdir())} == before


def test_a_pg_complete_existing_kit_is_neither_regraded_nor_rewritten(
        tmp_path, monkeypatch):
    """FORWARD CONTROL.  The producer must not have become a rewriter: a kit
    that already carries this run's derived interface is skipped, byte for
    byte, and magic is never asked for anything."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    hm = _good_kit(project, pdk)
    before = {q.name: q.read_bytes() for q in sorted(hm.iterdir())}

    def _never(*_a, **_k):  # pragma: no cover - the assertion is the point
        raise AssertionError("a PG-complete kit must not be rewritten")

    monkeypatch.setattr(gen, "write_lef_with_magic", _never)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == 0, (record.status, record.reason)
    assert record.replaced == [] and record.produced == []
    assert {q.name: q.read_bytes() for q in sorted(hm.iterdir())} == before


# ── the control, reverse: #1991's check is still armed ────────────────────

def test_a_freshly_written_lef_missing_a_rail_is_still_refused(tmp_path,
                                                               monkeypatch):
    """REVERSE CONTROL.  #1991's acceptance must survive the attribution fix.
    Magic exits zero having dropped the power rail out of the LEF THIS RUN
    WROTE — that is this producer's own output and its own defect to catch."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    monkeypatch.setattr(gen, "find_magic_site",
                        lambda _container="": _FakeSite())

    def drop_power(top, _gds, def_file, out_lef, *_a, **_k):
        text = _lef_from_def(Path(def_file).read_text(), top)
        head = text.index("  PIN rail_hi")
        tail = text.index("  END rail_hi") + len("  END rail_hi\n")
        Path(out_lef).write_text(text[:head] + text[tail:])
        return True, ""

    monkeypatch.setattr(gen, "write_lef_with_magic", drop_power)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == gen.RC_REFUSED
    assert record.status == "REFUSED_NOT_INTEGRABLE"
    assert record.interface["integrable"] is False
    assert record.interface["staged_lef_power_ground"] == {"rail_lo": "GROUND"}


def test_a_replacement_that_drops_a_rail_is_refused_after_it_is_written(
        tmp_path, monkeypatch):
    """REVERSE CONTROL over the NEW path.  Repairing a stale kit must not
    become a way past the check: the replacement is graded exactly like any
    other output of this run, and a replacement missing a rail refuses."""
    project = _project(tmp_path / "project")
    pdk = _pdk(tmp_path / "pdk")
    hm = _stale_kit(project)
    monkeypatch.setattr(gen, "find_magic_site",
                        lambda _container="": _FakeSite())

    def drop_ground(top, _gds, def_file, out_lef, *_a, **_k):
        text = _lef_from_def(Path(def_file).read_text(), top)
        head = text.index("  PIN rail_lo")
        tail = text.index("  END rail_lo") + len("  END rail_lo\n")
        Path(out_lef).write_text(text[:head] + text[tail:])
        return True, ""

    monkeypatch.setattr(gen, "write_lef_with_magic", drop_ground)

    rc, record = gen.run(project, str(pdk), False, False)

    assert rc == gen.RC_REFUSED
    assert record.status == "REFUSED_NOT_INTEGRABLE"
    # ...and the refusal is about what it wrote, which it did write.
    assert "macro_a.lef" in record.produced
    assert record.interface["staged_lef_power_ground"] == {"rail_hi": "POWER"}
    assert (hm / "macro_a.lef").read_text() != STALE_LEF


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
