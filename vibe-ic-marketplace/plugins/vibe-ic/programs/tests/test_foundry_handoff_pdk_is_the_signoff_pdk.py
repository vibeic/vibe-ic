"""BIDIRECTIONAL test: the foundry hand-off pack must declare the PDK that
PRODUCED the GDS, not the PDK the spec aspired to.

THE DEFECT
==========
`foundry_handoff_pack_gen._resolve_pdk_and_node` resolved

    pdk = l19 or l1 or pdk_from_files

i.e. the L19/L1 SPEC statement ("target PDK family") outranked everything. #467
documented that ordering as "Upstream spec facts win over PDK-file derivation",
which is correct for a requirements document and WRONG for a manufacturing
hand-off: this pack ships a GDS, and that GDS was produced by exactly one PDK.

Whenever a design is built on a PDK its own spec does not name — the entire
point of a cross-PDK benchmark matrix, and routine whenever a design is ported —
the pack recorded the ASPIRATION next to silicon from a different foundry.

MEASURED (spm x ihp-sg13cmos5l, plugin 1.6.4, image vibeic-eda:0.2.30
id sha256:4182c63b10d1). Every asset in phase3/stage3/pnr/pnr.tcl resolved under
/foss/pdks/ihp-sg13cmos5l, and the sign-off DRC ran
`script='/foss/pdks/ihp-sg13cmos5l/libs.tech/klayout/tech/drc/ihp-sg13cmos5l.drc'`.
L19 pdk_target was "sky130" (extracted from the spec's target-PDK-family prose).
Result, before the fix — all five hand-off members:

    mask_spec.json            "pdk": "sky130"
    wat_plan.json             "pdk": "sky130"
    corner_test_vectors.json  "pdk": "sky130"
    README.txt                PDK: sky130
    scribe_line_layout...txt  # pdk: sky130

…beside an IHP GDS, and `foundry_handoff_package_check` returned **PASS** —
it verifies the members EXIST, never that they agree with the flow that made
them. A 130 nm IHP die would have gone out described as sky130.

THE FIX
=======
Read the PDK off the sign-off PnR script's own asset paths — the files OpenROAD
actually consumed are ground truth for "which PDK made this" — and let that win.
The spec target is NOT discarded: on a disagreement it is recorded as
`spec_pdk_target` (with `pdk_source: "signoff_flow"`), so the divergence becomes
a stated fact instead of a silent resolution in either direction.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]

SIGNOFF_PDK = "ihp-sg13cmos5l"     # what the flow actually used
SPEC_PDK = "sky130"                # what L19 says the design targets


def _load():
    sys.path.insert(0, str(PROGRAMS))
    spec = importlib.util.spec_from_file_location(
        "_fhpg_test", PROGRAMS / "foundry_handoff_pack_gen.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fhpg_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _mk_project(tmp_path: Path, *, signoff_pdk: str | None,
                spec_pdk: str | None) -> Path:
    """A project carrying the two independent PDK statements the resolver reads:
    a PnR script naming the PDK tree the flow consumed, and an L19 spec target."""
    p = tmp_path / "proj"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)

    if signoff_pdk:
        # Shape mirrors a real pnr.tcl: several assets under one PDK tree.
        (p / "phase3" / "stage3" / "pnr" / "pnr.tcl").write_text(
            f"read_liberty /foss/pdks/{signoff_pdk}/libs.ref/x/lib/x_typ.lib\n"
            f"read_lef /foss/pdks/{signoff_pdk}/libs.ref/x/lef/x_tech.lef\n"
            f"read_lef /foss/pdks/{signoff_pdk}/libs.ref/x/lef/x.lef\n")
    if spec_pdk:
        (p / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json").write_text(
            json.dumps({"doc_id": "L19", "fields": {"pdk_target": spec_pdk}}))
    return p


# --------------------------------------------------------------------------
# NEGATIVE CONTROL — the defect present must make this FAIL, and fail for the
# RIGHT REASON. The pre-fix function returns a 2-tuple, so a bare 3-way unpack
# would raise ValueError and "fail" on the signature rather than the behaviour.
# `_resolve()` normalises both shapes so the assertion below is the only thing
# that can fail: on pristine origin/main it reports pdk == 'sky130'.
# --------------------------------------------------------------------------

def _resolve(m, proj, pdk_from_files=None, node_from_files=None):
    """Call the resolver under either signature; return (pdk, node, mismatch)."""
    got = m._resolve_pdk_and_node(proj, pdk_from_files, node_from_files)
    if len(got) == 2:                      # pre-fix shape: no divergence field
        return got[0], got[1], None
    return got


def test_NEGATIVE_CONTROL_signoff_pdk_beats_the_spec_target(tmp_path):
    """The regression itself: spec says sky130, the flow used IHP, the pack
    must say IHP."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=SIGNOFF_PDK, spec_pdk=SPEC_PDK)
    pdk, _node, mismatch = _resolve(m, proj)
    assert pdk == SIGNOFF_PDK, (
        f"hand-off pack would declare {pdk!r} for a GDS built on "
        f"{SIGNOFF_PDK!r} — the wrong process would reach the foundry")
    assert mismatch == SPEC_PDK, (
        "the spec target must be RETAINED as a recorded divergence, not dropped")


def test_NEGATIVE_CONTROL_divergence_is_recorded_not_silently_resolved(tmp_path):
    """Choosing the sign-off PDK silently would hide that the design was ported.
    The disagreement must be surfaced."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=SIGNOFF_PDK, spec_pdk=SPEC_PDK)
    _pdk, _node, mismatch = _resolve(m, proj)
    assert mismatch is not None and mismatch != _pdk


# --------------------------------------------------------------------------
# POSITIVE CONTROLS — every other case is unchanged
# --------------------------------------------------------------------------

def test_POSITIVE_CONTROL_agreement_reports_no_mismatch(tmp_path):
    """When the flow used the PDK the spec names, nothing diverges and no
    spec_pdk_target noise is emitted."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk="sky130A", spec_pdk="sky130A")
    pdk, _node, mismatch = _resolve(m, proj)
    assert pdk == "sky130A"
    assert mismatch is None


def test_POSITIVE_CONTROL_no_pnr_script_falls_back_to_the_spec(tmp_path):
    """#467's chain is preserved wherever the sign-off flow cannot answer:
    a project with no PnR script still reports the spec target."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=None, spec_pdk=SPEC_PDK)
    pdk, _node, mismatch = _resolve(m, proj)
    assert pdk == SPEC_PDK
    assert mismatch is None


def test_POSITIVE_CONTROL_ambiguous_pnr_script_never_guesses(tmp_path):
    """A script referencing two PDK trees cannot identify one — fall back to the
    spec rather than picking arbitrarily."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=None, spec_pdk=SPEC_PDK)
    (proj / "phase3" / "stage3" / "pnr" / "pnr.tcl").write_text(
        "read_liberty /foss/pdks/ihp-sg13cmos5l/a/b.lib\n"
        "read_lef /foss/pdks/sky130A/c/d.lef\n")
    pdk, _node, mismatch = _resolve(m, proj)
    assert pdk == SPEC_PDK, "an ambiguous script must not select a PDK"
    assert mismatch is None


def test_POSITIVE_CONTROL_all_sources_empty_keeps_the_honest_null(tmp_path):
    """#467's corpus-sweep guard: a project with nothing to say still says
    nothing, rather than inventing a PDK."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=None, spec_pdk=None)
    pdk, node, mismatch = _resolve(m, proj)
    assert pdk is None and node is None and mismatch is None


def test_POSITIVE_CONTROL_pdk_from_files_still_last_in_the_chain(tmp_path):
    """With neither a PnR script nor a spec statement, the PDK-file derivation
    remains the final fallback."""
    m = _load()
    proj = _mk_project(tmp_path, signoff_pdk=None, spec_pdk=None)
    pdk, _node, mismatch = _resolve(m, proj, "derived_from_files")
    assert pdk == "derived_from_files"
    assert mismatch is None
