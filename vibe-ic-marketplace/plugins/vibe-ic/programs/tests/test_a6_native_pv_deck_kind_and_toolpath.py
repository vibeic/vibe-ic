"""A6 native per-block PV — the three reasons it never produced DRC evidence
on an OPEN PDK, and the false clean that fixing only the obvious one creates.

WHAT WAS BROKEN, MEASURED ON A REAL RUN
=======================================
A design staging its own KLayout sign-off deck reached A6 and got
`A6_PV_DRC_NO_EVIDENCE` on both of its analog blocks. Three separate defects
sat in a row, and the ORDER they are fixed in matters:

1. `_tool_on_path` returned the tool path with the pinned image's entrypoint
   banner (`[INFO] Final PATH variable: ...`) glued to the front of it. The
   blob is truthy, so every caller believed the engine was present, then ran
   the whole blob shell-quoted as one argument: rc 127, no report. Measured
   for BOTH engines — `svrfdrc` AND `klayout` — so the native DRC path had
   never executed in that image at all.

2. The only DRC engine wired was `svrfdrc`, which reads SVRF. The resolver's
   own `drc_deck` axis globs `input/pdk/klayout/*.drc`, because a KLayout
   runset is what an open PDK ships. Handed one, `svrfdrc` does not fail: it
   derives the layers, finds ZERO rules, and writes a report with an empty
   tally.

3. `_default_drc_runner` counted `FAIL` lines in that report. Zero FAILs out
   of zero rules was returned as `violations=0` — DRC CLEAN.

THE ORDERING HAZARD THIS FILE EXISTS TO PIN
===========================================
Defect 1 is the obvious one and it is the dangerous one to fix alone. While it
stands, A6 says "no evidence" — useless, but honest. Fix ONLY it and `svrfdrc`
starts executing against a deck it cannot read, the empty tally is credited,
and A6 certifies a block DRC-CLEAN. Measured on a real block whose 4
violations a correct run of the SAME deck finds: pristine -> no evidence;
tool-path fix alone -> `violations=0, verdict=PASS`; tool-path + the
graded-nothing guard -> no evidence (safe); all three -> `violations=4,
verdict=FAIL`.

So the guard in (3) is not belt-and-braces: it is what keeps (1) from being a
regression, and the dispatch in (2) is what turns "no evidence" into a real
measurement.

NDA hygiene: synthetic deck / block names; the injected runners return
NUMBERS, never deck content.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a6_native_pv as PV               # noqa: E402
import analog_a6_block_pv_check as A6           # noqa: E402

BLOCK = "u_reg_alpha"


def _mk_project(tmp_path: Path) -> Path:
    ad = tmp_path / "phase3" / "analog"
    bdir = ad / BLOCK
    bdir.mkdir(parents=True)
    (ad / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": BLOCK, "type": "ldo"}]}))
    (bdir / f"{BLOCK}.gds").write_bytes(b"\x00GDSII-fake\x00" * 4)
    (bdir / f"{BLOCK}.sp").write_text(
        f".subckt {BLOCK} vdd vss vin vout\nr1 vin vout 1k\n.ends\n")
    return tmp_path


# ── (2) deck kind ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,kind", [
    ("/p/klayout/openpdk.drc", "klayout"),
    ("/p/klayout/openpdk.lydrc", "klayout"),
    ("/p/calibre/FOUNDRY_DRC.rule", "svrf"),
    ("/p/calibre/deck.svrf", "svrf"),
    ("/p/magic/foundry.tech", "unknown"),
    ("", "unknown"),
])
def test_deck_kind_is_read_off_the_deck_itself(name, kind):
    assert PV.deck_kind(name) == kind


def test_a_deck_of_no_known_kind_is_refused_by_name_not_guessed(tmp_path):
    """Running a deck under the wrong engine yields a rule-less report rather
    than an error, so guessing is the one thing that must not happen."""
    viol, meta = PV._default_drc_runner(
        "/p/magic/foundry.tech", "/p/b.gds", BLOCK, "no-such-container",
        tmp_path / "drc.report")
    assert viol is None
    assert "neither an SVRF" in meta["reason"], meta


def test_the_klayout_path_is_selected_for_an_open_pdk_deck(monkeypatch,
                                                           tmp_path):
    """The dispatch must actually reach the KLayout runner — asserted by
    intercepting it, so a future refactor that drops the branch is caught."""
    seen = {}

    def fake_klayout(deck, gds, block, container, report_host):
        seen.update(deck=deck, block=block)
        return 7, {"method": "klayout_runset", "rc": 0}

    monkeypatch.setattr(PV, "_klayout_drc_runner", fake_klayout)
    viol, meta = PV._default_drc_runner(
        "/p/klayout/openpdk.drc", "/p/b.gds", BLOCK, "ctr",
        tmp_path / "drc.report")
    assert viol == 7 and meta["method"] == "klayout_runset"
    assert seen["deck"].endswith(".drc") and seen["block"] == BLOCK


# ── (1) tool path ─────────────────────────────────────────────────────────
def test_tool_path_survives_an_entrypoint_banner_on_stdout(monkeypatch):
    """THE ROOT CAUSE. The pinned image prints two `[INFO] Final PATH ...`
    lines before the command's own output; the old reader returned all three
    lines as "the path"."""
    banner = ("[INFO] Final PATH variable: /a:/b\n"
              "[INFO] Final PYTHONPATH variable: /c:/d\n"
              "/foss/tools/klayout/klayout\n")
    monkeypatch.setattr(PV, "_docker_exec",
                        lambda *a, **k: (0, banner, ""))
    assert PV._tool_on_path("ctr", "klayout") == "/foss/tools/klayout/klayout"


def test_tool_path_is_still_none_when_the_tool_is_absent(monkeypatch):
    monkeypatch.setattr(PV, "_docker_exec", lambda *a, **k: (1, "", "not found"))
    assert PV._tool_on_path("ctr", "klayout") is None


def test_tool_path_is_unchanged_on_a_quiet_image(monkeypatch):
    """An image with no banner must behave exactly as before."""
    monkeypatch.setattr(PV, "_docker_exec",
                        lambda *a, **k: (0, "/usr/bin/klayout\n", ""))
    assert PV._tool_on_path("ctr", "klayout") == "/usr/bin/klayout"


# ── (3) the false clean ───────────────────────────────────────────────────
def test_a_report_that_graded_nothing_is_not_a_clean_report(tmp_path,
                                                            monkeypatch):
    """THE CONTROL THAT MATTERS. This is the exact artefact `svrfdrc` writes
    when it is handed a deck it cannot read: a well-formed report whose tally
    is empty. Counting its zero FAIL lines as zero violations is the false
    clean; it must come back as NO EVIDENCE instead."""
    rpt = tmp_path / "drc.report"
    rpt.write_text("# SVRF-native DRC via KLayout\n"
                   "# 0 layers, 122 derivations, 0 rules  |  {}\n"
                   "\n# tally: {}\n")
    monkeypatch.setattr(PV, "_tool_on_path", lambda c, t: "/bin/svrfdrc")
    monkeypatch.setattr(PV, "_docker_exec", lambda *a, **k: (0, "", ""))
    viol, meta = PV._default_drc_runner(
        "/p/calibre/FOUNDRY_DRC.rule", "/p/b.gds", BLOCK, "ctr", rpt)
    assert viol is None, "a rule-less report was credited as clean"
    assert "graded 0 rules" in meta["reason"], meta


def test_a_report_that_graded_rules_is_still_counted(tmp_path, monkeypatch):
    """The guard must not swallow a real clean run: a deck that graded rules
    and found no failures is genuinely 0 violations."""
    rpt = tmp_path / "drc.report"
    rpt.write_text("PASS rule_a\nPASS rule_b\nSKIP rule_c\n")
    monkeypatch.setattr(PV, "_tool_on_path", lambda c, t: "/bin/svrfdrc")
    monkeypatch.setattr(PV, "_docker_exec", lambda *a, **k: (0, "", ""))
    viol, meta = PV._default_drc_runner(
        "/p/calibre/FOUNDRY_DRC.rule", "/p/b.gds", BLOCK, "ctr", rpt)
    assert viol == 0 and meta["rules_pass"] == 2, meta


def test_a_real_violation_count_still_fails(tmp_path, monkeypatch):
    rpt = tmp_path / "drc.report"
    rpt.write_text("FAIL rule_a\nFAIL rule_b\nPASS rule_c\n")
    monkeypatch.setattr(PV, "_tool_on_path", lambda c, t: "/bin/svrfdrc")
    monkeypatch.setattr(PV, "_docker_exec", lambda *a, **k: (0, "", ""))
    viol, _ = PV._default_drc_runner(
        "/p/calibre/FOUNDRY_DRC.rule", "/p/b.gds", BLOCK, "ctr", rpt)
    assert viol == 2


# ── end to end through the gate ───────────────────────────────────────────
def test_an_unreadable_deck_leaves_a6_without_evidence_not_passing(tmp_path):
    """Producer -> gate: no evidence must NOT become an A6 pass."""
    proj = _mk_project(tmp_path)
    out = PV.run_block_pv(
        proj, BLOCK,
        {"drc_deck": "/p/klayout/openpdk.drc", "lvs_deck": None},
        container="ctr",
        drc_runner=lambda *a: (None, {"reason": "deck graded 0 rules"}),
        lvs_runner=lambda *a: (None, {"reason": "no lvs"}))
    assert out["ran"] is False, out
    assert not (proj / "phase3/analog" / BLOCK / "drc.report").exists()


def test_a_violating_block_reaches_the_gate_as_a_fail(tmp_path):
    proj = _mk_project(tmp_path)
    PV.run_block_pv(
        proj, BLOCK,
        {"drc_deck": "/p/klayout/openpdk.drc",
         "lvs_deck": "/p/netgen/setup.tcl"},
        container="ctr",
        drc_runner=lambda *a: (4, {"method": "klayout_runset"}),
        lvs_runner=lambda *a: ("match", {"method": "klayout_pdk_lvs"}))
    o = proj / "a6.json"
    A6.main([str(proj), "--block", BLOCK, "--json", str(o)])
    assert json.loads(o.read_text())["verdict"] == "FAIL"
