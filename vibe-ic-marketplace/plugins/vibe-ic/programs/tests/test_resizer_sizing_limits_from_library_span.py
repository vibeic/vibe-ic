"""RESIZER SIZING LIMITS — a chip-AGNOSTIC Phase-3 defect found on a real
multi-supply hard-macro design and invisible to every gate that ran at the time.

`PreChecks::checkSlewLimit` computes the best achievable transition over
`getSwappableCells(buffer_lowest_drive_)`, and `getSwappableCells` drops any
candidate more than `sizing_area_limit_` / `sizing_leakage_limit_` (BOTH
default 4.0) times the current cell's. On a library whose buffer family spans
wider than 4X — which is every library measured, open or commercial — the
weakest buffer cannot see the strong ones, "best achievable" is computed from a
crippled pool, and `repair_design` ABORTS with [ERROR RSZ-0090] against a
max_transition the library can in fact meet.

The fix does NOT widen the timing constraint. `max_transition` is untouched;
what is restored is the resizer's SWAP POOL, whose 4.0X area/leakage cut-off is
a cost heuristic, not a statement about the library's contents. The VALUE is the
library's own measured buffer-family span, so a library that already fits inside
4X is never touched. The block must be emitted BEFORE the first timing-driven
step, because RSZ-0090 is a fatal error raised from `global_placement
-timing_driven`, not only from an explicit `repair_design`.

HOW THIS FILE PROVES IT, AND WHY IT WAS REWRITTEN (2026-08-05)
=============================================================
As first landed (41c49f94d) this file did NOT reproduce the defect. Measured
against the pre-landing tree e3aa9b126, its 11 tests came out:

    9 x AttributeError  — `_liberty_buffer_family`, `_sizing_limits_preamble_tcl`,
                          `_sizing_limits_drv_report_tcl`,
                          `_buffer_family_sizing_spans` do not exist there;
    1 x ValueError      — `inspect.getsource(step_pnr).index("_sl_spans = ")`;
    1 x PASS            — the negative control, which asserts an ABSENCE and so
                          passes on a tree where the feature is absent;
    0 x AssertionError.

Every failure said only "a private symbol is missing". That is symbol existence,
not behaviour, and the landing commit's own docstring claimed the opposite of it.

Part A below drives `step_pnr` — the shipped Phase-3 step — against a fake
container and a real liberty on disk, and asserts on the pnr.tcl the step
actually emits and on what the step prints. Each of those raises AssertionError
on e3aa9b126 and passes on b85d68acc.

Part B is ONE test that could NOT be re-pointed, because the property it guards
has no observable outside the module. It is declared there rather than dressed
up; read its docstring before treating its green as proof of anything.

chip-AGNOSTIC: synthetic liberties whose cell names, areas and leakages match no
real PDK; no OpenROAD, no container.
"""
from __future__ import annotations

import difflib
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as R  # noqa: E402


# ── liberty fixtures ──────────────────────────────────────────────────────
def _cell(name, area, leak, function="A", extra_in=()):
    pins = ['    pin (A) { direction : input; capacitance : 0.01; }']
    for p in extra_in:
        pins.append(f'    pin ({p}) {{ direction : input; capacitance : 0.01; }}')
    pins.append(
        f'    pin (Z) {{ direction : output; function : "{function}";\n'
        f'      timing () {{ related_pin : "A"; '
        f'cell_rise (t) {{ values("1,2"); }} }}\n'
        f'    }}')
    return (f'  cell ("{name}") {{\n'
            f'    area : {area};\n'
            f'    cell_leakage_power : {leak};\n'
            + "\n".join(pins) + "\n  }")


def _lib(name, cells):
    """``cells`` is [(cell, area, leakage)] — every one a structural buffer."""
    return (f'library ({name}) {{\n'
            + "\n".join(_cell(c, a, k) for c, a, k in cells)
            + "\n}")


#: 3.5X area / 3.5X leakage — inside OpenROAD's 4.0X default, must be untouched
NARROW = _lib("narrow", [("BUFX1", 10.0, 1.0), ("BUFX2", 20.0, 2.0),
                         ("BUFX4", 35.0, 3.5)])
#: 8X area / 40X leakage
WIDE = _lib("wide", [("BUFX1", 10.0, 1.0), ("BUFX8", 80.0, 40.0)])
#: 16X area / 90X leakage
WIDER = _lib("wider", [("BUFX1", 10.0, 1.0), ("BUFX16", 160.0, 90.0)])
#: leakage-only outlier: 3.5X area (fits the default) / 90X leakage (does not)
LEAKY = _lib("leaky", [("BUFX1", 10.0, 1.0), ("BUFX4", 35.0, 90.0)])
#: WIDE plus an inverter and a 2-input gate that are SMALLER and LESS leaky than
#: every buffer. If they entered the span the answer would be 80/5 = 16X area
#: and 40/0.5 = 80X leakage instead of the buffer family's own 8X / 40X.
WIDE_PLUS_LOGIC = (
    'library (mixed) {\n'
    + _cell("BUFX1", 10.0, 1.0) + "\n"
    + _cell("BUFX8", 80.0, 40.0) + "\n"
    + _cell("INVX1", 5.0, 0.5, function="!A") + "\n"
    + _cell("NAND2X1", 7.0, 0.7, function="!(A B)", extra_in=("B",)) + "\n}")


def _expect(span, margin=1.1):
    """The limit is the measured span x margin, rounded UP to 2dp — rounding
    DOWN could land back under the span it was measured from."""
    return math.ceil(span * margin * 100.0) / 100.0


# ── driving the shipped step ──────────────────────────────────────────────
_ROUTE_OK = ("[INFO DRT-0199]   Number of violations = 0.\n"
             "[INFO DRT-0198] Complete detail routing.\n"
             "PG_NET_OWNERSHIP_AUDIT: total=600 no_net=0 masters=\n")

_ROUTED_DEF = ("VERSION 5.8 ;\nDESIGN widget ;\nUNITS DISTANCE MICRONS 1000 ;\n"
               "NETS 1 ;\n- n0 ( u0 Y ) ( u1 A )\n"
               "  + ROUTED met1 ( 1 2 ) ( 3 4 )\n  ;\nEND NETS\nEND DESIGN\n")


def _pnr_tcl(tmp_path: Path, monkeypatch, *, liberty: str,
             corner_libs: dict | None = None, top: str = "widget") -> str:
    """Run `step_pnr` against a fake OpenROAD and return the pnr.tcl it emitted.

    `liberty` is the PDK library's TEXT, written to a fixed path under
    ``tmp_path`` so two calls differ only in library CONTENT. `corner_libs`
    optionally stages a sign-off corner set under ``input/pdk/liberty/``, which
    is where `_resolve_signoff_corner_libs` looks. Nothing here is measured for
    the test — the step measures whatever is on disk, exactly as on a real run.
    """
    project = tmp_path / "proj"
    synth = R._pl.synth_dir(project)
    synth.mkdir(parents=True, exist_ok=True)
    lines = [f"module {top}(input clk, input a, output y);"]
    for i in range(300):
        lines.append(f"CELLA u{i} (.A(n{i}), .Y(n{i + 1}));")
    lines.append("endmodule")
    (synth / f"{top}_synth.v").write_text("\n".join(lines))

    libpath = tmp_path / "pdk.lib"
    libpath.write_text(liberty)
    if corner_libs:
        d = project / "input" / "pdk" / "liberty"
        d.mkdir(parents=True, exist_ok=True)
        for name, text in corner_libs.items():
            (d / name).write_text(text)

    pdk = R.PdkConfig(
        name="sky130A", liberty=str(libpath),
        tech_lef="/placeholder/x.tlef", cell_lef="/placeholder/x.lef",
        cell_gds="/placeholder/x.gds", site="unithd",
        drc_deck="/placeholder/x.drc", metal_prefix="met",
        tapcell_master="TAPA", antenna_diode_cell="DIODEA",
        tapcell_distance_um=14.0,
        # PINNED SO THE TWO ARMS DIFFER IN THE SPAN AND IN NOTHING ELSE.
        #
        # With these left None, `_i1958_pick_cts_buffers` derives the CTS
        # buffer masters from `pdk.liberty` — so the emitted deck depends on the
        # library's CELL NAMES, not only on the buffer family's drive SPAN,
        # which is the property under test. MEASURED on TREE 7903c1972305, the
        # WIDE-vs-NARROW diff carried four runs, two of them `replace`:
        #     insert   the sizing preamble            <- under test
        #     replace  foreach _wc_cm {"BUFX1" "BUFX4"} -> {"BUFX1" "BUFX8"}
        #     insert   the DRV evidence block         <- under test
        #     replace  clock_tree_synthesis … -root_buf "BUFX4" -> "BUFX8"
        # and `_inserted_runs` refuses any non-insert, so both arms died on a
        # difference that is not the one they are comparing.
        #
        # NOT FIXED BY LOOSENING `_inserted_runs`: its refusal of replace and
        # delete IS the claim of this file — restoring the swap pool must not
        # REWRITE the script, and `set_max_transition` is the exact regression
        # it stands guard over. Nor by filtering the CTS line out by name,
        # which is a hand-written allow-list and blind to the next
        # liberty-dependent emission.
        #
        # A real PDK registry declares these (`clk_buf_cell` /
        # `clk_buf_root_cell`), so pinning them is what a configured PDK looks
        # like, not a special case for the test. `BUFX1` is present in every
        # library this module builds, so the CTS lines are identical across the
        # arms and the diff carries only what the span changed.
        clk_buf="BUFX1", clk_buf_root="BUFX1")

    monkeypatch.setattr(R, "_openroad_supports_postroute_spef_repair",
                        lambda *_a, **_k: True)
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    bodies: list = []

    def fake(container, cmd, timeout=None, **kw):
        if "openroad -no_init" in cmd:
            out_dir = R._pl.pnr_dir(project)
            out_dir.mkdir(parents=True, exist_ok=True)
            script = next((Path(t) for t in cmd.split()
                           if t.endswith(".tcl")), None)
            bodies.append(script.read_text()
                          if script and script.is_file() else "")
            (out_dir / "routed.def").write_text(_ROUTED_DEF)
            (out_dir / f"{top}.def").write_text(_ROUTED_DEF)
            (out_dir / "openroad.log").write_text(_ROUTE_OK)
            lp = kw.get("log_path")
            if lp:
                Path(lp).write_text(_ROUTE_OK)
            return (0, _ROUTE_OK, "")
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake)
    R.step_pnr(project, top, pdk, "iic", "200x200", 0.30)
    assert bodies, "step_pnr never invoked openroad — the harness is broken"
    return bodies[0]


def _limits(tcl: str):
    """(area_limit, leakage_limit) from the emitted `set_opt_config`; either is
    None when that axis was not limited."""
    m = re.search(r"set_opt_config((?: -limit_sizing_\w+ [\d.]+)+)", tcl)
    if not m:
        return (None, None)
    got = dict(re.findall(r"-limit_sizing_(\w+) ([\d.]+)", m.group(1)))
    return (float(got["area"]) if "area" in got else None,
            float(got["leakage"]) if "leakage" in got else None)


def _first_command_offset(tcl: str, token: str) -> int:
    """Byte offset of the first EXECUTABLE line carrying ``token``.

    Comment-blind and `puts`-blind on purpose: the emitted script discusses
    `repair_design` in a dozen comments and prints its name in status messages,
    and a probe that cannot tell a command from a sentence about a command
    reports an ordering that is not there.
    """
    off = 0
    for line in tcl.splitlines(keepends=True):
        s = line.strip()
        if not (s.startswith("#") or s.startswith("puts ")) and token in s:
            return off
        off += len(line)
    raise AssertionError(f"no executable emitted line carries {token!r}")


def _inserted_runs(base_tcl: str, wider_tcl: str):
    """The contiguous line runs `wider_tcl` ADDS to `base_tcl`.

    Raises if anything was removed or replaced — for this fix that is itself the
    finding, since restoring a swap pool must not rewrite the script.
    """
    a = base_tcl.splitlines()
    b = wider_tcl.splitlines()
    runs = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        assert tag == "insert", (
            f"the widening did not only INSERT — it {tag}d lines: "
            f"{b[j1:j2][:5]}")
        runs.append(b[j1:j2])
    return runs


def _sizing_blocks(tmp_path: Path, monkeypatch, liberty: str):
    """The Tcl a >4X library ADDS, derived by diffing its pnr.tcl against the
    pnr.tcl the SAME project emits for a library that fits the default. Both
    runs use identical paths, so the diff is the feature and nothing else."""
    wide = _pnr_tcl(tmp_path / "w", monkeypatch, liberty=liberty)
    narrow = _pnr_tcl(tmp_path / "n", monkeypatch, liberty=NARROW)
    wide_n = wide.replace(str(tmp_path / "w"), "<P>")
    narrow_n = narrow.replace(str(tmp_path / "n"), "<P>")
    return wide, _inserted_runs(narrow_n, wide_n)


# ══════════════════ PART A — behaviour, through step_pnr ══════════════════

def test_a_library_wider_than_4x_gets_its_pool_restored_in_the_emitted_pnr_tcl(
        tmp_path, monkeypatch):
    """THE defect, reproduced at the step: with a >4X buffer family in hand the
    flow must emit the restored swap pool, or OpenROAD computes 'best
    achievable' over the truncated pool and aborts with [ERROR RSZ-0090]."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=WIDE)
    assert _limits(tcl) != (None, None), (
        "pnr.tcl carries no set_opt_config sizing limit for a library whose "
        "buffer family spans 8X area / 40X leakage")


def test_the_restored_pool_precedes_the_first_timing_driven_step(
        tmp_path, monkeypatch):
    """RSZ-0090 is reached from `global_placement -timing_driven` (gpl ->
    TimingBase::findResizeSlacks -> RepairDesign -> checkSlewLimit), and it is a
    logger_->error, so it ABORTS the script. A block emitted below
    `global_placement` never executes: measured on a real run, the abort was at
    the `global_placement` line while the block sat 262 lines under it."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=WIDE)
    cfg = _first_command_offset(tcl, "set_opt_config")
    gp = _first_command_offset(tcl, "global_placement")
    rd = _first_command_offset(tcl, "repair_design")
    assert cfg < gp, (
        "set_opt_config is emitted after global_placement; RSZ-0090 aborts "
        "there, so the restored pool would never be seen")
    assert gp < rd, "the emitted template no longer places gp before rd"


def test_the_limits_are_this_librarys_measured_span_not_a_constant(
        tmp_path, monkeypatch):
    """THE anti-blanket test. Any fixed pair of numbers makes RSZ-0090 go away
    and passes 'the violation disappeared'. It fails this: two libraries with
    different spans must produce different limits, each traceable to its own
    measured span and never below it."""
    a = _limits(_pnr_tcl(tmp_path / "a", monkeypatch, liberty=WIDE))
    b = _limits(_pnr_tcl(tmp_path / "b", monkeypatch, liberty=WIDER))
    assert a != b, (a, b)
    assert a == (_expect(8.0), _expect(40.0)), a
    assert b == (_expect(16.0), _expect(90.0)), b
    assert a[0] >= 8.0 and a[1] >= 40.0
    assert b[0] >= 16.0 and b[1] >= 90.0


def test_only_the_axis_that_exceeds_the_default_is_limited(
        tmp_path, monkeypatch):
    """Area and leakage are independent cut-offs. Relaxing the axis that already
    fits would widen the pool further than the library justifies — this is a
    restoration, not a licence."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=LEAKY)   # 3.5X area, 90X leak
    area, leak = _limits(tcl)
    assert leak == _expect(90.0), leak
    assert area is None, (
        f"the area axis fits inside the 4.0X default (measured 3.5X) and must "
        f"not be touched, but -limit_sizing_area {area} was emitted")


def test_only_structural_buffers_enter_the_span(tmp_path, monkeypatch):
    """The span is the BUFFER FAMILY's, identified the way OpenSTA identifies a
    buffer — one input, one output, the output's `function` IS that input. The
    library below carries an inverter and a NAND that are smaller and less leaky
    than every buffer; counting them would give 80/5 = 16X area and 40/0.5 = 80X
    leakage instead of the family's own 8X / 40X, and would hand the resizer a
    pool wider than anything it can legally swap between."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=WIDE_PLUS_LOGIC)
    assert _limits(tcl) == (_expect(8.0), _expect(40.0)), _limits(tcl)


def test_the_span_is_the_widest_across_the_whole_signoff_corner_set(
        tmp_path, monkeypatch):
    """Leakage span is strongly corner-dependent (measured on one real 3-corner
    open-PDK set: 16.47X at tt, 43.43X at ss, 772.4X at ff). A limit fitted to
    the typical corner still aborts at a sign-off corner, so the span has to be
    the max over every corner liberty the run will analyse. Here the PDK's own
    library and two of the three staged corners fit 4.0X; only the third does
    not, and it is the one the answer must come from."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=NARROW,
                   corner_libs={"libx_tt.lib": NARROW,
                                "libx_ff.lib": NARROW,
                                "libx_ss.lib": LEAKY})
    _area, leak = _limits(tcl)
    assert leak == _expect(90.0), (
        f"emitted {leak}: the limit does not cover the widest corner in the "
        f"set, so the run still aborts with RSZ-0090 at that corner")


def test_a_library_inside_the_default_limits_changes_the_script_not_at_all(
        tmp_path, monkeypatch):
    """A design that never had the problem must not have its optimisation
    changed. Nothing is emitted — not the limit, not the evidence block, not the
    marker.

    NEGATIVE CONTROL: this necessarily passes on e3aa9b126 too, where nothing is
    ever emitted for any library. Its green is not evidence for the tests above
    it; it exists so an over-broad fix cannot satisfy them."""
    tcl = _pnr_tcl(tmp_path, monkeypatch, liberty=NARROW)
    assert "set_opt_config" not in tcl
    assert "SIZING_LIMITS" not in tcl


def test_the_widening_touches_the_cell_pool_and_nothing_else(
        tmp_path, monkeypatch):
    """The one thing that must never happen: the fix must not move the timing
    constraint. Asserted as a DIFF over the WHOLE script — same project, same
    paths, same everything but the library's content — so 'nothing else changed'
    is measured rather than spot-checked on three literals."""
    wide, runs = _sizing_blocks(tmp_path, monkeypatch, WIDE)
    assert runs, "the two scripts are identical — the fixture exercises nothing"
    for run in runs:
        assert any("SIZING_LIMITS" in ln or "set_opt_config" in ln
                   for ln in run), (
            f"the widening added Tcl that is not part of the sizing blocks: "
            f"{run[:5]}")
    for forbidden in ("set_max_transition", "set_max_capacitance",
                      "set_max_fanout"):
        assert forbidden not in wide, forbidden


def test_the_drv_evidence_lands_after_repair_design_and_acts_on_nothing(
        tmp_path, monkeypatch):
    """The post-repair block exists to show what the restored pool bought. If it
    ever starts ACTING (another repair_design, another set_opt_config) the
    before/after number stops being an independent measurement."""
    wide, runs = _sizing_blocks(tmp_path, monkeypatch, WIDE)
    drv = [r for r in runs if any("SIZING_LIMITS_DRV" in ln for ln in r)]
    assert len(drv) == 1, [r[:2] for r in runs]
    block = drv[0]
    assert _first_command_offset(wide, "repair_design") < wide.index(
        "SIZING_LIMITS_DRV_AFTER_REPAIR"), (
        "the DRV evidence is emitted before the repair it claims to measure")
    text = "\n".join(block)
    assert "sta::max_slew_violation_count" in text
    assert "sta::max_capacitance_violation_count" in text
    assert "SIZING_LIMITS_DRV_UNMEASURED" in text  # counters absent != 0
    for line in block:
        s = line.strip()
        if s.startswith("#") or s.startswith("puts "):
            continue          # prose and printed messages are not actions
        for act in ("set_opt_config", "repair_design", "repair_timing"):
            assert act not in s, f"the evidence block acts: {s!r}"


def test_the_step_discloses_what_it_measured(tmp_path, monkeypatch, capsys):
    """A silently-widened pool is a silently-changed optimisation. The step has
    to say which library it measured and what it found on the run where it
    acts — and say nothing on the run where it does not."""
    _pnr_tcl(tmp_path / "w", monkeypatch, liberty=WIDE)
    said = capsys.readouterr().err
    assert "RESIZER SIZING LIMITS" in said, said[-1500:]
    assert "8X area" in said and "40X leakage" in said, said[-1500:]
    assert "max_transition is NOT modified" in said, said[-1500:]

    _pnr_tcl(tmp_path / "n", monkeypatch, liberty=NARROW)
    assert "RESIZER SIZING LIMITS" not in capsys.readouterr().err


# ══════ PART B — the one property with no observable outside the code ═════

def test_step_pnr_measures_the_corner_set_exactly_once(tmp_path, monkeypatch):
    """DECLARED NON-BEHAVIOURAL. Read this before counting its green.

    The cost defect is real and was measured: three consumers need the same span
    — the preamble, the DRV-report companion, and the step's own disclosure —
    and the parse is O(liberty bytes) over a whole sign-off corner set. On the
    real 3-corner sky130_fd_sc_hd set (96.9 MB) three passes took 81.47 s and
    one took 27.72 s.

    It has NO observable outside the module. The emitted pnr.tcl is
    byte-identical either way — that is the point; a fast wrong number would be
    worse than a slow right one — the disclosure line is identical, the step
    result is identical, and the only external difference is wall time, which is
    host- and load-dependent and would make a flaky assertion that did not say
    why it failed.

    So this test names the private symbol `_buffer_family_sizing_spans` and
    counts calls to it. On a tree that lacks that symbol it dies AttributeError,
    which proves nothing about behaviour. It is kept because the property is
    worth guarding against re-introduction, and it is labelled so its green is
    never read as evidence that the flow does anything observable.
    """
    real = R._buffer_family_sizing_spans
    calls = {"n": 0}

    def counting(lib_texts):
        calls["n"] += 1
        return real(lib_texts)

    monkeypatch.setattr(R, "_buffer_family_sizing_spans", counting)
    _pnr_tcl(tmp_path, monkeypatch, liberty=WIDE,
             corner_libs={"libx_tt.lib": NARROW, "libx_ss.lib": WIDER})
    assert calls["n"] == 1, (
        f"step_pnr parsed the corner set {calls['n']} times; three consumers "
        f"need the same number and the parse is O(liberty bytes) per corner")
