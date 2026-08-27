"""The post-repair slack must be measured on THIS round's repair, not a stale report.

THE DEFECT. `_measure_postrepair_mcorner_ocv` decided whether to run the post-repair
multi-corner OCV STA with an EXISTENCE-ONLY guard::

    postrepair_rpt = Path(sta_out) / "sta_mcorner_ocv_postrepair.rpt"
    if not (postrepair_rpt.is_file() and postrepair_rpt.stat().st_size > 0):
        _emit_mcorner_ocv_sta(...)

so a report left behind by an EARLIER round was reused verbatim: the
re-measurement never ran and the earlier round's number was parsed out and
published as THIS round's `repair_after`.

That alone is a stale read. What makes it a false certificate is the field
right above it: `parasitics_source` is computed from the SPEFs this call
SELECTED (preferring the repair's own re-extraction, #766(c)) and then recorded as
fact — while the number beside it came from a report the previous round had
measured against the BASE route's extraction. The record therefore ASSERTS a
netlist/parasitics pairing that never happened.

MEASURED ON A REAL CELL (this is the control's provenance, not a hypothetical):
  * published by the run : setup -8.31 ns, parasitics_source=repair_reextracted,
                           measured=true      <- parsed from the stale report
  * re-emitted, same code, same inputs, stale report removed:
                           setup -0.44 ns, parasitics_source=repair_reextracted
A 23x error, and it propagated: `postroute_timing_repair_audit` raised REPAIR_REGRESSED at
"-8.220 ns" for a real delta of -0.350 ns, and the residual note called
-8.31 ns a "real timing floor" — a floor that does not exist.

THE FIX. A report that PREDATES the artefacts it claims to describe cannot be a
measurement of them. Quarantine it (`.superseded`) and re-measure. This is the
same mtime-supersession idiom `step_canonicalize_artefacts` already applies to
metal fill ("filled.def was older than the routed DEF it derives from").

BIDIRECTIONAL. `test_stale_report_is_superseded_and_remeasured` is the forward
control: it FAILS against the byte-identical pre-fix file.
`test_current_report_is_reused_without_remeasuring` is the REVERSE control — an
up-to-date report must STILL be reused, so the fix cannot degenerate into
"re-measure always", which would be both wrong and ruinously slow.
"""
import os
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

TOP = "my_core"

STALE_RPT = """=== SETUP corner: process=SS liberty=/w/ss.lib, SPEF=my_core.max.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack max -8.31
tns max -3177.14
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack min 0.46
tns max 0.00
"""

FRESH_RPT = """=== SETUP corner: process=SS liberty=/w/ss.lib, SPEF=my_core.max.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack max -0.44
tns max -0.70
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack min 0.46
tns max 0.00
"""


def _touch(p: Path, text: str, when: float):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    os.utime(p, (when, when))


def _tree(tmp_path, *, rpt_text, rpt_age_offset):
    """Build the tree `_measure_postrepair_mcorner_ocv` reads.

    `rpt_age_offset` is seconds relative to the repair artefacts: negative means
    the report PREDATES them (the stale case), positive means it postdates them
    (the healthy case).
    """
    t0 = time.time() - 10_000
    repair = R._pl.postroute_timing_repair_dir(tmp_path)
    repair.mkdir(parents=True, exist_ok=True)
    _touch(repair / f"{TOP}_timing_repaired.v", "// repair netlist\n", t0)
    # The repair's own re-extraction (#766c) — same mtime as the netlist.
    for c in ("max", "min", "nom"):
        _touch(repair / "spef_corners" / f"{TOP}.{c}.spef", "*SPEF\n", t0)
    # Reroute SUCCEEDED: no POSTROUTE_TIMING_REPAIR_DETAILED_ROUTE_NONFATAL marker.
    _touch(repair / "postroute_timing_repair.log", "POSTROUTE_TIMING_REPAIR_REEXTRACT_WROTE max\n", t0)

    sta_out = tmp_path / "phase3/stage3/sta"
    _touch(sta_out / "sta_mcorner_ocv_postrepair.rpt", rpt_text,
           t0 + rpt_age_offset)

    base_spef_dir = tmp_path / "phase3/stage3/extracted/spef_corners"
    for c in ("max", "min", "nom"):
        _touch(base_spef_dir / f"{TOP}.{c}.spef", "*SPEF\n", t0 - 5_000)
    return sta_out, base_spef_dir


def _no_emit(monkeypatch, called):
    """`_emit_mcorner_ocv_sta` must not be reached in the reuse case; when it
    IS reached, stand in for it by writing the FRESH report."""
    def fake_emit(project, top, pdk, container, corner_libs, corner_spefs,
                  nom, out_rpt, notes, netlist_override=None, **kw):
        called.append(str(out_rpt))
        Path(out_rpt).parent.mkdir(parents=True, exist_ok=True)
        Path(out_rpt).write_text(FRESH_RPT)
        return True
    monkeypatch.setattr(R, "_emit_mcorner_ocv_sta", fake_emit)


def _pdk():
    return R.PdkConfig(
        name="testpdk", liberty="/w/lib.lib", tech_lef="/w/tech.lef",
        cell_lef="/w/cells.lef", cell_gds="/w/cells.gds", site="unit",
        drc_deck="/w/drc.lydrc", metal_prefix="met")


# ── forward control: FAILS against the pre-fix file ──────────────────────────
def test_stale_report_is_superseded_and_remeasured(tmp_path, monkeypatch):
    """Report predates the repair netlist + its SPEFs -> must NOT be adopted."""
    sta_out, base_spef_dir = _tree(tmp_path, rpt_text=STALE_RPT,
                                   rpt_age_offset=-3_000)
    called = []
    _no_emit(monkeypatch, called)
    notes = []

    res = R._measure_postrepair_mcorner_ocv(
        tmp_path, TOP, _pdk(), "fake-container", {},
        base_spef_dir, None, sta_out, notes)

    assert called, (
        "the stale post-repair report was reused verbatim: an earlier round's "
        "slack is being published as this round's repair_after")
    assert res["setup_worst_slack_ns"] == -0.44, (
        f"published the stale round's number {res['setup_worst_slack_ns']} "
        "instead of re-measuring")
    assert (sta_out / "sta_mcorner_ocv_postrepair.rpt.superseded").is_file(), \
        "the superseded bytes were not quarantined for the reader"
    assert any("SUPERSEDED" in n for n in notes), \
        f"the supersession was not disclosed: {notes}"


# ── reverse control: must STILL pass ─────────────────────────────────────────
def test_current_report_is_reused_without_remeasuring(tmp_path, monkeypatch):
    """An up-to-date report must still be reused — the fix must not degenerate
    into 're-measure always' (wrong, and a multi-corner OCV STA is expensive)."""
    sta_out, base_spef_dir = _tree(tmp_path, rpt_text=FRESH_RPT,
                                   rpt_age_offset=+3_000)
    called = []
    _no_emit(monkeypatch, called)
    notes = []

    res = R._measure_postrepair_mcorner_ocv(
        tmp_path, TOP, _pdk(), "fake-container", {},
        base_spef_dir, None, sta_out, notes)

    assert not called, \
        "re-measured a report that already postdates all of its inputs"
    assert res["setup_worst_slack_ns"] == -0.44
    assert res["measured"] is True
    assert not (sta_out / "sta_mcorner_ocv_postrepair.rpt.superseded").is_file(), \
        "quarantined a perfectly current report"
    assert not any("SUPERSEDED" in n for n in notes), \
        f"a current report was reported as superseded: {notes}"


def test_parasitics_source_is_repair_reextracted_when_reroute_succeeded(tmp_path,
                                                                     monkeypatch):
    """Guards the #766(c) selection this fix sits on top of: with the repair's own
    SPEFs present and the reroute clean, the record must say so."""
    sta_out, base_spef_dir = _tree(tmp_path, rpt_text=STALE_RPT,
                                   rpt_age_offset=-3_000)
    _no_emit(monkeypatch, [])
    res = R._measure_postrepair_mcorner_ocv(
        tmp_path, TOP, _pdk(), "fake-container", {},
        base_spef_dir, None, sta_out, [])
    assert res["parasitics_source"] == "repair_reextracted"
