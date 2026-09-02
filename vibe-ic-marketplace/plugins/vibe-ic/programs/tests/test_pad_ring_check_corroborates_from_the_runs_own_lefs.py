#!/usr/bin/env python3
"""Step 15.5ic's GATE had the same two-callers disagreement as its producer —
and its evidence is LEF CONTENT, so it gets a different proof.

THE MEASUREMENT
===============
`flow/phase1_phase2_phase3.yaml` grades step 15.5ic with
`pad_ring_check . --json reports/phase3/padring.json` and no PDK argument;
`phase3_one_shot_runner` dispatches it with `--pdk-root/--pdk`. MEASURED on one
completed chip-path tree (spm, an open 5 V PDK, plugin 1.16.8), same ring, same
disk, back to back: the flow's shape returned FAIL rc=1
`PADRING_MASTERS_UNCORROBORATED`, the runner's returned PASS rc=0. The root is
a per-host, per-container path and the clause is a static string, so nothing
can be written into the yaml to close it.

WHY THIS IS NOT THE PRODUCER'S FIX
==================================
`pad_assignment_gen` could take three VALUES out of the run's own record,
because the run had already read them from a PDK file and published the
file:line. This gate's central claim is different: a declared master must be
shown to be a PDK CELL rather than a drawn shape, and only the LEF's own
contents can show that. So the record is used for one thing only — the LIST OF
FILES this run opened — and those files are re-opened and re-parsed here.

THE FALSIFICATION, which is the point of the module
===================================================
A record is not evidence because it is a record. If the LEFs it names do not
carry every master the ring claims, they corroborate NOTHING, and the fallback
is DECLINED — `PADRING_MASTERS_UNCORROBORATED` stands exactly as it does with
no record at all. It is deliberately not reported as
`PAD_MASTER_NOT_IN_PDK_IO_LIBRARY`: that would be a claim about the PDK, and no
PDK was read.

Chip-agnostic: every master, library and file name below is invented.
"""
from __future__ import annotations

import json
from pathlib import Path

import pad_ring_check as PRC

_MASTERS = ("fixture_io__in_c", "fixture_io__cor", "fixture_io__fill10")


def _lef(masters, size=(10.0, 20.0)) -> str:
    out = ["VERSION 5.8 ;", 'BUSBITCHARS "[]" ;']
    for m in masters:
        out += [f"MACRO {m}", "  CLASS PAD ;",
                f"  SIZE {size[0]} BY {size[1]} ;", f"END {m}"]
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


def _producer(masters=_MASTERS) -> dict:
    """The producer record's own shape: masters live on the PLACED instances."""
    a, corner, fill = masters
    return {
        "schema": "vibe-ic/padring/1", "verdict": "PASS",
        "padring_def": "phase3/stage3/pnr/padring.def",
        "pads": [{"instance": "u_pad_a", "master": a, "side": "S"}],
        "corners": [{"instance": "cor_SW", "master": corner}],
        "fillers": [{"instance": "fill_S_0", "master": fill}],
        "config": {"PAD_CORNER": corner, "PAD_FILLERS": ["a_family_name"]},
    }


def _project(tmp_path: Path, *, lef_masters=_MASTERS, verdict="WROTE",
             write_lef=True, record=True) -> Path:
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    lef = proj / "pdk" / "libs.ref" / "fixture_io" / "lef" / "io.lef"
    lef.parent.mkdir(parents=True)
    if write_lef:
        lef.write_text(_lef(lef_masters))
    ring = proj / "phase3" / "stage3" / "pnr" / "padring.def"
    ring.parent.mkdir(parents=True)
    comps = [("u_pad_a", _MASTERS[0], 100000, 52000),
             ("cor_SW", _MASTERS[1], 52000, 52000),
             ("fill_S_0", _MASTERS[2], 300000, 52000)]
    ring.write_text(
        'VERSION 5.8 ;\nDIVIDERCHAR "/" ;\nBUSBITCHARS "[]" ;\n'
        "DESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 1000000 1000000 ) ;\n"
        f"COMPONENTS {len(comps)} ;\n"
        + "\n".join(f"- {i} {m} + PLACED ( {x} {y} ) N ;"
                     for i, m, x, y in comps)
        + "\nEND COMPONENTS\nEND DESIGN\n")
    if record:
        (proj / PRC.DERIVED_CHIP_TOP_REL).write_text(json.dumps({
            "program": "io_pad_chip_top_gen", "verdict": verdict,
            "io_library_lefs": [str(lef)]}))
    return proj


def test_the_masters_under_audit_are_read_from_the_instances(tmp_path):
    """Not from the config: a filler FAMILY name corroborates no instance."""
    assert PRC.declared_masters(_producer()) == sorted(_MASTERS)
    assert "a_family_name" not in PRC.declared_masters(_producer())


def test_a_record_whose_lefs_carry_every_master_is_adopted(tmp_path):
    proj = _project(tmp_path)
    lefs, decls, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    assert why == ""
    assert [p.name for p in lefs] == ["io.lef"]


def test_a_lef_missing_one_claimed_master_corroborates_nothing(tmp_path):
    """THE FALSIFIER. One master short is not 'mostly corroborated'."""
    proj = _project(tmp_path, lef_masters=_MASTERS[:2])
    lefs, _decls, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    assert lefs == []
    assert _MASTERS[2] in why and "corroborate nothing" in why


def test_the_declined_record_leaves_the_gate_uncorroborated(tmp_path):
    """And it is NOT re-reported as a claim about the PDK."""
    proj = _project(tmp_path, lef_masters=_MASTERS[:2])
    _lefs, _d, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    findings = PRC._audit_ring(proj, _producer(), PRC.PR.IoLibrary([]), why)
    rules = [f["rule"] for f in findings]
    assert "PADRING_MASTERS_UNCORROBORATED" in rules
    assert "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY" not in rules
    message = [f["message"] for f in findings
               if f["rule"] == "PADRING_MASTERS_UNCORROBORATED"][0]
    assert "consulted and declined" in message and _MASTERS[2] in message


def test_an_absent_record_is_declined_by_name(tmp_path):
    proj = _project(tmp_path, record=False)
    lefs, _d, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    assert lefs == [] and PRC.DERIVED_CHIP_TOP_REL in why


def test_a_record_that_wrote_nothing_opened_no_library(tmp_path):
    proj = _project(tmp_path, verdict="REFUSE")
    lefs, _d, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    assert lefs == [] and "REFUSE" in why


def test_a_path_that_is_not_on_this_host_is_declined_not_assumed(tmp_path):
    """The recorded paths are the CONTAINER's. A gate run where they do not
    resolve must say so, not treat the record as if it had read them."""
    proj = _project(tmp_path, write_lef=False)
    lefs, _d, why = PRC.io_lefs_this_run_recorded(proj, _producer())
    assert lefs == [] and "exists on this host" in why


def test_the_fallback_is_last_not_first(tmp_path):
    """An explicit --io-lef and a resolvable PDK both still win: the record is
    consulted only where nothing else answered."""
    src = Path(PRC.__file__).read_text()
    body = src[src.index("lefs = ([Path(p) for p in args.io_lef]"):]
    body = body[:body.index("findings.extend(")]
    assert body.index("if not lefs:") > body.index("discover_io_lefs")


def test_no_pdk_or_vendor_literal_is_baked_into_the_fallback(tmp_path):
    src = Path(PRC.__file__).read_text()
    body = src[src.index("def io_lefs_this_run_recorded"):
               src.index("def main(")]
    for literal in ("gf180", "sky130", "sg13", "/foss", "librelane"):
        assert literal not in body, f"{literal!r} baked into the reader"
