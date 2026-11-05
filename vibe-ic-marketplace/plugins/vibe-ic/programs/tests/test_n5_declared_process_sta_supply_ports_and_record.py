#!/usr/bin/env python3
"""N5 — the post-route PVT sweep the sign-off gate requires was MEASURED and
then thrown away by the producer's own annotation census.

MEASURED (spm x gf180mcuD as a HARDMACRO, image 0.3.83, stack33 + N4,
2026-09-28): `_emit_declared_process_sta` ran all six sections (FF/SS/TT x
setup/hold) on the routed netlist + the run's own SPEF, and OpenSTA reported
15 unannotated drivers per corner: 13 unconnected clkload/spare outputs, and
the two SUPPLY PORTS `VDD` / `VSS` of the hard-macro netlist (`inout VDD;`).
The routed DEF carries the supply only as special nets
(`- VDD ( * VNW ) ( * VDD ) + USE POWER`) with no `( PIN VDD )` and no PINS
row, so `sta_annotation_population.classify` bound nothing to the port and
left it REQUIRED_OR_UNKNOWN; the whole sweep was refused and renamed
`.attempt-<uuid>`; `sta_record` R6 then found FF-setup / SS-hold / TT
NOT_MEASURED, the pre-stream gate failed, and no GDS was streamed.

With the report promoted, the UNCHANGED gate returns PASS (checked on the run's
own bytes). The gate is not touched here; these tests pin the producer:

  1. a top-level port whose OWN net the DEF types USE POWER/GROUND (exactly
     one statement) is supply, not signal parasitics; conflicting or signal
     typing stays unknown;
  2. with such ports, the sweep is PROMOTED and the unchanged gate's R6 finds
     every declared (corner, check) measured post-route;
  3. every section names the sha256 of the liberty / SPEF / netlist / SDC it
     timed, and one record row per (declared corner, check) is written --
     MEASURED with its slack and sources, or NOT_MEASURED with the reason.

chip-, PDK- and vendor-AGNOSTIC: the fixture is synthetic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


import phase3_one_shot_runner as p3
import sta_corner_record_completeness_check as gate
from test_declared_process_sta_producer import scene  # noqa: F401  (fixture)



_CENSUS_WITH_SUPPLY_PORTS = (
    "STA_LINK_INSTANCE u1 core/INV\n"
    "STA_LINK_CENSUS total=1 linked=1 missing=0\n"
    "Found 2 unannotated drivers.\n VDD\n VSS\n"
    "Found 0 partially unannotated drivers.\n")


def _def(tmp: Path, vdd_use="POWER", vss_use="GROUND", extra="") -> Path:
    d = tmp / "phase3/stage3/pnr/dut.def"
    d.parent.mkdir(parents=True, exist_ok=True)
    special = [f"- VDD ( * VDD ) + USE {vdd_use} ;",
               f"- VSS ( * VSS ) + USE {vss_use} ;"] + ([extra] if extra else [])
    d.write_text(
        "DESIGN dut ;\n"
        "PINS 1 ;\n- clk + NET clk + DIRECTION INPUT + USE SIGNAL ;\nEND PINS\n"
        "COMPONENTS 1 ;\n- u1 INV ;\nEND COMPONENTS\n"
        f"SPECIALNETS {len(special)} ;\n" + "\n".join(special) + "\nEND SPECIALNETS\n"
        "NETS 1 ;\n- clk ( PIN clk ) ( u1 A ) + USE SIGNAL ;\nEND NETS\n")
    return d


# ── 1. the classifier ────────────────────────────────────────────────────────









# ── 2+3. the producer, driven end to end with a Tcl-faithful double ──────────

def _native_double(census: str):
    """Writes what the Tcl ASKS for: every `puts $_f {...}` header line the
    script emits, the census after the SETUP header, and one slack line per
    requested check. A CPU stand-in for `sta`, like the sibling fixture's."""
    def run(container, cmd, **kw):
        tcl = Path(kw["marker"]).read_text()
        out = Path(kw["isolate"][0])
        out.parent.mkdir(parents=True, exist_ok=True)
        chunks = re.split(r"set _f \[open \{[^}]*\} (?:w|a)\]\n", tcl)[1:]
        text = ""
        for ch in chunks:
            head = ch.split("close $_f", 1)[0]
            lines = re.findall(r"^puts \$_f \{(.*)\}$", head, re.M)
            text += "\n".join(lines) + "\n"
            if lines and lines[0].startswith("=== SETUP"):
                text += census + "worst slack max 1.25\ntns max 0.00\n"
            elif lines and lines[0].startswith("=== HOLD"):
                text += "worst slack min 0.40\ntns min 0.00\n"
        mode = "a" if out.exists() else "w"
        with out.open(mode) as f:
            f.write(text)
        return 0, "", ""
    return run


def _stage_gate_inputs(tmp: Path, by: dict) -> None:
    """The run artefacts the gate reads besides the sweep: the PVT matrix
    (step 7) and the process stance, as the flow writes them."""
    m = tmp / "phase2/stage2/constraints/pvt_matrix.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"corners": [
        {"name": Path(by[c]).stem, "label": c, "liberty": by[c]}
        for c in ("SS", "TT", "FF")], "primary_corner": "TT"}))
    st = tmp / "reports/phase3/mcorner_ocv_stance.json"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps({"setup_process_corner": "SS",
                              "hold_process_corner": "FF"}))


def test_supply_ports_no_longer_quarantine_the_sweep_and_the_gate_sees_every_corner(
        scene, monkeypatch):
    """RED on main: the sweep is refused, `sta_spef_based.rpt` is never
    promoted, and R6 names every required (corner, check) NOT_MEASURED."""
    s = scene
    _def(s["tmp_path"])
    monkeypatch.setattr(p3, "_docker_exec", _native_double(_CENSUS_WITH_SUPPLY_PORTS))
    assert s["emit"](), "the complete sweep was refused"
    assert s["rpt"].is_file()
    _stage_gate_inputs(s["tmp_path"], s["by"])
    decl = gate.read_declarations(s["tmp_path"])
    assert set(decl["required_pvt_corners"]) == {"SS", "TT", "FF"}
    recs = gate.read_records(s["tmp_path"], decl)
    for c in ("SS", "TT", "FF"):
        rec = recs[gate._key(gate.AXIS_PROCESS, c)]
        assert rec["basis_used"].get("setup_wns_ns") == gate.BASIS_SIGNOFF, rec
        assert rec["basis_used"].get("hold_wns_ns") == gate.BASIS_SIGNOFF, rec




def test_a_refused_sweep_keeps_every_measured_row_and_records_the_refusal_beside_it(
        scene, monkeypatch):
    """Review wave 5 (integrity MAJOR). A supply port the DEF does NOT type
    still refuses the sweep -- but the slacks the run DID measure stay
    MEASURED (promoted: false), and the refusal naming the driver sits at the
    top of the record and in each corner's census field."""
    s = scene
    _def(s["tmp_path"], vdd_use="SIGNAL")
    monkeypatch.setattr(p3, "_docker_exec", _native_double(_CENSUS_WITH_SUPPLY_PORTS))
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / "reports/phase3/sta/declared_process_sta.json").read_text())
    assert rec["status"] == "REFUSED" and "VDD" in rec["reason"], rec
    assert rec["report"] is None
    for c in ("SS", "TT", "FF"):
        for role, wns in (("setup", 1.25), ("hold", 0.40)):
            row = rec["corners"][c][role]
            assert row["status"] == "MEASURED" and row["wns_ns"] == wns, row
            assert row["promoted"] is False
            assert row["annotation_census"].startswith("INCOMPLETE"), row
            assert "VDD" in row["annotation_census"]


def test_a_missing_section_is_its_own_reason_and_measured_rows_survive(
        scene, monkeypatch):
    """Only the rows that were not measured are NOT_MEASURED, each with its
    own reason; the refusal (measurements incomplete) is beside them."""
    s = scene
    _def(s["tmp_path"])
    base = _native_double(_CENSUS_WITH_SUPPLY_PORTS)

    def drop_tt_hold(container, cmd, **kw):
        rc = base(container, cmd, **kw)
        out = Path(kw["isolate"][0])
        text = out.read_text()
        cut = text.find("=== HOLD corner: process=TT ===")
        if cut >= 0:
            nxt = text.find("=== ", cut + 4)
            out.write_text(text[:cut] + (text[nxt:] if nxt >= 0 else ""))
        return rc
    monkeypatch.setattr(p3, "_docker_exec", drop_tt_hold)
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / "reports/phase3/sta/declared_process_sta.json").read_text())
    assert rec["status"] == "REFUSED" and "incomplete" in rec["reason"]
    tt_hold = rec["corners"]["TT"]["hold"]
    assert tt_hold["status"] == "NOT_MEASURED"
    assert tt_hold["reason"] == "no HOLD section for TT in the native report"
    assert rec["corners"]["TT"]["setup"]["status"] == "MEASURED"
    assert rec["corners"]["SS"]["hold"]["wns_ns"] == 0.40


def test_a_producer_refusal_before_any_measurement_marks_every_row(scene):
    """Inside the producer: nothing was measured, so every row carries the
    refusal's reason."""
    s = scene
    s["spef"].unlink()
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / "reports/phase3/sta/declared_process_sta.json").read_text())
    assert rec["status"] == "REFUSED" and "SPEF" in rec["reason"]
    assert {r["status"] for c in rec["corners"].values() for r in c.values()} == {"NOT_MEASURED"}


def test_the_step23_caller_records_the_declared_corners_when_no_spef_exists(scene):
    """Review wave 5: the producer is only CALLED with a SPEF, so the
    no-SPEF record has to come from the caller. Drives the shipped step-23
    block (the same slice the landed caller test executes)."""
    import textwrap
    s = scene
    s["spef"].unlink()
    source = Path(p3.__file__).read_text()
    block = source.split('    # --- Step 23: SPEF-based post-route STA (#527)')[1].split(
        '    # --- TAPEOUT-SIGNOFF P1: multi-corner SPEF')[0]
    block = block[block.index('    spef_sta_rpt ='):]
    scope = dict(vars(p3), sta_out=s["rpt"].parent, spef_out=s["spef"],
                 primary_def=s["spef"], project=s["tmp_path"], top="dut",
                 pdk=s["pdk"], container="fixture", notes=[], written=[],
                 rpt_phase3=s["tmp_path"], _signoff_regen=lambda *a: True)
    exec(textwrap.dedent(block), scope)
    rec = json.loads((s["tmp_path"] / "reports/phase3/sta/declared_process_sta.json").read_text())
    assert rec["status"] == "NOT_RUN" and "no non-empty SPEF" in rec["reason"]
    assert sorted(rec["corners"]) == ["FF", "SS", "TT"]
    assert {r["status"] for c in rec["corners"].values() for r in c.values()} == {"NOT_MEASURED"}






# ── review wave 7 ────────────────────────────────────────────────────────────

_REC = "reports/phase3/sta/declared_process_sta.json"


def _fail_at(corner: str, census: str = _CENSUS_WITH_SUPPLY_PORTS):
    """The same Tcl-faithful double, except that the invocation for `corner`
    writes its SETUP header and dies the way `sta` does: rc 1 plus an
    `Error:` line (e.g. the preamble's `unreadable STA input`)."""
    base = _native_double(census)

    def run(container, cmd, **kw):
        tcl = Path(kw["marker"]).read_text()
        if f"process={corner} ===" in tcl:
            out = Path(kw["isolate"][0])
            with out.open("a" if out.exists() else "w") as f:
                f.write(f"=== SETUP corner: process={corner} ===\n"
                        "worst slack max 9.99\n")
            return 1, f"Error: something failed at {corner}\n", ""
        return base(container, cmd, **kw)
    return run


def test_a_native_failure_at_the_last_corner_keeps_the_earlier_corners(
        scene, monkeypatch):
    """MAJOR (both reviewers): corner 3 of 3 failing erased FF and SS."""
    s = scene
    _def(s["tmp_path"])
    monkeypatch.setattr(p3, "_docker_exec", _fail_at("TT"))
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / _REC).read_text())
    assert rec["status"] == "REFUSED" and "at TT" in rec["reason"], rec
    for c in ("FF", "SS"):
        for role, wns in (("setup", 1.25), ("hold", 0.40)):
            row = rec["corners"][c][role]
            assert row["status"] == "MEASURED" and row["wns_ns"] == wns, row
            assert row["promoted"] is False
    for role in ("setup", "hold"):
        row = rec["corners"]["TT"][role]
        assert row["status"] == "NOT_MEASURED" and row["wns_ns"] is None, row
    # the tool's own words are kept verbatim, and the row's reason names them
    logs = rec["attempt_report"]["native_logs"]
    assert len(logs) == 1 and logs[0].endswith(".TT.native.log")
    assert "Error: something failed at TT" in (s["tmp_path"] / logs[0]).read_text()
    for role in ("setup", "hold"):
        assert rec["corners"]["TT"][role]["reason"] == (
            f"native execution failed rc=1 at TT; the tool's own output: {logs[0]}")


def test_a_native_failure_at_a_middle_corner_names_the_later_corner_not_run(
        scene, monkeypatch):
    s = scene
    _def(s["tmp_path"])
    monkeypatch.setattr(p3, "_docker_exec", _fail_at("SS"))
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / _REC).read_text())
    assert rec["corners"]["FF"]["setup"]["status"] == "MEASURED"
    assert rec["corners"]["SS"]["hold"]["reason"].startswith(
        "native execution failed rc=1 at SS; the tool's own output: ")
    assert rec["corners"]["TT"]["setup"]["reason"] == "not run: sweep stopped at SS"
    assert rec["corners"]["TT"]["hold"]["status"] == "NOT_MEASURED"




def test_a_promoted_record_carries_no_attempt_report(scene, monkeypatch):
    s = scene
    _def(s["tmp_path"])
    monkeypatch.setattr(p3, "_docker_exec", _native_double(_CENSUS_WITH_SUPPLY_PORTS))
    assert s["emit"]()
    rec = json.loads((s["tmp_path"] / _REC).read_text())
    assert rec["report"] and "attempt_report" not in rec


def test_a_long_unknown_driver_list_states_its_count_and_that_it_was_cut(
        scene, monkeypatch):
    """MINOR (integrity): `_unknown[:8]` read as 'there are 8'."""
    s = scene
    _def(s["tmp_path"])
    names = [f"X{i}" for i in range(12)]
    census = ("STA_LINK_INSTANCE u1 core/INV\n"
              "STA_LINK_CENSUS total=1 linked=1 missing=0\n"
              f"Found {len(names)} unannotated drivers.\n"
              + "".join(f" {n}\n" for n in names)
              + "Found 0 partially unannotated drivers.\n")
    monkeypatch.setattr(p3, "_docker_exec", _native_double(census))
    assert not s["emit"]()
    rec = json.loads((s["tmp_path"] / _REC).read_text())
    assert "12 unclassified unannotated driver(s)" in rec["reason"], rec["reason"]
    assert "+4 more; see " in rec["reason"] and ".population.json" in rec["reason"]
    assert "(+4 more" in rec["corners"]["FF"]["setup"]["annotation_census"]




def test_the_promoted_report_discloses_the_pg_by_name_exclusions(scene, monkeypatch):
    s = scene
    _def(s["tmp_path"])
    monkeypatch.setattr(p3, "_docker_exec", _native_double(_CENSUS_WITH_SUPPLY_PORTS))
    assert s["emit"]()
    head = s["rpt"].read_text().split("===", 1)[0]
    assert "# STA_ANNOTATION_PG_BY_NAME FF: 2 supply port(s)" in head, head
    assert "# STA_ANNOTATION_PG_BY_NAME basis:" in head
