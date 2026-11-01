#!/usr/bin/env python3
"""Pure-helper unit tests for si_mcf_sta.py (SI-aware STA via MCF bounding).

Covers every deterministic, tool-free helper:
  * coupling_pairs        — *CAP coupling entries -> aggressor/victim + Cc
  * windows_overlap       — overlap logic + unknown-window conservatism
  * mcf_for_pair          — the MCF formula per corner + window gating
  * net_windows_from_timing — per-pin arrival JSON -> per-net window
  * victim_folded_caps    — per-net MCF-bounded fold + worst aggressor
  * floor_folded_caps     — window-independent lower bound
  * rewrite_spef_folded   — coupling dropped, fold added, header rewritten,
                            MCF=1 self-fold reproduces the original total
  * net_grounded_totals / count_coupling_caps
  * independent_recount   — self-consistent PASS + false-clean recount FAIL
  * worst_setup_hold      — OpenSTA report parse
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M  # noqa: E402


# A minimal 2-net coupling SPEF: victim *1 (vic) and aggressor *2 (agg), one
# coupling cap Cc=0.1 pF between them, each net carrying 0.2 pF of ground cap.
SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "1.0"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 vic
*2 agg

*D_NET *1 0.3
*CONN
*I inv1:Z O *D BUF
*I ff1:D I *D DFF
*CAP
1 inv1:Z 0.1
2 ff1:D 0.1
3 ff1:D agg2:A 0.1
*RES
1 inv1:Z ff1:D 10
*END

*D_NET *2 0.2
*CONN
*I inv2:Z O *D BUF
*I agg2:A I *D DFF
*CAP
1 inv2:Z 0.1
2 agg2:A 0.1
*RES
1 inv2:Z agg2:A 10
*END
"""


# --------------------------------------------------------------------------
# coupling_pairs
# --------------------------------------------------------------------------
def test_coupling_pairs_extracts_pair_and_cc():
    pairs = M.coupling_pairs(SPEF)
    assert pairs == {("*1", "*2"): 0.1}


def test_coupling_pairs_accepts_preparsed_dict():
    sp = M.parse_spef(SPEF)
    assert M.coupling_pairs(sp) == {("*1", "*2"): 0.1}


# --------------------------------------------------------------------------
# windows_overlap
# --------------------------------------------------------------------------
def test_windows_overlap_basic():
    assert M.windows_overlap((0.0, 1.0), (0.5, 1.5)) is True
    assert M.windows_overlap((0.0, 1.0), (2.0, 3.0)) is False
    # touching at the boundary counts as overlap
    assert M.windows_overlap((0.0, 1.0), (1.0, 2.0)) is True


def test_windows_overlap_unknown_is_conservative():
    # unknown window => cannot prove decoupling => assume overlap
    assert M.windows_overlap(None, (2.0, 3.0)) is True
    assert M.windows_overlap((0.0, 1.0), None) is True


def test_windows_overlap_guard_band():
    # 0.4 gap; a 0.5 guard makes them overlap, no guard does not
    assert M.windows_overlap((0.0, 1.0), (1.4, 2.0)) is False
    assert M.windows_overlap((0.0, 1.0), (1.4, 2.0), guard_ns=0.5) is True


# --------------------------------------------------------------------------
# mcf_for_pair
# --------------------------------------------------------------------------
def test_mcf_setup_overlap_is_two():
    assert M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "setup") == 2.0


def test_mcf_setup_decoupled_is_one():
    assert M.mcf_for_pair((0.0, 1.0), (2.0, 3.0), "setup") == 1.0


def test_mcf_hold_overlap_is_zero():
    assert M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "hold") == 0.0


def test_mcf_hold_decoupled_is_one():
    assert M.mcf_for_pair((0.0, 1.0), (2.0, 3.0), "hold") == 1.0


def test_mcf_unknown_window_setup_is_two():
    # unknown window => assume overlap => worst-case MCF (never optimistic)
    assert M.mcf_for_pair(None, None, "setup") == 2.0
    assert M.mcf_for_pair(None, None, "hold") == 0.0


def test_mcf_bad_corner_raises():
    import pytest
    with pytest.raises(ValueError):
        M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "typ")


# --------------------------------------------------------------------------
# net_windows_from_timing
# --------------------------------------------------------------------------
def test_net_windows_from_timing_union_and_slew_pad():
    timing = {"pins": {
        "inv1:Z": {"arr_rise_min": 1.0, "arr_rise_max": 1.2,
                   "arr_fall_min": 0.9, "arr_fall_max": 1.1,
                   "slew_rise_max": 0.1, "slew_fall_max": 0.05},
    }}
    w = M.net_windows_from_timing(timing, {"*1": ["inv1:Z"]})
    # union of rise/fall arrivals = (0.9, 1.2), trailing edge padded by max slew 0.1
    assert w["*1"] == (0.9, 1.3)


def test_net_windows_from_timing_no_driver_pin_is_none():
    w = M.net_windows_from_timing({"pins": {}}, {"*1": ["missing:Z"]})
    assert w["*1"] is None


# --------------------------------------------------------------------------
# victim_folded_caps  +  floor_folded_caps
# --------------------------------------------------------------------------
def test_victim_folded_setup_folds_both_nets_at_mcf2():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}  # overlap
    folded, worst = M.victim_folded_caps(pairs, windows, "setup")
    assert folded == {"*1": 0.2, "*2": 0.2}          # 0.1 * 2 on each victim
    assert worst["*1"]["aggressor"] == "*2"
    assert worst["*1"]["mcf"] == 2.0


def test_victim_folded_hold_overlap_is_zero():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}
    folded, _ = M.victim_folded_caps(pairs, windows, "hold")
    assert folded == {"*1": 0.0, "*2": 0.0}


def test_victim_folded_decoupled_setup_is_mcf1():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (5.0, 6.0)}   # no overlap
    folded, _ = M.victim_folded_caps(pairs, windows, "setup")
    assert folded == {"*1": 0.1, "*2": 0.1}          # 0.1 * 1 (quiet)


def test_floor_folded_caps():
    pairs = {("*1", "*2"): 0.1}
    assert M.floor_folded_caps(pairs, "setup") == {"*1": 0.1, "*2": 0.1}
    assert M.floor_folded_caps(pairs, "hold") == {"*1": 0.0, "*2": 0.0}


# --------------------------------------------------------------------------
# rewrite_spef_folded
# --------------------------------------------------------------------------
def test_rewrite_drops_coupling_and_adds_ground_fold():
    folded = {"*1": 0.2, "*2": 0.2}   # setup MCF=2
    text, stats = M.rewrite_spef_folded(SPEF, folded, "setup")
    assert stats["coupling_caps_dropped"] == 1
    assert stats["nets_folded"] == 2
    assert stats["nets_no_repnode"] == 0
    # the bounded SPEF has NO coupling caps left
    assert M.count_coupling_caps(text) == 0
    # each net's grounded total rose by its fold (0.2 -> 0.4)
    g = M.net_grounded_totals(text)
    assert abs(g["*1"] - 0.4) < 1e-9
    assert abs(g["*2"] - 0.4) < 1e-9
    # header total rewritten to grounded + fold
    assert "*D_NET *1 0.4" in text


def test_rewrite_mcf1_reproduces_original_total():
    # MCF=1 self-fold: coupling moved to ground, header total UNCHANGED.
    folded = {"*1": 0.1, "*2": 0.1}
    text, _ = M.rewrite_spef_folded(SPEF, folded, "anchor")
    assert M.count_coupling_caps(text) == 0
    g = M.net_grounded_totals(text)
    # *1 original header total was 0.3 (0.2 grounded + 0.1 coupling); the MCF=1
    # self-fold moves the coupling to ground, reproducing that 0.3 exactly.
    assert abs(g["*1"] - 0.3) < 1e-9


def test_rewrite_mcf1_net2_total_matches():
    folded = {"*1": 0.1, "*2": 0.1}
    text, _ = M.rewrite_spef_folded(SPEF, folded, "anchor")
    g = M.net_grounded_totals(text)
    # *2 grounded 0.2 + folded 0.1 = 0.3
    assert abs(g["*2"] - 0.3) < 1e-9


def test_rewrite_banner_present():
    text, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.2, "*2": 0.2}, "setup")
    assert "SI-BOUNDED SPEF (SETUP corner)" in text
    assert "NOT silicon-proven" in text


# --------------------------------------------------------------------------
# net_grounded_totals / count_coupling_caps on the raw SPEF
# --------------------------------------------------------------------------
def test_grounded_totals_and_coupling_count_raw():
    assert M.count_coupling_caps(SPEF) == 1
    g = M.net_grounded_totals(SPEF)
    assert abs(g["*1"] - 0.2) < 1e-9
    assert abs(g["*2"] - 0.2) < 1e-9


# --------------------------------------------------------------------------
# independent_recount  (the GATE's false-clean-proof)
# --------------------------------------------------------------------------
def _windows_overlap_dict():
    return {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}


def test_recount_self_consistent_setup_passes():
    windows = _windows_overlap_dict()
    folded, _ = M.victim_folded_caps(M.coupling_pairs(SPEF), windows, "setup")
    bounded, _ = M.rewrite_spef_folded(SPEF, folded, "setup")
    rc = M.independent_recount(SPEF, bounded, windows, "setup")
    assert rc["ok"] is True
    assert rc["nets_checked"] == 2
    assert rc["residual_coupling_caps"] == 0


def test_recount_false_clean_dropped_fold_fails():
    # CHEAT: drop coupling but fold NOTHING (bounded stays at plain grounded)
    windows = _windows_overlap_dict()
    cheat, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "setup")
    rc = M.independent_recount(SPEF, cheat, windows, "setup")
    assert rc["ok"] is False
    assert any(v["reason"] == "UNDER_APPLIED_MCF" for v in rc["violations"])


def test_recount_residual_coupling_fails():
    # bounded == original (coupling caps never folded to ground) -> must FAIL
    windows = _windows_overlap_dict()
    rc = M.independent_recount(SPEF, SPEF, windows, "setup")
    assert rc["ok"] is False
    assert rc["residual_coupling_caps"] == 1


def test_recount_over_applied_fails():
    # inflate the fold beyond the MCF=2 ceiling (0.1*2=0.2); apply 0.5
    windows = _windows_overlap_dict()
    over, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.5, "*2": 0.5}, "setup")
    rc = M.independent_recount(SPEF, over, windows, "setup")
    assert rc["ok"] is False
    assert any(v["reason"] == "OVER_APPLIED_MCF" for v in rc["violations"])


def test_recount_floor_mode_catches_dropped_fold_without_windows():
    # gate path when the timing-window JSON is unavailable: use the MCF>=1 floor
    expected = M.floor_folded_caps(M.coupling_pairs(SPEF), "setup")
    cheat, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "setup")
    rc = M.independent_recount(SPEF, cheat, {}, "setup", expected=expected)
    assert rc["ok"] is False


# --------------------------------------------------------------------------
# worst_setup_hold
# --------------------------------------------------------------------------
def test_worst_setup_hold_parse():
    rpt = "worst slack max 7.3675\nworst slack min 0.3934\n"
    assert M.worst_setup_hold(rpt) == (7.3675, 0.3934)


def test_worst_setup_hold_missing():
    assert M.worst_setup_hold("no slack here") == (None, None)


@pytest.mark.parametrize("rc", [0, 127])
def test_failed_sta_does_not_reuse_retained_slacks(tmp_path, monkeypatch, rc):
    retained = "worst slack max 1.25\nworst slack min 0.25\n"
    (tmp_path / "si_mcf_sta_nominal.rpt").write_text(retained)
    monkeypatch.setattr(M, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(M, "_docker_exec", lambda *a, **k: (rc, "", "launch failed"))
    setup, hold, body, actual_rc = M._run_sta_slack(
        "host", tmp_path, "nominal", "cells.lib", "design.v", "widget",
        "design.sdc", "design.spef", [])
    assert actual_rc == rc and body == retained
    assert (setup, hold) == ((1.25, 0.25) if rc == 0 else (None, None))


@pytest.mark.parametrize("rc", [0, 127])
def test_failed_window_launch_does_not_reuse_retained_windows(tmp_path, monkeypatch, rc):
    import json
    retained = {"pins": {"widget/q": {"arr_rise_min": 1.0}}}
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(retained))
    monkeypatch.setattr(M, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(M, "_docker_exec", lambda *a, **k: (rc, "", "launch failed"))
    windows, actual_rc = M._run_windows(
        "host", tmp_path, "cells.lib", "design.v", "widget", "design.sdc",
        "design.spef", [], 1.8, path)
    assert actual_rc == rc
    assert windows == (retained if rc == 0 else {"pins": {}})


@pytest.mark.parametrize("rc,expected", [(0, "PASS"), (127, "ERROR")])
def test_run_failed_sta_overrides_positive_slacks(tmp_path, monkeypatch, rc, expected):
    spef = tmp_path / "design.spef"
    spef.write_text(SPEF)
    monkeypatch.setattr(M, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(M, "_run_windows", lambda *a, **k: ({"pins": {}}, 0))
    monkeypatch.setattr(M, "_run_sta_slack", lambda *a, **k: (1.25, 0.25, "", rc))
    report = M.run(tmp_path, container="host", spef=str(spef),
                   netlist=str(tmp_path / "design.v"), sdc="design.sdc",
                   liberty="cells.lib", top="widget")
    assert report["verdict"] == expected


@pytest.mark.parametrize("supervised", [False, True])
def test_local_sta_dispatch_uses_local_route(monkeypatch, supervised):
    monkeypatch.setattr(M._ce, "no_container_route", lambda: True)
    command = "printf 'current-local-sta'"
    if supervised:
        rc, out, err = M._docker_exec("LOCAL", command, timeout=10)
    else:
        rc, out, err = M._docker_exec_raw("LOCAL", command)
    assert rc == 0, err
    assert out == "current-local-sta"


# ── R-0915-107: the SI STA report is published WITH its basis, or not at all ──
import _sta_basis  # noqa: E402


def _corners(*rcs):
    return [{"corner": f"mcf_{i}", "worst_setup_slack_ns": 1.0,
             "worst_hold_slack_ns": 2.0, "sta_rc": rc}
            for i, rc in enumerate(rcs)]


def _publish(tmp_path, *, rcs=(0,), nom_rc=0, out_json=None):
    out_json_p = (Path(out_json) if out_json
                  else tmp_path / "reports/phase3/si_mcf_sta.json")
    out_json_p.parent.mkdir(parents=True, exist_ok=True)
    return M.publish_si_sta_report(
        tmp_path, out_json_p, out_json, top="widget", spef_name="w.spef",
        verdict="PASS", nom_setup=1.0, nom_hold=2.0, nom_rc=nom_rc,
        corners=_corners(*rcs))


def test_the_published_report_states_a_basis_that_resolves(tmp_path):
    """Step 27 DECLARES this report, so it must exist and must disclose the
    basis it was measured on — post-route extracted parasitics with the coupling
    caps MCF-folded. Read through `_sta_basis`, the ONE reader of the stamp, so
    this asserts what every consumer will see and not a string of its own."""
    p = _publish(tmp_path)
    assert p is not None and p.is_file()
    assert p.name == "si_mcf_sta.rpt"
    assert _sta_basis.declared_basis(p.read_text()) == "POST_ROUTE"


def test_no_corner_reached_opensta_means_no_report(tmp_path):
    """THE RULING'S OWN CLAUSE: if the emitter cannot state a basis it does not
    write the report. A run where no corner reached OpenSTA measured no parasitic
    timing, so it has no basis to disclose — and a timing report without one is
    the laundering the stage gate exists to catch. Nothing is written, and the
    absence is the honest artefact."""
    assert _publish(tmp_path, rcs=(1, 1)) is None
    assert not (tmp_path / "reports/phase3/si_mcf_sta.rpt").exists()


def test_a_failed_nominal_run_also_publishes_nothing(tmp_path):
    """The nominal grounded corner is the reference the folded corners are read
    against; without it there is no basis either."""
    assert _publish(tmp_path, rcs=(0,), nom_rc=1) is None
    assert not (tmp_path / "reports/phase3/si_mcf_sta.rpt").exists()


def test_one_good_corner_among_failures_is_enough_to_publish(tmp_path):
    """Both directions of the same predicate: the clause withholds the report
    when NO corner measured, not whenever any corner failed."""
    p = _publish(tmp_path, rcs=(1, 0))
    assert p is not None and p.is_file()


def test_a_redirected_out_json_carries_the_report_with_it(tmp_path):
    """The r21 discipline this module already records: `si_mcf_repair` measures a
    CANDIDATE through `run` with `out_json` redirected, and a candidate must not
    overwrite the shipping run's working set. So the report follows `out_json`
    and the canonical path stays untouched."""
    cand = tmp_path / "txn" / "si_mcf_sta_candidate.json"
    cand.parent.mkdir(parents=True, exist_ok=True)
    p = _publish(tmp_path, out_json=cand)
    assert p == cand.with_suffix(".rpt") and p.is_file()
    assert not (tmp_path / "reports/phase3/si_mcf_sta.rpt").exists()
    assert _sta_basis.declared_basis(p.read_text()) == "POST_ROUTE"


# ── the top-module read is a DECLARATION read, not a sentence read ────────────
#
# The polarity ratchet flagged `si_mcf_sta::run` when this module began
# publishing a DECLARED report: `top` came from a bare
# `re.search(r"^\s*module\s+(\w+)", raw)` INSIDE `run`, so `run` was a function
# that read a value out of text and wrote it into a record. The read now goes
# through `gate_utils.find_modules`, the shared module reader.
#
# WHAT THESE CASES PIN, and it is narrower than the first version of this block
# claimed. I had added a comment/string stripper and asserted it was what kept a
# sentence from winning. MEASURED, that was wrong twice over:
# `gate_utils._MODULE_KW_RE` is `^\s*module\s+(\w+)\b` — anchored at LINE
# START — and a module must close with `endmodule`, so comment and legal-string
# rivals were ALREADY defeated without any stripping; and the one rival that does
# win, a quote spanning a raw newline, was NOT defeated by the stripper either.
# The stripper was dropped rather than shipped with a docstring it did not earn.
_RIVAL = "module ghost (input a); endmodule"

_RIVAL_CONTEXTS = (
    ("block comment", f"/* {_RIVAL} */\n"),
    ("line comment", f"// {_RIVAL}\n"),
    ("display string", f'initial $display("{_RIVAL}");\n'),
    ("localparam string", f'localparam S = "{_RIVAL}";\n'),
)

_REAL = "module real_one (input a);\nendmodule\n"


@pytest.mark.parametrize("label,rival", _RIVAL_CONTEXTS)
def test_a_complete_rival_module_in_prose_cannot_win_the_top_read(
        tmp_path, label, rival):
    """A COMPLETE rival — `module ghost (input a); endmodule`, not a bare keyword
    — placed ABOVE the real declaration, where a first-match read takes it. The
    design's own declaration must still be the answer, because none of these
    puts `module` at line start."""
    n = tmp_path / f"{label.replace(' ', '_')}.v"
    n.write_text(rival + _REAL)
    assert M._top_from_netlist(n) == "real_one", label


@pytest.mark.parametrize("label,rival", _RIVAL_CONTEXTS)
def test_a_complete_rival_below_the_declaration_cannot_win_either(
        tmp_path, label, rival):
    """Both directions a denial could act: after the declaration as well as
    before it."""
    n = tmp_path / f"below_{label.replace(' ', '_')}.v"
    n.write_text(_REAL + rival)
    assert M._top_from_netlist(n) == "real_one", label


def test_a_multiline_quote_is_a_known_limit_and_is_recorded_as_one(tmp_path):
    """THE ONE CASE NOT DEFENDED, pinned so the limit is visible rather than
    surprising. A quote spanning a raw newline whose second line begins with a
    complete module DOES win the read. That is not legal Verilog — a string
    literal cannot contain an unescaped newline — so the netlist is malformed,
    and closing it belongs in the shared reader with every other caller of
    `find_modules`, not in this emitter. Asserted in the direction it actually
    behaves; if the shared reader is ever hardened, this case fails and is the
    prompt to delete it."""
    n = tmp_path / "multiline_quote.v"
    n.write_text(f'initial $display("\n{_RIVAL}");\n' + _REAL)
    assert M._top_from_netlist(n) == "ghost"


def test_the_declaration_is_what_moves_the_answer(tmp_path):
    """NEGATIVE CONTROL: the answers above must be about the grammar, not a
    fixture that could not move. Rename the real module and the answer follows
    it — so the read is reaching the text."""
    n = tmp_path / "moved.v"
    n.write_text("module actually_this_one (input a);\nendmodule\n")
    assert M._top_from_netlist(n) == "actually_this_one"


def test_an_unclosed_module_is_not_a_declaration(tmp_path):
    """THE `endmodule` HALF, pinned with the fixture that actually discriminates.
    An earlier version of this case used a bare `module\n`, which a plain
    line-anchored regex ALSO rejects (nothing follows the keyword) — so it held
    whether or not the reader required a closing `endmodule`, and the mutation
    that removed that requirement left it green. `module orphan (input a);` with
    no `endmodule` separates them: a bare regex answers `orphan`, the shared
    reader answers nothing, and nothing is the honest answer — the caller then
    falls back to its own default rather than shipping a scraped word as the
    design's top."""
    n = tmp_path / "orphan.v"
    n.write_text("module orphan (input a);\n")
    assert M._top_from_netlist(n) is None


def test_a_bare_module_keyword_answers_nothing(tmp_path):
    """The weaker sibling of the case above, kept because it is a different
    input: a keyword with no name at all."""
    n = tmp_path / "bare.v"
    n.write_text("module\n")
    assert M._top_from_netlist(n) is None


def test_an_absent_netlist_answers_nothing(tmp_path):
    """"Could not read it" is not "read it and it declared nothing"; both land on
    None here, and the caller's default is what names the fallback."""
    assert M._top_from_netlist(tmp_path / "nope.v") is None
