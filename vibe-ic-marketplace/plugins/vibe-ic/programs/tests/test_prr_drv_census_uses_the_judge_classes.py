"""Step 32's final DRV count uses the DRV standard's classes, not raw rows.

MEASURED on the routed spm DIE (lane drvrcpt, 32-base STAPostPNR, 9 scenes):
the post-route repair (PRR) census counted every `(pin, check)` row the tool
printed. 35 of them per scene were bond-pad PORTS -- `clk`, `rst`, `x[0..31]`,
`y` -- at 2.989 pF against the 0.2 pF std-cell margin: the pad's own PAD-pin
capacitance on a net no std cell drives. Those rows alone made Step 32 FAIL and
stopped stream-out (root audit U1). R-0928-DRV-IC: a port-to-PAD net is judged
by the IO Liberty T1 (the IO-cell pin row, which stays counted) and the set_load,
never by the std-cell margin; an IO-cell pin under the std-cell margin but within
its IO Liberty limit is listed apart (DRV standard section 4).

The fixture's report text has the shape of that STAPostPNR `sta.log`; the
netlist and IO Liberty are the run's own kinds of input, shrunk to four cells.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import librelane_postroute_repair as P  # noqa: E402

CORNER = "nom_tt_025C_5v00"

_LIB = """library ("io_tt") {
  time_unit : "1ns";
  capacitive_load_unit (1.000000, "pf");
  default_max_capacitance : 999.000000;
  default_max_fanout : 1.000000;
  cell ("PADIN") {
    pad_cell : true;
    pin ("PAD") {
      max_transition : 1.000000;
      direction : "input";
    }
    pin ("Y") {
      direction : "output";
    }
  }
  cell ("PADWEAK") {
    pad_cell : true;
    pin ("PAD") {
      max_transition : 1.000000;
      direction : "input";
    }
    pin ("Y") {
      max_capacitance : 0.150000;
      direction : "output";
    }
  }
  cell ("PADMID") {
    pad_cell : true;
    pin ("PAD") {
      max_transition : 1.000000;
      direction : "input";
    }
    pin ("Y") {
      max_capacitance : 0.300000;
      direction : "output";
    }
  }
  cell ("BUF") {
    pin ("A") { direction : input; }
    pin ("Z") { direction : output; }
  }
}
"""

_NETLIST = """module top (a, b, c, n);
  input a;
  input b;
  input c;
  input n;
  PADIN u_pad_a (.PAD(a),
    .Y(a_core));
  PADWEAK u_pad_b (.PAD(b),
    .Y(b_core));
  PADMID u_pad_c (.PAD(c),
    .Y(c_core));
  BUF \\u_core/u1  (.A(a_core),
    .Z(z1));
  BUF u2 (.A(n),
    .Z(z2));
endmodule
"""

# pin, limit, value -- one row of each class the standard names.
_SLEW = [("u_pad_a/PAD", "1.000000", "49.209225"),   # IO Liberty T1: counted
         ("a", "3.000000", "49.209231")]             # bond-pad port: listed
_FANOUT = [("u_pad_a/Y", "1", "3")]                  # IO default 1: counted
_CAP = [("a", "0.200000", "2.989206"),               # bond-pad port: listed
        ("n", "0.200000", "0.250000"),               # port into a std cell: counted
        ("u_pad_a/Y", "0.200000", "0.211182"),       # IO pin within IO Liberty: listed
        ("u_pad_b/Y", "0.150000", "0.180000"),       # IO pin over IO Liberty: counted
        ("u_pad_c/Y", "0.200000", "0.350000"),       # margin below IO Liberty, value over it: counted
        ("u_core/u1/Z", "0.200000", "0.246000")]     # std-cell margin: counted


def _table(title, head, rows, blank_between=False):
    out = [title, "", head, "-" * len(head)]
    for i, (pin, lim, val) in enumerate(rows):
        slack = float(lim) - float(val)
        out.append(f"{pin:<40}{lim:>9} {val:>11} {slack:>11.6f} (VIOLATED)")
        if blank_between:
            out.append("")
    return out + [""]


def _sta_log():
    lines = ["======================= " + CORNER + " Corner ====", ""]
    lines += _table("max slew", "Pin" + " " * 40 + "Limit        Slew       Slack", _SLEW)
    lines += _table("max fanout", "Pin" + " " * 35 + "Limit Fanout  Slack", _FANOUT)
    lines += _table("max capacitance", "Pin" + " " * 40 + "Limit         Cap       Slack",
                    _CAP, blank_between=True)
    lines += ["=" * 75,
              f"max slew violation count {len(_SLEW)}",
              f"max fanout violation count {len(_FANOUT)}",
              f"max cap violation count {len(_CAP)}", "=" * 75]
    return "\n".join(lines) + "\n"


def _stage(tmp_path, pad_libs=True, lib_text=_LIB):
    pdk = tmp_path / "pdk"
    (pdk / "io").mkdir(parents=True)
    (pdk / "io" / "io_tt.lib").write_text(lib_text)
    nl = tmp_path / "top.nl.v"
    nl.write_text(_NETLIST)
    sta = tmp_path / "04-openroad-stapostpnr"
    (sta / CORNER).mkdir(parents=True)
    (sta / CORNER / "sta.log").write_text(_sta_log())
    sdc = tmp_path / "signoff.sdc"   # the design-scope std-cell margin STA read
    sdc.write_text("set_max_capacitance 0.2 [current_design]\n")
    cfg = {"STA_CORNERS": [CORNER], "SIGNOFF_SDC_FILE": str(sdc)}
    if pad_libs:
        cfg["PAD_LIBS"] = {"*_tt_025C_5v00": ["/pdk/io/io_tt.lib"]}
    (sta / "config.json").write_text(json.dumps(cfg))
    (sta / "state_in.json").write_text(json.dumps({"nl": str(nl)}))
    ctx = {"corners": [CORNER], "mounts": [(str(pdk), "/pdk")], "project": str(tmp_path)}
    summary = {"drv": {"slew": {CORNER: len(_SLEW)}, "cap": {CORNER: len(_CAP)},
                       "fanout": {CORNER: len(_FANOUT)}}}
    return ctx, sta, summary


def _census(tmp_path, **kw):
    ctx, sta, summary = _stage(tmp_path, **kw)
    build = getattr(P, "_drv_classifier", None)
    classifier = build(ctx, sta) if build else None
    if classifier is None:
        return P.drv_pin_census(sta, summary, ctx["corners"])
    return P.drv_pin_census(sta, summary, ctx["corners"], classifier=classifier)


def _counted(census):
    return sorted(tuple(p) for p in census["drv_pin_checks"])


def test_bond_pad_port_rows_are_not_std_cell_drv(tmp_path):
    census = _census(tmp_path)
    assert census["drv_pin_checks_state"] == "PASS", census
    counted = _counted(census)
    assert ("a", "cap") not in counted, counted
    assert ("a", "slew") not in counted, counted


def test_the_io_liberty_rows_and_the_core_row_still_count(tmp_path):
    counted = _counted(_census(tmp_path))
    assert counted == sorted([("u_pad_a/PAD", "slew"), ("u_pad_a/Y", "fanout"),
                              ("n", "cap"), ("u_pad_b/Y", "cap"), ("u_pad_c/Y", "cap"),
                              ("u_core/u1/Z", "cap")]), counted


def test_every_row_left_out_is_listed_with_its_class(tmp_path):
    census = _census(tmp_path)
    listed = sorted((r["pin"], r["check"], r["class"])
                    for r in census.get("drv_pin_checks_excluded") or [])
    assert listed == sorted([
        ("a", "slew", "OFFCHIP_PORT_TO_PAD_NET"),
        ("a", "cap", "OFFCHIP_PORT_TO_PAD_NET"),
        ("u_pad_a/Y", "cap", "IO_STD_CELL_MARGIN_DISCLOSURE")]), listed


def test_final_drv_counts_only_the_drv_class(tmp_path):
    census = _census(tmp_path)
    report = {"verdict": "PASS", "final": {"drv_count": len(census["drv_pin_checks"])}}
    P._set_final_drv_verdict(report)
    assert report["final_drv"]["violations"] == 6, report


def test_an_unreadable_io_liberty_is_not_measured_never_excluded(tmp_path):
    ctx, sta, summary = _stage(tmp_path)
    (tmp_path / "pdk" / "io" / "io_tt.lib").unlink()
    classifier = P._drv_classifier(ctx, sta)
    census = P.drv_pin_census(sta, summary, ctx["corners"], classifier=classifier)
    assert census["drv_pin_checks_state"] == "NOT_MEASURED", census
    assert census["drv_pin_checks"] is None


def test_the_candidate_measurement_counts_with_the_classes(tmp_path, monkeypatch):
    """The wiring: Step 32's own measurement (`_candidate`) hands the census
    the run's classes. Only the tool-running seams are stubbed; the census,
    the classes and the drv_count are the real code on the fixture's files."""
    import librelane_contract as _ll
    import excluded_master_census_check as _emc
    import _native_postroute_timing as _native
    ctx, sta, summary = _stage(tmp_path)
    metrics = {"timing__setup__ws__corner:" + CORNER: 1.0,
               "timing__hold__ws__corner:" + CORNER: 0.1}
    for kind, per in summary["drv"].items():
        metrics[f"design__max_{kind}_violation__count__corner:{CORNER}"] = per[CORNER]
    (sta / "state_out.json").write_text(json.dumps({"metrics": metrics}))
    repair, antenna = tmp_path / "01-repair", tmp_path / "02-antenna"
    for folder in (repair, antenna):
        folder.mkdir()
        (folder / "state_out.json").write_text("{}")
    monkeypatch.setattr(_ll, "run_chain", lambda *a, **k: [repair, antenna, sta])
    monkeypatch.setattr(_emc, "write_audit", lambda *a, **k: {})
    monkeypatch.setattr(_native, "measure", lambda *a, **k: {})
    monkeypatch.setattr(P, "antenna_census", lambda folder: {
        "antenna__violating__nets": 0, "antenna__violating__pins": 0})
    ctx.update(project=str(tmp_path), image="img", configs={
        step: str(sta / "config.json") for step in P.MEASURE_STEPS})
    _, measured = P._candidate(ctx, sta / "config.json", sta / "state_in.json", "t")
    assert measured["drv_count"] == 6, measured["drv_members"]


def test_a_padless_run_counts_every_row_as_before(tmp_path):
    """Control: no PAD_LIBS -> no classes; the census is main's census."""
    ctx, sta, summary = _stage(tmp_path, pad_libs=False)
    build = getattr(P, "_drv_classifier", None)
    assert build is None or build(ctx, sta) is None
    census = P.drv_pin_census(sta, summary, ctx["corners"])
    assert len(census["drv_pin_checks"]) == len(_SLEW) + len(_FANOUT) + len(_CAP)


@pytest.mark.parametrize("syntax", ["concatenation", "positional", "branching_alias", "unconnected"])
def test_unresolved_structural_connectivity_keeps_ports_counted(tmp_path, syntax):
    ctx, sta, summary = _stage(tmp_path)
    path = tmp_path / "top.nl.v"
    text = path.read_text()
    if syntax == "concatenation":
        text = text.replace(".A(n)", ".A({n,a})")
    elif syntax == "positional":
        text = text.replace(".A(n),\n    .Z(z2)", "a, z2")
    elif syntax == "branching_alias":
        text = text.replace("endmodule", "assign alias1 = a; assign alias2 = a; endmodule")
    else:
        text = text.replace(".A(n)", ".A()")
    path.write_text(text)
    census = P.drv_pin_census(sta, summary, ctx["corners"], classifier=P._drv_classifier(ctx, sta))
    assert ("a", "cap") in _counted(census)
    assert ("a", "slew") in _counted(census)
    assert ("u_core/u1/Z", "cap") in _counted(census)
    assert ("u_pad_b/Y", "cap") in _counted(census)
    assert any(row["class"] == "IO_STD_CELL_MARGIN_DISCLOSURE"
               for row in census["drv_pin_checks_excluded"])


@pytest.mark.parametrize("connection", ["alias", "concat"])
def test_prr_keeps_a_core_load_hidden_by_verilog_spelling(tmp_path, connection):
    ctx, sta, summary = _stage(tmp_path)
    nl = tmp_path / "top.nl.v"
    rhs = "a_alias" if connection == "alias" else "{n,a}"
    text = nl.read_text().replace(".A(n)", f".A({rhs})")
    if connection == "alias":
        text = text.replace("endmodule", "wire a_alias; assign a_alias = a; endmodule")
    nl.write_text(text)
    census = P.drv_pin_census(sta, summary, ctx["corners"], classifier=P._drv_classifier(ctx, sta))
    assert ("a", "cap") in _counted(census), census
    assert ("a", "slew") in _counted(census), census


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
