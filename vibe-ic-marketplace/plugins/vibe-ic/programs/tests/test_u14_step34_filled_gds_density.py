"""U14 — Steps 34/35 must measure what they claim (IC_BLOCKER_AUDIT U14).

Measured on the spm IC-path tail run (cx_spmic2_run, 8HD-4, plugin main of
2026-09-28, report paths project-relative):

  * phase3/stage3/pnr/filled.def was BYTE-IDENTICAL to routed.def (same sha);
  * reports/density.json carried only the OpenROAD row/core utilisation;
  * reports/phase3/metal_density.json measured phase3/stage3/pnr/spm.gds per
    layer but recorded NO sha of the bytes it measured;
  * Step 34 (reports/phase2/gates/metal_fill_density.json) still said
    pass=true with per_layer_density_verified=false (FILL_DONE_AT_PNR);
  * Step 35 (reports/phase3/dfm_screen.json) said PASS_WITH_ADVISORIES with
    density_ref=null — it referenced no Step-34 density verdict at all.

The rules now pinned:
  * Step 34 judges the per-layer density of the FILLED (streamed, shipped) GDS,
    bound by sha256; an absent/unbound/moved/other-stream measurement is never a
    PASS, and a layer under its window FAILs;
  * a byte-copy filled.def is not fill evidence (row-fill cells at PnR are not
    metal fill);
  * Step 35's content gate refuses a screen with density_ref null.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from _filled_gds_fixture import GDS_REL, write_filled_gds

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import metal_fill_density_check as MFD  # noqa: E402
import dfm_screen_check as DFM  # noqa: E402

# The real run's row-util-only density.json (values copied).
_ROW_ONLY_DENSITY = {
    "tool": "openroad-filler_placement", "filler_instances": 0,
    "row_utilization_pct": 99.90505577972941, "core_utilization_pct": 3.0,
    "utilization_below_report_precision": False}
# The real run's routed.def carried 75197 row-fill instances; two stand in.
_ROUTED_DEF = """VERSION 5.8 ;
DESIGN top ;
COMPONENTS 3 ;
- u1 lib__nand2_1 + PLACED ( 0 0 ) N ;
- FILLER_0_1 lib__fill_1 + PLACED ( 10 0 ) N ;
- FILLER_0_2 lib__fill_2 + PLACED ( 20 0 ) N ;
END COMPONENTS
END DESIGN
"""
# The real run's metal_density.json, minimised: same keys, same layer values,
# and — the defect — no gds_sha256.
_REAL_UNBOUND_DENSITY = {
    "tool": "klayout",
    "measurement": "per_layer_drawn_area_over_die_bbox_area",
    "gds": GDS_REL,
    "layers": {"metal1": 0.438939, "metal2": 0.386965, "metal3": 0.362177,
               "metal4": 0.359382, "metal5": 0.35929}}


def _real_shape(tmp_path: Path, *, density=None, bind=False) -> Path:
    """The spm tail-run shape: byte-copy filled.def over a row-filled routed.def,
    row-util-only density.json, a streamed GDS, and its density measurement."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(_ROUTED_DEF)
    (pnr / "filled.def").write_text(_ROUTED_DEF)          # byte copy
    (pnr / "metal_fill.done").write_text("done\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "density.json").write_text(json.dumps(_ROW_ONLY_DENSITY))
    if bind:
        write_filled_gds(tmp_path, layers=density)
    else:
        gds = tmp_path / GDS_REL
        gds.parent.mkdir(parents=True)
        gds.write_bytes(b"GDSII-filled")
        rpt = tmp_path / "reports" / "phase3" / "metal_density.json"
        rpt.parent.mkdir(parents=True)
        rpt.write_text(json.dumps(_REAL_UNBOUND_DENSITY))
    return tmp_path


def _gate(project: Path):
    out = project / "gate.json"
    r = subprocess.run([sys.executable, str(PROGRAMS / "metal_fill_density_check.py"),
                        str(project), "--json", str(out)],
                       capture_output=True, text=True)
    return r.returncode, json.loads(out.read_text())


def _cats(rep):
    return {f["category"] for f in rep["findings"]}


# ── Step 34 ─────────────────────────────────────────────────────────────────

def test_real_run_shape_is_not_a_step34_pass(tmp_path):
    """RED on main: the real shape (unbound measurement + byte-copy filled.def
    with PnR row fill) passed Step 34 via FILL_DONE_AT_PNR."""
    rc, rep = _gate(_real_shape(tmp_path))
    assert rc == 1 and rep["summary"]["pass"] is False, rep["findings"]
    assert rep["summary"]["filled_gds_density"] == "NOT_MEASURED"
    assert "FILLED_GDS_DENSITY_NOT_MEASURED" in _cats(rep)
    # the byte copy is refused as fill evidence, the row fill still disclosed
    assert "FILL_BYTE_COPY_NOT_EVIDENCE" in _cats(rep)
    assert "FILL_DONE_AT_PNR" in _cats(rep)


def test_bound_in_window_filled_gds_passes_and_names_the_byte_copy(tmp_path):
    """GREEN direction: the same shape with the measurement bound to the shipped
    stream passes, and the byte copy is disclosed as not-evidence."""
    rc, rep = _gate(_real_shape(tmp_path, bind=True))
    assert rc == 0, rep["findings"]
    assert rep["summary"]["filled_gds_density"] == "PASS"
    assert "FILLED_DEF_IS_BYTE_COPY" in _cats(rep)
    assert "FILL_BYTE_COPY_NOT_EVIDENCE" not in _cats(rep)


def test_layer_below_window_on_the_filled_gds_fails(tmp_path):
    """RED on main: a filled GDS whose metal2 sits under the whole-die floor
    (the real run's routing-only metal2 = 0.204) — main never looked."""
    low = dict(_REAL_UNBOUND_DENSITY["layers"], metal2=0.204224)
    rc, rep = _gate(_real_shape(tmp_path, density=low, bind=True))
    assert rc == 1
    assert rep["summary"]["filled_gds_density"] == "FAIL"
    oob = [f for f in rep["findings"] if f["category"] == "FILLED_GDS_DENSITY_OOB"]
    assert oob and "metal2" in oob[0]["message"]


def test_measurement_of_another_stream_is_refused(tmp_path):
    """RED on main: the measurement is bound, but to a pre-fill stream whose
    bytes are not the shipped GDS."""
    p = _real_shape(tmp_path)
    write_filled_gds(p, measured_rel="phase3/stage3/pnr/top.prefill.gds")
    (p / "phase3/stage3/pnr/top.prefill.gds").write_bytes(b"GDSII-prefill")
    rpt = p / "reports/phase3/metal_density.json"
    doc = json.loads(rpt.read_text())
    doc["gds_sha256"] = hashlib.sha256(b"GDSII-prefill").hexdigest()
    rpt.write_text(json.dumps(doc))
    rc, rep = _gate(p)
    assert rc == 1
    assert "FILLED_GDS_DENSITY_WRONG_SUBJECT" in _cats(rep)


def test_stream_rewritten_after_measurement_is_not_measured(tmp_path):
    p = _real_shape(tmp_path, bind=True)
    (p / GDS_REL).write_bytes(b"GDSII-rewritten-after-measurement")
    rc, rep = _gate(p)
    assert rc == 1
    assert rep["summary"]["filled_gds_density"] == "NOT_MEASURED"
    assert "changed since it was measured" in json.dumps(rep["findings"])


def test_no_streamed_gds_is_not_measured(tmp_path):
    p = _real_shape(tmp_path, bind=True)
    (p / GDS_REL).unlink()
    rc, rep = _gate(p)
    assert rc == 1 and rep["summary"]["filled_gds_density"] == "NOT_MEASURED"


def test_librelane_arm_is_judged_by_the_tool_deck_not_here(tmp_path, monkeypatch):
    """On the LibreLane arm `tool_arm_findings` judges the shipped GDS with the
    PDK density deck; the direct-arm judgement stays out of its way."""
    import librelane_contract as llc
    monkeypatch.setattr(llc, "selected_mode", lambda _p, _s: "librelane")
    findings, stats = MFD.audit(_real_shape(tmp_path))
    assert "filled_gds_density" not in stats
    assert not {f.category for f in findings} & {"FILLED_GDS_DENSITY_NOT_MEASURED"}


# ── producer: the measurement records the sha of the bytes it measured ──────

class _Pdk:
    name = "testpdk"
    lefdef_layermap = "/pdk/layermap.map"
    drc_deck = ""


def test_producer_binds_the_measured_gds_sha(tmp_path, monkeypatch):
    """RED on main: `_emit_metal_density_report` wrote no gds_sha256."""
    import importlib.util as iu
    spec = iu.spec_from_file_location("_p3_u14", PROGRAMS / "phase3_one_shot_runner.py")
    R = iu.module_from_spec(spec)
    sys.modules["_p3_u14"] = R
    spec.loader.exec_module(R)
    proj = tmp_path / "proj"
    gds = proj / GDS_REL
    gds.parent.mkdir(parents=True)
    gds.write_bytes(b"GDSII-filled")
    out = proj / "reports/phase3/metal_density.json"
    out.parent.mkdir(parents=True)
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "declared_die_rect", lambda _p: (None, "test"))

    def fake_exec(container, cmd, **_):     # only the tool's file write is faked
        out.write_text(json.dumps(_REAL_UNBOUND_DENSITY))
        return 0, "", ""
    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    assert R._emit_metal_density_report(proj, "top", _Pdk(), "c", out, []) is True
    doc = json.loads(out.read_text())
    assert doc["gds_sha256"] == hashlib.sha256(b"GDSII-filled").hexdigest()
    # and the gate accepts exactly that binding
    stats = MFD.filled_gds_density(proj)[1]
    assert stats["state"] == "PASS", stats


# ── Step 35 ─────────────────────────────────────────────────────────────────







def test_screen_emitted_before_step34_gate_still_carries_its_verdict(tmp_path):
    """RED on main: the runner emits the screen BEFORE the audit writes Step
    34's gate report (real run: 00:50 vs 01:04), so the screen shipped with
    density_ref null. It now reads Step 34's judge in process."""
    p = _real_shape(tmp_path)
    assert not (p / "reports/phase2/gates/metal_fill_density.json").exists()
    rep = DFM.audit(p)
    ref = rep["density_ref"]
    assert isinstance(ref, dict) and ref["step34_pass"] is False
    assert ref["filled_gds_density"] == "NOT_MEASURED"
    assert not (p / "reports/phase2/gates/metal_fill_density.json").exists(), \
        "reading step 34 in process must not write its receipt"


# ── round 2 (review wave58 TBU14) ───────────────────────────────────────────

def _load_runner():
    import importlib.util as iu
    spec = iu.spec_from_file_location("_p3_u14r2", PROGRAMS / "phase3_one_shot_runner.py")
    R = iu.module_from_spec(spec)
    sys.modules["_p3_u14r2"] = R
    spec.loader.exec_module(R)
    return R


def _stale_tree(tmp_path, monkeypatch, R, *, stale_bound_to=None):
    """A stream on disk and a PREVIOUS round's report: unbound (the real
    cx_spmic2_run report) or bound to earlier bytes."""
    proj = tmp_path / "proj"
    gds = proj / GDS_REL
    gds.parent.mkdir(parents=True)
    gds.write_bytes(b"GDSII-this-round")
    out = proj / "reports/phase3/metal_density.json"
    out.parent.mkdir(parents=True)
    old = dict(_REAL_UNBOUND_DENSITY)
    if stale_bound_to is not None:
        old["gds_sha256"] = hashlib.sha256(stale_bound_to).hexdigest()
    out.write_text(json.dumps(old))
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "declared_die_rect", lambda _p: (None, "test"))
    return proj, out


@pytest.mark.parametrize("rc", [1, 0], ids=["rc1", "rc0_via_tee"])
@pytest.mark.parametrize("stale_bound_to", [None, b"GDSII-previous-round"],
                         ids=["unbound_stale", "bound_to_previous_bytes"])
def test_tool_that_writes_nothing_never_rebinds_a_stale_report(
        tmp_path, monkeypatch, stale_bound_to, rc):
    """Finding 1 (MAJOR): KLayout exits without writing (container gone). The
    stale numbers must not be stamped with this round's sha — Step 34 reads
    NOT_MEASURED, never PASS. rc 0 too: the recipe runs piped through `tee`,
    so a KLayout that died writing nothing can still hand back rc 0."""
    R = _load_runner()
    proj, out = _stale_tree(tmp_path, monkeypatch, R, stale_bound_to=stale_bound_to)
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **_: (rc, "", "klayout: no output"))
    notes = []
    assert R._emit_metal_density_report(proj, "top", _Pdk(), "gone", out, notes) is False
    assert not out.exists(), "the stale report must not survive a re-emit"
    st = MFD.filled_gds_density(proj)[1]
    assert st["state"] == "NOT_MEASURED", st


def test_tool_nonzero_exit_is_not_bound_even_if_it_wrote(tmp_path, monkeypatch):
    """rc != 0 means the measurement is not trusted: written, but unbound."""
    R = _load_runner()
    proj, out = _stale_tree(tmp_path, monkeypatch, R)

    def fake_exec(container, cmd, **_):
        out.write_text(json.dumps(_REAL_UNBOUND_DENSITY))
        return 1, "", "recipe crashed after writing"
    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    R._emit_metal_density_report(proj, "top", _Pdk(), "c", out, [])
    doc = json.loads(out.read_text())
    assert "gds_sha256" not in doc and "rc=1" in doc["gds_sha256_refused"]
    assert MFD.filled_gds_density(proj)[1]["state"] == "NOT_MEASURED"


def _p1_shape(tmp_path, layers, absent, pdk="gf180mcuD", gds_map=None):
    """Probe P1 (integrity review): byte-copy filled.def, NO row fill at PnR
    (row util 60 %, 0 fillers), a bound measurement listing empty layers in
    `layers_absent_in_gds` as the real recipe does."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    d = "VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1 ;\n- u1 lib__nand2_1 + PLACED ( 0 0 ) N ;\nEND COMPONENTS\nEND DESIGN\n"
    (pnr / "routed.def").write_text(d)
    (pnr / "filled.def").write_text(d)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/density.json").write_text(json.dumps(
        {"filler_instances": 0, "row_utilization_pct": 60.0}))
    rpt = write_filled_gds(tmp_path, layers=layers, pdk=pdk)
    doc = json.loads(rpt.read_text())
    doc["layers_absent_in_gds"] = absent
    if gds_map is not None:
        doc["layer_gds_map"] = gds_map
    rpt.write_text(json.dumps(doc))
    return tmp_path


def test_p1_regulated_layer_absent_from_the_stream_fails(tmp_path):
    """Finding 2 (MAJOR), probe P1: gf180mcuD, metal5 has no shapes. The PDK's
    own M5.4 rule (whole-die metal5 >= 30 %) fails at 0 %; the branch at r1 read
    PASS and excused the byte copy with it."""
    p = _p1_shape(tmp_path, {f"metal{i}": 0.35 for i in range(1, 5)}, ["metal5"])
    rc, rep = _gate(p)
    assert rc == 1 and rep["summary"]["pass"] is False
    assert rep["summary"]["filled_gds_density"] == "FAIL"
    assert "metal5" in json.dumps(rep["findings"])
    assert "FILLED_DEF_IS_BYTE_COPY" not in _cats(rep)


def test_p1b_only_one_layer_measured_fails(tmp_path):
    p = _p1_shape(tmp_path, {"metal1": 0.44},
                  ["metal2", "metal3", "metal4", "metal5"])
    rc, rep = _gate(p)
    assert rc == 1 and rep["summary"]["filled_gds_density"] == "FAIL"


def test_regulated_layer_mapped_but_unreported_is_not_a_pass(tmp_path):
    """A PDK-windowed layer the measurement mapped but reported nowhere was
    never judged — NOT_MEASURED, never PASS."""
    p = _p1_shape(tmp_path, {f"metal{i}": 0.35 for i in range(1, 5)}, [],
                  gds_map={f"metal{i}": [0, 0] for i in range(1, 6)})
    rc, rep = _gate(p)
    assert rc == 1 and rep["summary"]["filled_gds_density"] == "NOT_MEASURED"


_ALL5 = {f"metal{i}": 0.36 for i in range(1, 6)}


@pytest.mark.parametrize("case,expect_pass", [
    ("bound_shipped_all_regulated_in_window", True),
    ("regulated_layer_absent", False),
    ("regulated_layer_below_window", False),
    ("bound_to_another_stream", False),
    ("unbound", False),
])
def test_p9_byte_copy_is_excused_only_by_a_complete_bound_shipped_measurement(
        tmp_path, case, expect_pass):
    """P9 decision pinned: a byte-copy filled.def (and no PnR row fill) passes
    Step 34 ONLY when an in-window measurement bound to the SHIPPED bytes
    covers EVERY regulated layer."""
    layers, absent = dict(_ALL5), []
    if case == "regulated_layer_absent":
        layers.pop("metal5"); absent = ["metal5"]
    if case == "regulated_layer_below_window":
        layers["metal3"] = 0.12
    p = _p1_shape(tmp_path, layers, absent,
                  gds_map={f"metal{i}": [0, 0] for i in range(1, 6)})
    rpt = p / "reports/phase3/metal_density.json"
    doc = json.loads(rpt.read_text())
    if case == "bound_to_another_stream":
        other = p / "phase3/stage3/pnr/top.gds"
        other.write_bytes(b"GDSII-not-shipped")
        doc["gds"] = "phase3/stage3/pnr/top.gds"
        doc["gds_sha256"] = hashlib.sha256(b"GDSII-not-shipped").hexdigest()
    if case == "unbound":
        doc.pop("gds_sha256")
    rpt.write_text(json.dumps(doc))
    rc, rep = _gate(p)
    assert (rc == 0) is expect_pass, (case, rep["findings"])
    assert rep["summary"]["pass"] is expect_pass
    assert ("FILLED_DEF_IS_BYTE_COPY" in _cats(rep)) is expect_pass
