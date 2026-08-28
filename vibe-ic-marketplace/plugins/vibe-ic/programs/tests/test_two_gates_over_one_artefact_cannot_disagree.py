"""test_two_gates_over_one_artefact_cannot_disagree.py — the invariant, and
the two false certifications that were measured on top of the previous round.

WHAT THE PREVIOUS ROUND ESTABLISHED, AND WHERE IT LEAKED
========================================================
The ordering holds at the gate of record and in the consumers wired so far:

    design-bound   >   structure-only (disclosed)   >   undisclosed
                                                    >   invented content

Two measured leaks survived it, and both are FALSE CERTIFICATIONS rather than
gaps in coverage:

(a) TWO GATES OVER ONE ARTEFACT, IN DISAGREEMENT. `flow/phase1_phase2_phase3
    .yaml` declares `analog_pre_vs_post_layout_check` as the gate for the
    post-layout step; `analog_a7_post_layout_resim_check` — the gate the
    A-track runner runs over the SAME `phase3/analog/<block>/pre_vs_post.json`
    — appears ZERO times in that YAML. Measured on three trees identical in
    every artefact except the one recorded `design_content` value:

        analog_pre_vs_post_layout_check    rc 0 / rc 0 / rc 0
        analog_a7_post_layout_resim_check  rc 0 / rc 0 (disclosed) / rc 1

    byte-identical console AND byte-identical `--json` artefact from the
    declared gate on all three. On the silent tree the two disagreed outright,
    and the one the flow declares was the one that could not tell the trees
    apart. The SAME shape held at A8: the flow declares
    `analog_hardmacro_check`, the runner runs `analog_a8_hardmacro_gen_check`,
    and both answered PASS / PASS / PASS over a complete package on which
    `analog_liberty_nonzero_delay_check` answered PASS / PASS_STRUCTURE_ONLY /
    FAIL.

(b) A CHAIN ORDERED NEAREST-FIRST, WHOSE NEAREST LINK IS AI-AUTHORED. A7 read
    `("pre_vs_post.json", "corner_results.json")` in that order, documented as
    "so this gate can never certify a tree its own gate of record refuses".
    Measured with the corner artefact SILENT and the derived artefact carrying
    the design-bound token: the gate of record answered rc 1 FAIL and A7
    answered rc 0 plain PASS with no disclosure sentinel. Nothing
    deterministic writes `design_content` into `pre_vs_post.json` — it is
    authored by an AI skill — so ordering it first put an AI-authored claim
    above the deterministic record. STOPPING at the gate of record's artefact
    is not the same as being BOUNDED by it.

(c) A THIRD LEAK, found on top of (a) and (b), and the reason section 4 no
    longer takes a list. `analog_a3_netlist_gen_check` — the gate the flow
    declares for the A3 step — answered the SAME content question about a THIRD
    artefact with a private `==` against ONE token, so it had a DISCLOSED tier
    and no UNDISCLOSED one. Measured on the same three trees, run verbatim as
    the flow runs it:

        analog_a3_netlist_gen_check   rc 0 / rc 0 (disclosed) / rc 0
        --json sha256                 6c3a3a36 / 7b1d5477 / 6c3a3a36

    design-bound and SILENT byte-identical; the tree that DISCLOSED a library
    default the only one marked down. Silence ranked ABOVE disclosure. The
    invariant in section 4 was supposed to make this impossible and did not,
    because it was parameterised over an ENUMERATED two artefacts and the third
    was never added to the list. It now DERIVES its subjects.

THE RULES UNDER TEST, with no tool, step or block name in them:

    Two gates that certify ONE artefact must not disagree about it. One may
    check more than the other; neither may CERTIFY what the other REFUSES.

    A derived artefact may CONFIRM or LOWER the content its baseline records.
    It may never RAISE it. What a comparison is a comparison OF is decided by
    the thing it is compared against, not by the file reporting the
    comparison.

ORDERING, defended by a control in every section: the certification question
is asked LAST. A tree that is silent AND has a real value defect reports the
VALUE defect — "your post-layout drift is 22 %", "your package has no Verilog
view" — and not the content one. Those name a deeper cause and answer "what
did you measure?" as a side effect; the reverse is not true.

Every assertion here fails on a wrong CERTIFICATION — an rc, a verdict word,
or a written artefact — never on a message string.

Every fixture is synthetic: invented block names, library nominal geometries,
no design content, no PDK SKU, no vendor, no part number.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

PLUGIN = PROGRAMS.parent
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

PVP_DECLARED_GATE = PROGRAMS / "analog_pre_vs_post_layout_check.py"
PVP_STEP_GATE = PROGRAMS / "analog_a7_post_layout_resim_check.py"
A4_GATE_OF_RECORD = PROGRAMS / "analog_a4_corner_sweep_check.py"

HM_DECLARED_GATE = PROGRAMS / "analog_hardmacro_check.py"
HM_STEP_GATE = PROGRAMS / "analog_a8_hardmacro_gen_check.py"
HM_LIBERTY_GATE = PROGRAMS / "analog_liberty_nonzero_delay_check.py"

#: The gate the FLOW declares for the A3 step, and the only program that
#: certifies `phase3/analog/<block>/<block>.sp`. Its SECOND consumer is not a
#: program but `analog_one_shot_runner`, which reads the same producer sidecar
#: through the shared whitelist to write the run record — see section 5.
A3_GATE = PROGRAMS / "analog_a3_netlist_gen_check.py"

#: The gates that certify `phase3/analog/<block>/pre_vs_post.json`. The FLOW
#: declares the first; the A-track runner runs the second.
PVP_GATES = (PVP_DECLARED_GATE, PVP_STEP_GATE)

#: The gates that certify the packaged hardmacro. The FLOW declares the first;
#: the A-track runner runs the second; the third reads the record and grades
#: the `.lib` inside the package the other two sign off.
HM_GATES = (HM_DECLARED_GATE, HM_STEP_GATE, HM_LIBERTY_GATE)

STRUCTURE_ONLY = "structure_only"
SIZED = "structure_and_geometry"

BLOCKS = ("blk_alpha", "blk_beta")


# ═══ the tree, and the ONE field that varies across it ══════════════════════

def _corners(margin_pct: float = 22.5) -> list:
    """A full 27-corner PVT cube, every corner comfortably above the margin
    floor, so nothing in this fixture fails for a VALUE reason and every
    assertion below is about content."""
    return [{"name": f"{p}_{t}c_{v}v", "simulator_run": True,
             "process": p, "temp_c": t, "vdd_v": v, "margin_pct": margin_pct}
            for p in ("ss", "tt", "ff")
            for t in (-40, 27, 125)
            for v in (1.62, 1.80, 1.98)]


_LIB = """library({b}_lib) {{
  cell({b}) {{
    area : 10000 ;
    cell_rise : 0.42 ;
    cell_fall : 0.39 ;
    cell_leakage_power : 0.0031 ;
  }}
}}
"""

_LEF = """VERSION 5.8 ;
BUSBITCHARS "[]" ;
DIVIDERCHAR "/" ;
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MACRO {b}
  CLASS BLOCK ;
  ORIGIN 0 0 ;
  SIZE 20.000 BY 20.000 ;
  SYMMETRY X Y R90 ;
  PIN vdd
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER met1 ;
        RECT 0.000 0.000 2.000 20.000 ;
    END
  END vdd
  PIN vss
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER met1 ;
        RECT 18.000 0.000 20.000 20.000 ;
    END
  END vss
  PIN vin
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 4.000 0.000 4.400 0.400 ;
    END
  END vin
  PIN vout
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER met2 ;
        RECT 14.000 19.600 14.400 20.000 ;
    END
  END vout
END {b}
END LIBRARY
"""

_VLOG = """// {b} — synthetic behavioural view for this fixture.
`timescale 1ns/1ps
module {b} (
  inout  wire vdd,
  inout  wire vss,
  input  wire vin,
  output wire vout
);
  assign vout = vin;
endmodule
"""


# ── a GDS carrying real BOUNDARY records, built here so the fixture needs no
#    binary blob checked in and no PDK of any kind.
#
#: Database unit of the GDS below, in microns. The UNITS record declares
#: (1e-3 user-units-per-db-unit, 1e-9 metres-per-db-unit), so one db unit is
#: one nanometre and 1000 of them are one micron.
_GDS_DBU_PER_UM = 1000
#: The outline the GDS covers, in microns, and it is `_LEF`'s `SIZE` READ BACK
#: rather than a second number that has to be kept equal to it by hand. The
#: fixture's own docstring promises that everything a VALUE rule could catch is
#: clean; `analog_lef_gds_outline_check` is a value rule over exactly this pair,
#: and before this was derived the two numbers were 20 um and 2 um — Δ900 %
#: against a 2 % tolerance, which pinned A8 at FAIL in every variant and hid
#: whatever the variants were supposed to be measuring at that step.
_GDS_OUTLINE_UM = float(
    re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", _LEF).group(1))


def _gds_rec(rtype: int, dtype: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload


def _gds_real8(v: float) -> bytes:
    if v == 0:
        return b"\x00" * 8
    sign, v, exp = (0x80 if v < 0 else 0x00), abs(v), 64
    while v >= 1:
        v /= 16.0
        exp += 1
    while v < 1 / 16.0:
        v *= 16.0
        exp -= 1
    return struct.pack(">B", sign | exp) + int(v * (1 << 56)).to_bytes(7, "big")


def _gds_bytes(cellname: str) -> bytes:
    nm = cellname.encode() + (b"\x00" if len(cellname) % 2 else b"")
    stamp = struct.pack(">12h", *([2026, 8, 1, 0, 0, 0] * 2))
    out = _gds_rec(0x00, 2, struct.pack(">h", 600))
    out += _gds_rec(0x01, 2, stamp)
    out += _gds_rec(0x02, 6, nm)
    out += _gds_rec(0x03, 5, _gds_real8(1e-3) + _gds_real8(1e-9))
    out += _gds_rec(0x05, 2, stamp)
    out += _gds_rec(0x06, 6, nm)
    # Four nested boundaries, the outermost spanning the WHOLE declared
    # outline so the bounding box the outline gate measures is `_LEF`'s own
    # `SIZE`. The inner three keep the original relative geometry; only the
    # scale is derived, so the fixture still exercises "several boundaries on
    # several layers" and no longer trips a value rule while doing it.
    full = round(_GDS_OUTLINE_UM * _GDS_DBU_PER_UM)
    for i, (lay, frac) in enumerate(
            ((66, 1.0), (67, 0.7), (68, 0.45), (69, 0.3))):
        out += _gds_rec(0x08, 0)
        out += _gds_rec(0x0D, 2, struct.pack(">h", lay))
        out += _gds_rec(0x0E, 2, struct.pack(">h", 20))
        w = round(full * frac)
        x0 = y0 = round(full * 0.05) * i
        pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + w), (x0, y0 + w), (x0, y0)]
        out += _gds_rec(0x10, 3,
                        b"".join(struct.pack(">ii", a, b) for a, b in pts))
        out += _gds_rec(0x11, 0)
    out += _gds_rec(0x07, 0)
    out += _gds_rec(0x04, 0)
    return out


def _project(root: Path, design_content, derived_content=None,
             blocks=BLOCKS, drift_pct: float = 1.0,
             hardmacro: bool = True, netlist_bytes: int = 0) -> Path:
    """A complete analog tree carrying every artefact these gates read.

    `design_content`  — what the CORNER artefact (the gate of record's own
                        subject) records. `None` builds the pre-disclosure
                        shape BY DELETION: the whole disclosure set goes, which
                        is what an artefact written before the fields existed
                        looks like, and what a stale one looks like.
    `derived_content` — what `pre_vs_post.json` records about ITSELF. `None`
                        is the shape every deterministic producer actually
                        writes: nothing. Anything else is the AI-authored
                        claim, which is the whole subject of section 2.

    Everything a VALUE rule could catch is deliberately clean: 27 corners at
    22.5 % margin, a non-degenerate Liberty, a GDS with four BOUNDARY records,
    a LEF with MACRO+PIN, a Verilog with a module, and a post-layout drift of
    1 %. So no assertion below can be satisfied by a gate failing for some
    other reason.
    """
    adir = root / "phase3" / "analog"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": b, "type": "ldo"} for b in blocks]}, indent=2))
    for b in blocks:
        d = adir / b
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps({"block": b, "specs": []}))
        (d / "topology.md").write_text("# topology\nlibrary topology\n")
        # `netlist_bytes` pads the deck past A3's 200-byte substance floor.
        # The DEFAULT is deliberately below it: at 193 bytes this deck is the
        # thin tree A3's own value rule owns, and section 5's ordering control
        # depends on it staying that way.
        head = (f"* {b} — synthetic block netlist for this fixture\n"
                f"* every geometry below is a library nominal, on purpose\n")
        body = (f".subckt {b} vdd vss vin vout\n"
                f"xm1 vout vin vss vss nch w=8 l=1\n"
                f".ends {b}\n")
        while len((head + body).encode()) < netlist_bytes:
            head += "* synthetic fixture padding\n"
        (d / f"{b}.sp").write_text(head + body)
        if design_content is not None:
            (d / "netlist_provenance.json").write_text(json.dumps({
                "block": b,
                "_provenance": {"producer": "synthetic-fixture",
                                "design_content": design_content,
                                "spec_bound_params": [],
                                "library_nominal_params": ["m1.w"]}},
                indent=2))
        corners = _corners()
        doc = {
            "block": b, "_provenance": "real_ngspice",
            "simulator": "ngspice (docker)",
            "corners_executed": len(corners),
            "full_pvt_sweep_executed": True,
            "total_corners": len(corners),
            "corners": corners,
            "spec_results": [{"name": "vout", "status": "PASS"}],
        }
        if design_content is not None:
            doc["netlist_provenance"] = "a3_netlist"
            doc["netlist_source"] = f"phase3/analog/{b}/{b}.sp"
            doc["design_traceable"] = True
            doc["design_content"] = design_content
            doc["design_content_meaning"] = "see the producer record"
        (d / "corner_results.json").write_text(json.dumps(doc, indent=2))

        post = round(1.80 * (1.0 - drift_pct / 100.0), 6)
        pvp = {"block": b,
               "specs": [{"name": "vout", "pre_value": 1.80,
                          "post_value": post},
                         {"name": "iq", "pre_value": 20.0,
                          "post_value": 20.2}]}
        if derived_content is not None:
            pvp["design_content"] = derived_content
        (d / "pre_vs_post.json").write_text(json.dumps(pvp, indent=2))

        if hardmacro:
            hm = adir / "hardmacro" / b
            hm.mkdir(parents=True, exist_ok=True)
            lib = _LIB.format(b=b)
            while len(lib.encode()) < 260:      # clear the A8 200B floor
                lib += "/* synthetic fixture padding */\n"
            (hm / f"{b}.lib").write_text(lib)
            (hm / f"{b}.lef").write_text(_LEF.format(b=b))
            (hm / f"{b}.v").write_text(_VLOG.format(b=b))
            (hm / f"{b}.gds").write_bytes(_gds_bytes(b))
    return root


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True)


def _both(cp) -> str:
    return (cp.stdout or "") + (cp.stderr or "")


# ═══ the ONE reading of "what did this gate certify?" ═══════════════════════
# Read from the gate's OWN verdict — its exit code and the verdict word it
# prints — never from prose. Three answers, and they are the same three
# everywhere.
CERTIFIED_BOUND = "CERTIFIED_DESIGN_BOUND"
CERTIFIED_SO = "CERTIFIED_STRUCTURE_ONLY"
REFUSED = "REFUSED"
EXAMINED_NOTHING = "EXAMINED_NOTHING"


def _tier(cp) -> str:
    if cp.returncode == 2:
        return EXAMINED_NOTHING
    if cp.returncode != 0:
        return REFUSED
    out = _both(cp)
    if "STRUCTURE_ONLY:" in out or "PASS_STRUCTURE_ONLY" in out:
        return CERTIFIED_SO
    return CERTIFIED_BOUND


def _tiers(prog: Path, tmp_path: Path, tag: str, **kw) -> dict:
    """The tier *prog* reaches on each of the three trees."""
    return {
        "bound": _tier(_run(prog, _project(tmp_path / f"{tag}_d", SIZED,
                                           **kw))),
        "structure_only": _tier(
            _run(prog, _project(tmp_path / f"{tag}_s", STRUCTURE_ONLY, **kw))),
        "silent": _tier(_run(prog, _project(tmp_path / f"{tag}_n", None,
                                            **kw))),
    }


# ═══ 1. (a) THE GATE THE FLOW DECLARES FOR THE POST-LAYOUT STEP ════════════

def test_the_flow_declared_pre_vs_post_gate_names_what_it_compared(tmp_path):
    """THE HEADLINE for (a). Pre-fix this gate answered rc 0 on all three
    trees with a byte-identical console and a byte-identical `--json`
    artefact — it is the gate the FLOW runs for this step, so that
    certification is what the flow record inherits."""
    bound = _run(PVP_DECLARED_GATE, _project(tmp_path / "d", SIZED))
    so = _run(PVP_DECLARED_GATE, _project(tmp_path / "s", STRUCTURE_ONLY))
    silent = _run(PVP_DECLARED_GATE, _project(tmp_path / "n", None))

    assert bound.returncode == 0, _both(bound)
    assert "[PASS]" in bound.stdout, bound.stdout

    assert so.returncode == 0, _both(so)
    assert "[PASS_STRUCTURE_ONLY]" in so.stdout, (
        f"a pre/post comparison OF A LIBRARY TOPOLOGY was certified by the "
        f"step's DECLARED gate in the same tier as a design's:\n{so.stdout}")
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"the step's DECLARED gate certified (rc={silent.returncode}) a "
        f"comparison with nothing anywhere saying what circuit was compared")
    assert "PRE_VS_POST_DESIGN_CONTENT_UNDECLARED" in _both(silent)


def test_the_declared_gate_and_the_step_gate_agree_on_every_tree(tmp_path):
    """THE INVARIANT ITSELF, and the one assertion that would have caught this
    round without an adversarial reading of the YAML: no gate over this
    artefact may CERTIFY a tree another REFUSES.

    Pre-fix the declared gate certified all three while the step gate refused
    the silent one — two gates over one artefact, in disagreement."""
    per_gate = {g.name: _tiers(g, tmp_path, g.stem[:12]) for g in PVP_GATES}
    for tree in ("bound", "structure_only", "silent"):
        answers = {name: t[tree] for name, t in per_gate.items()}
        assert len(set(answers.values())) == 1, (
            f"two gates over ONE artefact disagree about the {tree!r} tree: "
            f"{answers}")


def test_the_declared_gate_writes_a_different_artefact_for_a_different_tree(
        tmp_path):
    """The FLOW runs this gate as `... --json reports/phase2/gates/
    pre_vs_post.json`, and that document is what a machine consumer reads.
    Pre-fix its sha256 was IDENTICAL on all three trees, so no consumer
    downstream of the flow could tell them apart either."""
    shas = {}
    for tag, dc in (("d", SIZED), ("s", STRUCTURE_ONLY), ("n", None)):
        project = _project(tmp_path / tag, dc)
        out = tmp_path / f"{tag}.json"
        _run(PVP_DECLARED_GATE, project, "--json", str(out))
        shas[tag] = hashlib.sha256(out.read_bytes()).hexdigest()
    assert len(set(shas.values())) == 3, (
        f"the artefact the FLOW writes for this step does not distinguish a "
        f"design-bound run, a disclosed library default and a silent one: "
        f"{shas}")


def test_the_disclosure_survives_the_way_the_flow_actually_runs_this_gate(
        tmp_path):
    """A disclosure printed only on the console path is a disclosure the flow
    auditor never sees — and `--json` is the ONLY path the flow ever takes for
    this gate. `flow_compliance_check._stdout_signals_structure_only` reads the
    line-start token out of the concatenated streams."""
    project = _project(tmp_path, STRUCTURE_ONLY)
    cp = _run(PVP_DECLARED_GATE, project, "--json",
              str(tmp_path / "r.json"))
    assert cp.returncode == 0, _both(cp)
    assert any(l.lstrip().startswith("STRUCTURE_ONLY:")
               for l in _both(cp).splitlines()), (
        f"run the way the flow runs it, the gate disclosed nothing:\n"
        f"{_both(cp)!r}")


def test_a_severe_degradation_is_still_a_severe_degradation(tmp_path):
    """ORDERING CONTROL. The defect this gate exists for — post-layout specs
    degrading past the floor — is diagnosed as itself even on a tree that also
    says nothing about what was compared. Holds pre-fix and post-fix."""
    cp = _run(PVP_DECLARED_GATE, _project(tmp_path, None, drift_pct=45.0))
    assert cp.returncode == 1
    out = _both(cp)
    assert "LAYOUT_SEVERE_DEGRADATION" in out, out
    assert "PRE_VS_POST_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_zero_comparable_specs_is_still_zero_comparable_specs(tmp_path):
    """ORDERING CONTROL, the other one this gate owns: a comparison gate with
    items_compared == 0 must FAIL as that, not as a content failure. Holds
    pre-fix and post-fix."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        (root / "phase3" / "analog" / b / "pre_vs_post.json").write_text(
            json.dumps({"block": b, "comparison": {"vout": "ok"}}))
    cp = _run(PVP_DECLARED_GATE, root)
    assert cp.returncode == 1
    out = _both(cp)
    assert "PRE_VS_POST_ZERO_COMPARED" in out, out
    assert "PRE_VS_POST_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_the_gate_the_flow_declares_is_one_of_the_gates_verified_to_agree():
    """THE GUARD AGAINST THE NEXT DIVERGENCE, and the reason this round did
    not simply re-point the YAML.

    The invariant above is only worth what its MEMBERSHIP is worth: it
    compares the gates in `PVP_GATES`. If a future round re-points the step's
    declaration at a third program, or adds a second `program_exit_zero`
    clause to the step, that program is outside the set and its agreement was
    never measured. This reddens then, instead of an adversarial round
    rediscovering it by hand.
    """
    declared = _declared_programs("A7")
    assert declared, (
        f"no `program_exit_zero` clause found in the A7 step of {FLOW_YAML}")
    known = {g.stem for g in PVP_GATES}
    assert set(declared) <= known, (
        f"the flow declares {sorted(set(declared) - known)} for the "
        f"post-layout step, and no test measures whether it agrees with "
        f"{sorted(known)} about `pre_vs_post.json`")


# ═══ 2. (b) A DERIVED ARTEFACT CANNOT CERTIFY ABOVE ITS BASELINE ═══════════

def test_a_derived_artefact_cannot_certify_what_the_gate_of_record_refuses(
        tmp_path):
    """THE HEADLINE for (b). The corner artefact — the gate of record's own
    subject — is SILENT; the derived artefact carries the design-bound token
    that no deterministic producer writes into it.

    Pre-fix: the gate of record answered rc 1 FAIL and A7 answered rc 0 PLAIN
    PASS, with no disclosure sentinel, on the same block."""
    project = _project(tmp_path, None, derived_content=SIZED)

    record = _run(A4_GATE_OF_RECORD, project)
    assert record.returncode == 1, (
        f"fixture is not exercising the case: the gate of record accepted the "
        f"silent corner artefact (rc={record.returncode})")

    got = {g.stem: _tier(_run(g, project)) for g in PVP_GATES}
    assert got == {g.stem: REFUSED for g in PVP_GATES}, (
        f"a gate certified a tree its own gate of record refuses (which "
        f"answered REFUSED), on a `design_content` token written only into "
        f"the artefact an AI skill authors: {got}")


def test_a_derived_claim_cannot_upgrade_a_disclosed_default(tmp_path):
    """The subtler half of the same bug, and the one a re-ordering of the
    chain would still have missed: the baseline discloses a LIBRARY DEFAULT
    and the derived artefact claims design-bound. The comparison cannot be
    more design-bound than the pre-layout result it is compared against.

    Pre-fix: a bare design-bound PASS, no sentinel."""
    project = _project(tmp_path, STRUCTURE_ONLY, derived_content=SIZED)
    got = {g.stem: _tier(_run(g, project)) for g in PVP_GATES}
    assert got == {g.stem: CERTIFIED_SO for g in PVP_GATES}, (
        f"a gate certified a comparison as this design's on a claim the "
        f"artefact made about ITSELF, over a baseline that discloses a "
        f"library default: {got}")


def test_a_derived_artefact_may_still_disclose_something_weaker(tmp_path):
    """NEGATIVE CONTROL on the ceiling: it is a CEILING, not a lock. A
    producer disclosing something weaker than its baseline entitled it to
    claim still certifies, in the disclosed tier. Refusing that would make
    honesty cost again, which is the inversion one level up.

    Holds pre-fix for the STEP gate — nearest-first already read the derived
    record — and fails pre-fix for the DECLARED gate, which had no content
    rule at all and certified it as design-bound."""
    project = _project(tmp_path, SIZED, derived_content=STRUCTURE_ONLY)
    got = {g.stem: _tier(_run(g, project)) for g in PVP_GATES}
    assert got == {g.stem: CERTIFIED_SO for g in PVP_GATES}, (
        f"a gate did not certify a self-disclosed library default in its own "
        f"tier: {got}")


def test_a_drift_over_budget_is_still_a_drift_failure_on_a_capped_tree(
        tmp_path):
    """ORDERING CONTROL for section 2. A comparison whose drift blows the
    budget is diagnosed as THAT, even when its own record also over-claims
    against a silent baseline. Holds pre-fix and post-fix."""
    project = _project(tmp_path, None, derived_content=SIZED, drift_pct=45.0)
    cp = _run(PVP_STEP_GATE, project)
    assert cp.returncode == 1
    out = _both(cp)
    assert "A7_POSTSIM_DELTA_TOO_BIG" in out, out
    assert "A7_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_the_run_record_cannot_claim_a_content_the_step_did_not_reach(
        tmp_path):
    """THE SAME BUG ONE LAYER DOWN. `analog_one_shot_runner._CONTENT_SOURCES`
    reads the SAME two artefacts in the SAME nearest-first order, so the run
    record inherited the same inversion independently of the gate.

    Pre-fix, on a baseline that discloses a library default and a derived
    artefact claiming design-bound: the runner recorded status
    PASS_STRUCTURE_ONLY (it read the gate's sentinel) beside
    `design_content: structure_and_geometry` and `structure_only: False` — a
    run record contradicting itself in two adjacent fields.
    """
    import analog_one_shot_runner as R

    project = _project(tmp_path, STRUCTURE_ONLY, derived_content=SIZED,
                       blocks=("blk_alpha",))
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A7_post_layout_resim")
    assert res.status == "PASS_STRUCTURE_ONLY", (res.status, res.detail)
    assert res.extras.get("design_content") == STRUCTURE_ONLY, res.extras
    assert res.extras.get("structure_only") is True, res.extras
    assert (res.extras.get("design_content_source") or "").endswith(
        "corner_results.json"), res.extras


def test_the_run_record_still_names_a_design_bound_step(tmp_path):
    """NEGATIVE CONTROL on the cap in the run record: a genuinely design-bound
    step still records design-bound, from the baseline, as a plain PASS."""
    import analog_one_shot_runner as R

    project = _project(tmp_path, SIZED, blocks=("blk_alpha",))
    res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                           "A7_post_layout_resim")
    assert res.status == "PASS", (res.status, res.detail)
    assert res.extras.get("design_content") == SIZED, res.extras
    assert res.extras.get("structure_only") is False, res.extras


# ═══ 3. THE A8 PAIR — THREE GATES OVER ONE PACKAGE ═════════════════════════

def test_the_flow_declared_hardmacro_gate_names_what_the_package_models(
        tmp_path):
    """The hardmacro is what digital PnR INSTANTIATES and what integration STA
    CLOSES ON. Pre-fix the gate the FLOW declares for A8 answered rc 0 on all
    three trees over a COMPLETE package (.gds + .lef + .lib + .v) — the
    finding does not reproduce on a `.lib`-only fixture, where both A8 gates
    exit 1 on the missing deliverables first and the disagreement is masked."""
    bound = _run(HM_DECLARED_GATE, _project(tmp_path / "d", SIZED))
    so = _run(HM_DECLARED_GATE, _project(tmp_path / "s", STRUCTURE_ONLY))
    silent = _run(HM_DECLARED_GATE, _project(tmp_path / "n", None))

    assert bound.returncode == 0, _both(bound)
    assert "[PASS]" in bound.stdout, bound.stdout

    assert so.returncode == 0, _both(so)
    assert "[PASS_STRUCTURE_ONLY]" in so.stdout, (
        f"a hardmacro MODELLING A LIBRARY TOPOLOGY was signed off for "
        f"floorplan and STA in the same tier as a designed macro:\n{so.stdout}")
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"the package digital PnR instantiates was signed off "
        f"(rc={silent.returncode}) with nothing saying what it models")
    assert "HARDMACRO_SUBJECT_UNDECLARED" in _both(silent)


def test_the_a8_step_gate_names_what_the_package_models(tmp_path):
    """The same, for the gate the A-track RUNNER runs for this step."""
    bound = _run(HM_STEP_GATE, _project(tmp_path / "d", SIZED))
    so = _run(HM_STEP_GATE, _project(tmp_path / "s", STRUCTURE_ONLY))
    silent = _run(HM_STEP_GATE, _project(tmp_path / "n", None))

    assert bound.returncode == 0, _both(bound)
    assert bound.stdout.startswith("PASS:"), bound.stdout

    assert so.returncode == 0, _both(so)
    assert "PASS_STRUCTURE_ONLY:" in so.stdout, so.stdout
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"the A8 step gate certified (rc={silent.returncode}) a package with "
        f"nothing saying what it models")
    assert "A8_DESIGN_CONTENT_UNDECLARED" in _both(silent)


def test_three_gates_over_one_hardmacro_agree_on_every_tree(tmp_path):
    """THE INVARIANT, applied to the package. Pre-fix the two gates that
    answer for the STEP certified all three trees while the gate that reads
    the record refused the silent one."""
    per_gate = {g.name: _tiers(g, tmp_path, g.stem[:14]) for g in HM_GATES}
    for tree in ("bound", "structure_only", "silent"):
        answers = {name: t[tree] for name, t in per_gate.items()}
        assert len(set(answers.values())) == 1, (
            f"gates over ONE hardmacro package disagree about the {tree!r} "
            f"tree: {answers}")


def test_an_incomplete_package_is_still_an_incomplete_package(tmp_path):
    """ORDERING CONTROL for section 3. A declared block with no behavioural
    view is a macro the floorplan and STA cannot consume, and THAT is the
    finding — even on a tree that also says nothing about its subject. Holds
    pre-fix and post-fix."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        (root / "phase3" / "analog" / "hardmacro" / b / f"{b}.v").unlink()
    for gate, value_rule, content_rule in (
            (HM_DECLARED_GATE, "HARDMACRO_INCOMPLETE",
             "HARDMACRO_SUBJECT_UNDECLARED"),
            (HM_STEP_GATE, "A8_HARDMACRO_V_MISSING",
             "A8_DESIGN_CONTENT_UNDECLARED")):
        cp = _run(gate, root)
        assert cp.returncode == 1, _both(cp)
        out = _both(cp)
        assert value_rule in out, out
        assert content_rule not in out, out


def test_a_deterministic_stub_hardmacro_still_passes_in_its_own_tier(tmp_path):
    """NEGATIVE CONTROL. A stub marker is ITSELF a disclosure of what the
    package is, and PASS_WITH_STUB is its own already-disclosed tier — the
    content question must not reach it and turn a disclosed stub red. Holds
    pre-fix and post-fix."""
    root = _project(tmp_path, None)
    for b in BLOCKS:
        hm = root / "phase3" / "analog" / "hardmacro" / b
        (hm / f"{b}.gds").unlink()
        (hm / f"{b}.v").write_text(
            f"// extraction_strategy=deterministic_stub\n"
            f"module {b} (input wire vin, output wire vout);\n"
            f"  assign vout = vin;\nendmodule\n")
    cp = _run(HM_DECLARED_GATE, root)
    assert cp.returncode == 0, (
        f"a DISCLOSED deterministic stub lost its own tier "
        f"(rc={cp.returncode}):\n{_both(cp)}")
    assert "HARDMACRO_SUBJECT_UNDECLARED" not in _both(cp), _both(cp)


# ═══ 4. THE SHARED SITE — one rule per artefact, not one per gate ══════════

def _step(step_id: str) -> dict:
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    for step in doc.get("steps") or []:
        if isinstance(step, dict) and step.get("id") == step_id:
            return step
    return {}


def _gate_combinator(step_id: str) -> str:
    """`all_of` (conjunction) or `any_of` (disjunction) — which one a step's
    gate uses decides whether a lenient clause can certify the step alone."""
    gate = _step(step_id).get("gate") or {}
    for key in ("all_of", "any_of"):
        if key in gate:
            return key
    return ""


def _declared_programs(step_id: str) -> list:
    """Every program named by a `program_exit_zero` clause in *step_id*'s gate.

    Read out of the flow YAML itself, not out of a list kept beside it: a list
    kept beside it is exactly how the declaration and the runner drifted apart
    in the first place.
    """
    gate = _step(step_id).get("gate") or {}
    clauses = gate.get("all_of") or gate.get("any_of") or []
    return [str(c["program_exit_zero"]).split()[0] for c in clauses
            if isinstance(c, dict) and "program_exit_zero" in c]


def test_the_gate_the_flow_declares_for_a8_is_verified_to_agree_too():
    """The same guard as section 1's, for the package.

    A8's gate declares a SECOND clause, `analog_lef_gds_outline_check` — the
    numeric LEF-`SIZE`-vs-GDS-bounding-box half. It does not answer the content
    question and is NOT asked to, for a reason that is structural rather than a
    judgement call: the step's gate is an `all_of`, so the step's verdict is
    the CONJUNCTION of its clauses, and a clause can only ever make the step
    stricter. A more lenient sibling in an `all_of` cannot certify what a
    stricter one refuses. It is named here so that stays a recorded decision
    rather than an omission nobody re-checks — and so that a future round which
    moves it into an `any_of`, where the reasoning inverts, has to come past
    this test.
    """
    declared = _declared_programs("A8")
    assert declared, (
        f"no `program_exit_zero` clause found in the A8 step of {FLOW_YAML}")
    known = {g.stem for g in HM_GATES} | {"analog_lef_gds_outline_check"}
    assert set(declared) <= known, (
        f"the flow declares {sorted(set(declared) - known)} for the hardmacro "
        f"step, and no test measures whether it agrees with {sorted(known)} "
        f"about the package")
    # ...and the conjunction the allowance above rests on, asserted rather
    # than assumed. Under `any_of` a single lenient clause would certify the
    # step on its own and the reasoning inverts.
    assert _gate_combinator("A8") == "all_of", (
        f"the A8 gate is no longer a conjunction, so a clause that does not "
        f"ask the content question can now certify the step by itself")


def test_this_fixtures_package_does_not_trip_the_numeric_clause(tmp_path):
    """THE BUILDER'S OWN PROMISE, ENFORCED — `_project`'s docstring says
    everything a VALUE rule could catch is deliberately clean, and for one
    value rule it was not.

    `analog_lef_gds_outline_check` compares `_LEF`'s `SIZE` against the
    bounding box of `_gds_bytes`' BOUNDARY records to a 2 % tolerance. The two
    numbers were written independently — 20 um and 2 um — so the clause failed
    at Δ900 % on EVERY tree this builder makes. A8 was therefore pinned at
    FAIL in all four content variants, and the step-level differential the
    variants exist to expose (`PASS / STRUCTURE-ONLY / PASS / PASS` across
    design-bound / disclosed / silent / silent — silence outranking disclosure
    at the step level) was invisible underneath it.

    A fixture that fails a gate for a reason no test is about does not merely
    waste the gate: it SILENCES every measurement taken over that step. The
    outline is now derived from `_LEF` rather than written twice, and this
    pins it, because the next reader of that GDS builder has no other way to
    find out the two numbers are load-bearing on each other.
    """
    cp = _run(PROGRAMS / "analog_lef_gds_outline_check.py",
              _project(tmp_path, SIZED))
    assert cp.returncode == 0, (
        f"the shared builder's hardmacro fails the numeric A8 clause "
        f"(rc={cp.returncode}) — every variant measured over A8 is pinned by "
        f"a fixture defect rather than by the content value under test:\n"
        f"{cp.stdout}{cp.stderr}")


#: Every answer an artefact can give, including the three ways of declining.
#: `None` is the field absent — the pre-disclosure and stale shape; `""` is
#: present and empty; `"undeclared"` is a producer's honest statement that the
#: upstream shipped no record, which is a non-empty string and so satisfies any
#: rule keyed on "is the field present?" — that is how silence comes back under
#: a new name.
_ANSWERS = (None, "", "undeclared", STRUCTURE_ONLY, SIZED, "__ABSENT_FILE__")


def _write_answer(path: Path, answer) -> None:
    if answer == "__ABSENT_FILE__":
        if path.exists():
            path.unlink()
        return
    path.write_text(json.dumps({} if answer is None
                               else {"design_content": answer}))


def test_the_ceiling_holds_for_every_pair_of_answers(tmp_path):
    """ENUMERATED, not sampled: all 36 (baseline, derived) pairs.

    The property, stated once and checked everywhere: the answer a derived
    artefact may certify at is never RANKED ABOVE what its baseline supports.
    A sampled test would have passed the pre-fix code on 30 of these 36 cells;
    the six it fails are the whole bug.
    """
    import _analog_a_check_common as _acc

    rank = _acc.content_rank
    violations = []
    for baseline in _ANSWERS:
        for derived in _ANSWERS:
            _write_answer(tmp_path / "corner_results.json", baseline)
            _write_answer(tmp_path / "pre_vs_post.json", derived)
            got = _acc.pre_vs_post_content(tmp_path)
            ceiling = _acc.classify_design_content(
                baseline if baseline not in (None, "__ABSENT_FILE__") else None)
            if rank(got.klass) > rank(ceiling):
                violations.append((baseline, derived, got.klass, ceiling))
    assert not violations, (
        f"a derived artefact certified ABOVE what its baseline supports "
        f"(baseline, derived, certified_at, ceiling): {violations}")


def test_the_ceiling_is_a_ceiling_and_not_a_lock(tmp_path):
    """The other direction of the same property, so the test above cannot be
    satisfied by a rule that simply ignores the derived artefact: a derived
    record that discloses something WEAKER than its baseline entitled it to
    claim is honoured."""
    import _analog_a_check_common as _acc

    _write_answer(tmp_path / "corner_results.json", SIZED)
    _write_answer(tmp_path / "pre_vs_post.json", STRUCTURE_ONLY)
    got = _acc.pre_vs_post_content(tmp_path)
    assert got.klass == _acc.CONTENT_STRUCTURE_ONLY, got
    assert got.refused is None, got


# ── WHY THIS TEST NO LONGER TAKES A LIST OF SUBJECTS ─────────────────────
# It used to be parameterised over an ENUMERATED two artefacts —
# `pre_vs_post.json` and the hardmacro package — with the docstring "it is the
# cheapest thing that reddens when the next gate is added with its own copy".
# It was not. `analog_a3_netlist_gen_check` answered the same question about a
# THIRD artefact with a private `==` against one token, in the same round that
# claimed the class closed, and this test stayed green because the A3 netlist
# was never in the list. AN ENUMERATION YOU MUST REMEMBER TO EXTEND IS NOT AN
# INVARIANT: it is a record of what somebody remembered last time.
#
# So the subjects are DERIVED from the tree. Whatever asks the question is a
# subject, the day it is written, without anyone adding it anywhere.
#
# WHAT IT COVERS, stated plainly so the coverage is reviewable and not assumed:
#
#   (A) MEMBERSHIP, derived: every non-test program under `programs/` whose
#       source mentions the record's field name. Nothing is listed here; the
#       set is whatever the tree contains.
#   (B) THE SHARED SURFACE, derived: the public callables in
#       `_analog_a_check_common` that answer the content question, found by
#       introspection. A new helper joins the surface by existing.
#   (C) THE OBLIGATION, two clauses:
#         A. a subject must REFERENCE the shared surface at all;
#         B. no subject may COMPARE against the producer's raw tokens — the
#            string literals, or a `DESIGN_CONTENT_*` constant holding one.
#            That is the exact shape of every divergence measured so far, and
#            it is per-SITE rather than per-file.
#
# WHAT IT DOES NOT COVER, and these are real holes, not caveats:
#
#   * A file that references the surface ONCE and still answers privately
#     somewhere else with `raw == CONTENT_STRUCTURE_ONLY`. The class constant
#     and the raw token are the SAME STRING, so clause B — which keys on the
#     NAME — cannot tell that compare from a legitimate one on a classifier's
#     output. Clause A catches it only if the file calls nothing shared at all.
#   * A gate that reaches the record through a key path built at runtime and
#     never spells the field name as a literal: clause A's membership scan
#     would not see it.
#   * A gate that copies the record into a DIFFERENTLY NAMED field and grades
#     that. Nothing here can see a rename.
#
# The two named checks the enumerated version made — that a specific helper
# exists and that specific gates call it — survive below as
# `test_the_named_per_artefact_rules_are_the_ones_the_gates_call`, which is a
# specialisation of this, not the invariant.

#: Programs are the subjects; their tests are not (a test naming the field is
#: describing the rule, not answering it).
def _subject_programs() -> list:
    """Every non-test program under `programs/` that touches the record.

    DERIVED, not listed. `_analog_a_check_common` is excluded because it IS the
    shared site — the one file where the producer's raw tokens are translated
    into the class the consumers rank on."""
    import _analog_a_check_common as _acc
    field = _acc.DESIGN_CONTENT_FIELD
    out = []
    for p in sorted(PROGRAMS.glob("*.py")):
        if p.name == "_analog_a_check_common.py":
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:                                 # pragma: no cover
            continue
        if field in src:
            out.append(p)
    return out


def _shared_surface() -> set:
    """The public names in `_analog_a_check_common` that ANSWER the content
    question, found by introspection so a new helper joins by existing."""
    import _analog_a_check_common as _acc
    return {n for n in dir(_acc)
            if not n.startswith("_") and callable(getattr(_acc, n))
            and (n.startswith("content_") or n.endswith("_content"))}


def _raw_token_names() -> tuple:
    """`(constant names, string literals)` of the PRODUCER's vocabulary.

    Derived from the shared module: a `DESIGN_CONTENT_*` constant whose value is
    a disclosed token, or the whitelist itself. The CLASS vocabulary
    (`CONTENT_*`) is deliberately not here — comparing a classifier's OUTPUT
    against it is the correct shape."""
    import _analog_a_check_common as _acc
    disclosed = _acc.DESIGN_CONTENT_DISCLOSED
    names = {n for n in dir(_acc) if n.startswith("DESIGN_CONTENT_")
             and (getattr(_acc, n) in disclosed
                  or getattr(_acc, n) == disclosed)}
    return names, set(disclosed)


def _names_in(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _raw_token_compares(tree, names: set, literals: set) -> list:
    """Every `Compare` whose operands include a raw producer token — directly,
    or inside a tuple/list an `in` test is run against."""
    hits = []

    def _flat(node):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for e in node.elts:
                yield from _flat(e)
        else:
            yield node

    for n in ast.walk(tree):
        if not isinstance(n, ast.Compare):
            continue
        for operand in [n.left] + list(n.comparators):
            for o in _flat(operand):
                nm = (o.id if isinstance(o, ast.Name)
                      else o.attr if isinstance(o, ast.Attribute) else None)
                if nm in names:
                    hits.append((n.lineno, nm))
                    break
                if isinstance(o, ast.Constant) and o.value in literals:
                    hits.append((n.lineno, repr(o.value)))
                    break
    return hits


def test_one_rule_per_artefact_not_one_per_gate():
    """THE INVARIANT, with its subjects DERIVED from the tree.

    Clause A: every program that touches the record must reach the shared
    surface. A program that mentions the field and references nothing shared is
    answering the content question privately, whatever else it does — which is
    literally what `analog_a3_netlist_gen_check` was doing when
    `grep -c 'classify_design_content\\|content_class' ` over it returned 0.
    """
    surface = _shared_surface()
    assert surface, "the shared content surface is empty — nothing to route to"
    offenders = {}
    for p in _subject_programs():
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        if not (_names_in(tree) & surface):
            offenders[p.name] = "references no shared content rule"
    assert not offenders, (
        f"program(s) answer the design-content question without going through "
        f"`_analog_a_check_common` — a private copy is how two consumers over "
        f"one artefact came to disagree: {offenders}. The shared surface is "
        f"{sorted(surface)}.")


def test_no_consumer_compares_against_the_producers_raw_token():
    """Clause B, and it is the one that would have caught THIS round.

    A consumer compares the CLASS `classify_design_content` returns. Comparing
    against the raw token the producer writes is a second answer to the shared
    question, and it is how a gate ended up with a DISCLOSED tier and no
    UNDISCLOSED one: `(_sidecar(project, b) or {}).get("design_content") ==
    DESIGN_CONTENT_STRUCTURE_ONLY` names one of three answers and silently
    merges the other two.
    """
    names, literals = _raw_token_names()
    assert names and literals, "the producer vocabulary derived empty"
    offenders = {}
    for p in _subject_programs():
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        hits = _raw_token_compares(tree, names, literals)
        if hits:
            offenders[p.name] = hits
    assert not offenders, (
        f"a consumer compares against the PRODUCER's raw design-content token "
        f"instead of the class the shared classifier returns "
        f"(file -> [(line, token)]): {offenders}")


@pytest.mark.parametrize("artefact,gates,helper", [
    ("pre_vs_post.json", PVP_GATES, "pre_vs_post_content"),
    ("hardmacro package", HM_GATES, "hardmacro_content"),
    ("<block>.sp", (A3_GATE,), "netlist_content"),
])
def test_the_named_per_artefact_rules_are_the_ones_the_gates_call(
        artefact, gates, helper):
    """The SPECIALISATION, kept because it says something the derived invariant
    cannot: that the gates over ONE artefact reach the shared surface at the
    helper written FOR that artefact, not merely somewhere on it. It is no
    longer the invariant, and it is no longer where a new artefact has to be
    remembered — the two tests above cover a new one the day it appears."""
    import _analog_a_check_common as _acc
    assert hasattr(_acc, helper), (
        f"the shared rule for {artefact} does not exist at a shared site")
    for g in gates:
        src = g.read_text(encoding="utf-8")
        assert helper in src, (
            f"{g.name} certifies {artefact} without going through the shared "
            f"rule `_analog_a_check_common.{helper}` — a private copy is how "
            f"two gates over one artefact came to disagree")


# ═══ 5. THE A3 NETLIST — the artefact the enumeration above never covered ═══
# THE MEASUREMENT, run verbatim as `flow/phase1_phase2_phase3.yaml` runs this
# gate (`analog_a3_netlist_gen_check . --json reports/analog/a3_netlist.json`)
# on a completed benchmark tree carrying GDS/LEF/Liberty/DRC/LVS:
#
#   design-bound    rc=0  PASS: ... 2/2 block(s) clean   --json 6c3a3a36e0d812b0
#   silent          rc=0  PASS: ... 2/2 block(s) clean   --json 6c3a3a36e0d812b0
#   structure-only  rc=0  PASS + STRUCTURE_ONLY sentinel --json 7b1d547773af32f5
#
# Design-bound and silent BYTE-IDENTICAL; the DISCLOSED tree the only one marked
# down. Silence ranked ABOVE disclosure — the exact inversion the rest of this
# file exists to remove, in the one gate that had a disclosed tier and no
# undisclosed one.
#
# The netlist decks below are padded past A3's 200-byte substance floor on
# purpose: the DEFAULT fixture deck is 193 bytes, and a tree that fails for a
# value reason cannot show anything about content.
A3_SUBSTANTIVE = 400


def test_the_flow_declared_a3_gate_names_what_the_netlist_contains(tmp_path):
    """THE HEADLINE. Pre-fix this gate answered rc 0 on all three trees, and it
    is the gate the FLOW runs for this step, so that certification is what the
    flow record inherits."""
    bound = _run(A3_GATE, _project(tmp_path / "d", SIZED,
                                   netlist_bytes=A3_SUBSTANTIVE))
    so = _run(A3_GATE, _project(tmp_path / "s", STRUCTURE_ONLY,
                                netlist_bytes=A3_SUBSTANTIVE))
    silent = _run(A3_GATE, _project(tmp_path / "n", None,
                                    netlist_bytes=A3_SUBSTANTIVE))

    assert bound.returncode == 0, _both(bound)
    assert bound.stdout.startswith("PASS:"), bound.stdout

    assert so.returncode == 0, _both(so)
    assert so.stdout.startswith("PASS_STRUCTURE_ONLY:"), (
        f"a netlist rendered from a LIBRARY TOPOLOGY was certified by the "
        f"step's declared gate in the same tier as a design's:\n{so.stdout}")
    assert "STRUCTURE_ONLY:" in _both(so)

    assert silent.returncode == 1, (
        f"the step's DECLARED gate certified (rc={silent.returncode}) a "
        f"netlist with nothing anywhere saying what circuit is in it — and it "
        f"certified it in the SAME tier as the design-bound tree, while the "
        f"tree that disclosed a library default was marked down")
    assert "A3_DESIGN_CONTENT_UNDECLARED" in _both(silent)


def test_the_a3_gate_writes_a_different_artefact_for_a_different_tree(
        tmp_path):
    """The flow runs this gate as `... --json reports/analog/a3_netlist.json`,
    and that document is what a machine consumer reads. Pre-fix its sha256 was
    IDENTICAL on the design-bound and the silent tree, so no consumer
    downstream of the flow could tell those two apart either."""
    shas = {}
    for tag, dc in (("d", SIZED), ("s", STRUCTURE_ONLY), ("n", None)):
        project = _project(tmp_path / tag, dc, netlist_bytes=A3_SUBSTANTIVE)
        out = tmp_path / f"{tag}.json"
        _run(A3_GATE, project, "--json", str(out))
        shas[tag] = hashlib.sha256(out.read_bytes()).hexdigest()
    assert len(set(shas.values())) == 3, (
        f"the artefact the FLOW writes for the A3 step does not distinguish a "
        f"design-bound run, a disclosed library default and a silent one: "
        f"{shas}")


def test_the_a3_gate_and_the_run_record_agree_on_every_tree(tmp_path):
    """THE INVARIANT ITSELF at A3, and the divergence that let the bug through.

    Two consumers read ONE artefact: the GATE (private `==`, pre-fix) and
    `analog_one_shot_runner`, which reads the same producer sidecar through the
    SHARED whitelist to write the run record. Pre-fix, on the silent tree, the
    gate certified design-bound while the run record — asking the same file the
    same question through the shared site — recorded NO content at all."""
    import analog_one_shot_runner as R

    for tree, dc, want in (("bound", SIZED, CERTIFIED_BOUND),
                           ("structure_only", STRUCTURE_ONLY, CERTIFIED_SO),
                           ("silent", None, REFUSED)):
        project = _project(tmp_path / f"agree_{tree}", dc,
                           blocks=("blk_alpha",),
                           netlist_bytes=A3_SUBSTANTIVE)
        gate = _tier(_run(A3_GATE, project))
        res = R.step_for_block(project, {"name": "blk_alpha", "type": "ldo"},
                               "A3_netlist_gen")
        record = (REFUSED if res.status == "FAIL"
                  else CERTIFIED_SO if res.status == "PASS_STRUCTURE_ONLY"
                  else CERTIFIED_BOUND)
        assert gate == record == want, (
            f"the gate and the run record disagree about the {tree!r} tree "
            f"(gate={gate}, run record={record} from status "
            f"{res.status!r}/extras {res.extras}); both read "
            f"phase3/analog/blk_alpha/netlist_provenance.json")


def test_the_a3_run_record_names_the_content_it_certified(tmp_path):
    """The other half of the same agreement: what the run record SAYS, not only
    which tier it lands in. A step certified in the disclosed tier must carry
    the disclosed token; a design-bound one must carry the design-bound token
    and say `structure_only: False`."""
    import analog_one_shot_runner as R

    so = R.step_for_block(
        _project(tmp_path / "so", STRUCTURE_ONLY, blocks=("blk_alpha",),
                 netlist_bytes=A3_SUBSTANTIVE),
        {"name": "blk_alpha", "type": "ldo"}, "A3_netlist_gen")
    assert so.status == "PASS_STRUCTURE_ONLY", (so.status, so.detail)
    assert so.extras.get("design_content") == STRUCTURE_ONLY, so.extras
    assert so.extras.get("structure_only") is True, so.extras

    bound = R.step_for_block(
        _project(tmp_path / "b", SIZED, blocks=("blk_alpha",),
                 netlist_bytes=A3_SUBSTANTIVE),
        {"name": "blk_alpha", "type": "ldo"}, "A3_netlist_gen")
    assert bound.status == "PASS", (bound.status, bound.detail)
    assert bound.extras.get("design_content") == SIZED, bound.extras
    assert bound.extras.get("structure_only") is False, bound.extras


def test_the_a3_disclosure_survives_the_way_the_flow_actually_runs_it(
        tmp_path):
    """`--json` is the only path the flow ever takes for this gate, and
    `flow_compliance_check._stdout_signals_structure_only` reads the line-start
    token out of the concatenated streams. A disclosure that only exists on the
    bare console path is a disclosure the flow auditor never sees."""
    project = _project(tmp_path, STRUCTURE_ONLY, netlist_bytes=A3_SUBSTANTIVE)
    cp = _run(A3_GATE, project, "--json", str(tmp_path / "r.json"))
    assert cp.returncode == 0, _both(cp)
    assert any(l.lstrip().startswith("STRUCTURE_ONLY:")
               for l in _both(cp).splitlines()), (
        f"run the way the flow runs it, the gate disclosed nothing:\n"
        f"{_both(cp)!r}")


def test_a_thin_netlist_is_still_a_thin_netlist(tmp_path):
    """ORDERING CONTROL for section 5, and the property the fix had to keep: a
    deck below the substance floor is diagnosed as THAT, even on a tree that
    also says nothing about what is in it. The content question is asked LAST,
    behind every value rule. Holds pre-fix and post-fix."""
    cp = _run(A3_GATE, _project(tmp_path, None))      # 193 B — the thin deck
    assert cp.returncode == 1
    out = _both(cp)
    assert "A3_NETLIST_TOO_SMALL" in out, out
    assert "A3_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_an_empty_subckt_shell_is_still_an_empty_subckt_shell(tmp_path):
    """The other ordering control this gate owns: a `.subckt` wrapping no
    device is a placeholder, and that is the finding — on a substantive-sized,
    silent deck where the content rule would otherwise fire. Holds pre-fix and
    post-fix."""
    root = _project(tmp_path, None, netlist_bytes=A3_SUBSTANTIVE)
    for b in BLOCKS:
        p = root / "phase3" / "analog" / b / f"{b}.sp"
        p.write_text(p.read_text().replace(
            f"xm1 vout vin vss vss nch w=8 l=1\n", "* the circuit goes here\n"))
    cp = _run(A3_GATE, root)
    assert cp.returncode == 1
    out = _both(cp)
    assert "A3_NETLIST_NO_DEVICES" in out, out
    assert "A3_DESIGN_CONTENT_UNDECLARED" not in out, out


def test_a_disclosed_library_netlist_still_certifies_the_step(tmp_path):
    """NEGATIVE CONTROL. The disclosed tier is a CERTIFICATION, not a softer
    failure: rc 0, and the step is counted covered. Only silence costs.
    Refusing an honest ceiling is what teaches the next run to stop being
    honest."""
    project = _project(tmp_path, STRUCTURE_ONLY, netlist_bytes=A3_SUBSTANTIVE)
    out = tmp_path / "r.json"
    cp = _run(A3_GATE, project, "--json", str(out))
    assert cp.returncode == 0, _both(cp)
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "PASS_STRUCTURE_ONLY", doc
    assert doc["blocks_pass"] == len(BLOCKS), doc
    assert doc["blocks_structure_only"] == len(BLOCKS), doc
    assert doc.get("blocks_fail", 0) == 0, doc


def test_the_gate_the_flow_declares_for_a3_is_the_one_verified_here():
    """The same membership guard sections 1 and 3 carry. The A3 step's gate is
    an `all_of`; the sibling clause `analog_netlist_pdk_check` judges model
    includes and body connections and does not answer the content question,
    which is safe only while the combinator is a conjunction — a clause in an
    `all_of` can only make the step stricter."""
    declared = _declared_programs("A3")
    assert declared, (
        f"no `program_exit_zero` clause found in the A3 step of {FLOW_YAML}")
    known = {A3_GATE.stem, "analog_netlist_pdk_check"}
    assert set(declared) <= known, (
        f"the flow declares {sorted(set(declared) - known)} for the A3 step, "
        f"and no test measures whether it agrees with {sorted(known)} about "
        f"`<block>.sp`")
    assert _gate_combinator("A3") == "all_of", (
        f"the A3 gate is no longer a conjunction, so a clause that does not "
        f"ask the content question can now certify the step by itself")
