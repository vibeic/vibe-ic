"""A per-corner STA over a design that did not LINK must not count as a corner.

THE DEFECT. `_emit_multi_corner_sta`'s entire success test was::

    rc, out, err = _docker_exec(container, cmd, marker=tcl_c, outputs=[rpt])
    if rc != 0 or not rpt.is_file():
        ...failed...
    else:
        any_emitted = True

i.e. "the tool exited 0 and a file appeared" was accepted as "this corner was
measured". OpenSTA does not cooperate with that reading. An instance whose
master is absent from every `read_liberty` is resolved to a BLACK BOX --
OpenSTA prints ``Warning 198: ... module <M> not found. Creating black box for
<inst>.`` and **exits 0**. A black box has no timing arcs, so every path
through it leaves the graph: `report_checks` prints ``No paths found`` and
`report_wns` / `report_tns` print ``0.00``.

The artefact is then byte-indistinguishable from a genuinely clean corner, and
it errs OPTIMISTIC -- which is the dangerous direction. Measured on a real
cell: reading the wrong technology's Liberty against the netlist black-boxed
every standard cell and produced ``wns 0.00`` at SS/TT/FF, where the
correctly-linked run of the SAME netlist reported ``wns -33.88 ns`` at SS. The
unlinked run looked BETTER than the design is.

This is chip-AGNOSTIC. Any netlist/Liberty disagreement lands here: a hard
macro whose `.lib` was never staged, a partially-staged corner set, a renamed
cell, a PDK mismatch.

The fix degrades an unlinked corner to ABSENT, which is the same #437(c)
doctrine the `rc != 0` branch already follows: a corner that could not be
measured leaves NO report, never a falsely-clean one.

BIDIRECTIONAL. `test_unlinked_corner_is_not_emitted` is the forward control --
it FAILS against the byte-identical pre-fix file. `test_linked_corner_still_
emitted` and `test_helper_returns_empty_on_clean_log` are the REVERSE control:
a healthy run must still emit its corners, so the fix cannot be "tighten until
the count reaches zero".
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

TOP = "my_core"

# Verbatim OpenSTA output shape (2.7.0) for an unresolved master.
BLACKBOX_LOG = """OpenSTA 2.7.0 f21d4a3878 Copyright (c) 2026, Parallax Software, Inc.
Warning 198: /w/{t}_synth.v line 3970, module foo_fd_sc__clkinv_1 not found. Creating black box for _3145_.
Warning 198: /w/{t}_synth.v line 4094, module foo_fd_sc__nand2_1 not found. Creating black box for _3176_.
Warning 198: /w/{t}_synth.v line 4099, module foo_fd_sc__mux2_1 not found. Creating black box for _3177_.
""".format(t=TOP)

CLEAN_LOG = """OpenSTA 2.7.0 f21d4a3878 Copyright (c) 2026, Parallax Software, Inc.
Warning: constraint.sdc line 4, set_input_delay on clock port.
"""

# What OpenSTA writes when everything was black-boxed: the could-not-measure
# state that reads as measured-clean.
UNLINKED_RPT = "No paths found.\ntns max 0.00\nwns max 0.00\n"
LINKED_RPT = "Startpoint: r1\n  -33.88   slack (VIOLATED)\ntns max -17599.70\nwns max -33.88\n"


def _project(tmp_path):
    """Minimal tree `_multi_corner_sta_inputs` accepts as post-route."""
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    (pnr / f"{TOP}_pnr.v").write_text("// routed\n")
    return tmp_path


def _libs(tmp_path):
    """One Liberty that classifies to a single corner, so exactly one report
    is attempted and the assertions are unambiguous."""
    libdir = tmp_path / "libs"
    libdir.mkdir(parents=True, exist_ok=True)
    lib = libdir / "foo_fd_sc__ss_125C_4v50.lib"
    lib.write_text("/* liberty */\n")
    return [lib]


def _install_fake_sta(monkeypatch, out_dir, log_text, rpt_text, corner):
    """Stand in for the container call: write BOTH artefacts OpenSTA writes and
    return rc=0, exactly as OpenSTA does when it black-boxes."""
    def fake_exec(container, cmd, marker=None, outputs=None, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"sta_{corner}.log").write_text(log_text)
        (out_dir / f"sta_{corner}.rpt").write_text(rpt_text)
        return 0, "", ""
    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: str(p))


# ── helper, both directions ──────────────────────────────────────────────────
def test_helper_finds_blackboxed_masters(tmp_path):
    log = tmp_path / "sta_SS.log"
    log.write_text(BLACKBOX_LOG)
    assert R._sta_blackboxed_masters(log) == [
        "foo_fd_sc__clkinv_1", "foo_fd_sc__mux2_1", "foo_fd_sc__nand2_1"]


def test_helper_returns_empty_on_clean_log(tmp_path):
    """REVERSE CONTROL: an ordinary log must not be read as black-boxed."""
    log = tmp_path / "sta_SS.log"
    log.write_text(CLEAN_LOG)
    assert R._sta_blackboxed_masters(log) == []


def test_helper_fails_open_when_log_absent(tmp_path):
    """No log is not evidence of black-boxing — this check may only ever ADD a
    finding, never invent one."""
    assert R._sta_blackboxed_masters(tmp_path / "nope.log") == []


# ── the forward control: FAILS against the pre-fix file ──────────────────────
def test_unlinked_corner_is_not_emitted(tmp_path, monkeypatch):
    project = _project(tmp_path)
    out_dir = tmp_path / "per_corner"
    out_dir.mkdir(parents=True, exist_ok=True)
    _install_fake_sta(monkeypatch, out_dir, BLACKBOX_LOG, UNLINKED_RPT, "SS")
    notes = []

    emitted = R._emit_multi_corner_sta(
        project, TOP, _pdk(), "fake-container",
        _libs(tmp_path), out_dir, notes)

    assert emitted is False, (
        "a fully black-boxed (unlinked) design was accepted as a measured "
        "corner: 'rc==0 and a file appeared' is not evidence of timing")
    assert not (out_dir / "sta_SS.rpt").is_file(), (
        "the falsely-clean report survived; an unmeasurable corner must "
        "degrade to ABSENT (#437c), not to 0.00 slack")
    assert any("UNLINKED" in n for n in notes), \
        f"the failure was not disclosed in notes: {notes}"


# ── the reverse control: must STILL pass ─────────────────────────────────────
def test_linked_corner_still_emitted(tmp_path, monkeypatch):
    """A healthy run is untouched by the fix — this is what stops the fix from
    being 'tighten the filter until the count is zero'."""
    project = _project(tmp_path)
    out_dir = tmp_path / "per_corner"
    out_dir.mkdir(parents=True, exist_ok=True)
    _install_fake_sta(monkeypatch, out_dir, CLEAN_LOG, LINKED_RPT, "SS")
    notes = []

    emitted = R._emit_multi_corner_sta(
        project, TOP, _pdk(), "fake-container",
        _libs(tmp_path), out_dir, notes)

    assert emitted is True, "a cleanly-linked corner must still be emitted"
    assert (out_dir / "sta_SS.rpt").is_file(), \
        "the fix deleted a legitimate corner report"
    assert "-33.88" in (out_dir / "sta_SS.rpt").read_text(), \
        "the real slack number was not preserved"
    assert not any("UNLINKED" in n for n in notes), \
        f"a clean run was reported as unlinked: {notes}"


def _pdk():
    """Smallest PdkConfig the emitter reads (macro_libs + the paths it stamps)."""
    return R.PdkConfig(
        name="testpdk",
        liberty="/w/lib.lib",
        tech_lef="/w/tech.lef",
        cell_lef="/w/cells.lef",
        cell_gds="/w/cells.gds",
        site="unit",
        drc_deck="/w/drc.lydrc",
        metal_prefix="met",
    )


# ── a MENTION of the warning is not the warning (vibe-ic#731) ────────────────
#
# `_STA_BLACKBOX_RE` was run over the whole log, comments included, so a line
# RESTATING the warning read as OpenSTA ISSUING it. A per-corner log is not HDL,
# but nothing keeps HDL out of one — a flow that folds the netlist into its
# transcript, or a reader echoing the offending source line, puts `//` and
# `/* */` text in here.
#
# The damage runs OPPOSITE to the defect this file opens with. There, a missed
# warning kept a falsely-clean corner. Here, a phantom master makes
# `_emit_multi_corner_sta` `rpt.unlink()` a corner report that is REAL and
# record that the design did not link, so a mention DESTROYS post-route
# sign-off data. Both directions are asserted below, on the RETURNED masters.

BANNER = (
    "OpenSTA 2.7.0 f21d4a3878 Copyright (c) 2026, Parallax Software, Inc.\n"
    "License GPLv3: GNU GPL version 3 <http://gnu.org/licenses/gpl.html>\n")

REAL_WARNING = (
    "Warning 198: /w/{t}_synth.v line 3970, module foo_fd_sc__clkinv_1 "
    "not found. Creating black box for _3145_.\n").format(t=TOP)

# The same two sentences, written ABOUT the tool instead of BY it.
COMMENTED_LOG = BANNER + (
    "// module foo_fd_sc__nand2_1 not found. Creating black box for _3176_.\n"
    "/* module foo_fd_sc__mux2_1 not found. Creating black box for _3177_. */\n")


def test_a_commented_warning_is_not_read_as_a_warning(tmp_path):
    """FORWARD CONTROL — FAILS against the pre-fix helper, which returns
    ['foo_fd_sc__mux2_1', 'foo_fd_sc__nand2_1'] for this text and would delete
    a healthy corner report on the strength of two comments."""
    log = tmp_path / "sta_SS.log"
    log.write_text(COMMENTED_LOG)
    assert R._sta_blackboxed_masters(log) == []


def test_a_real_warning_beside_a_commented_one_is_still_reported(tmp_path):
    """REVERSE CONTROL — the strip may not silence the thing it guards. Losing
    a genuine Warning 198 restores the falsely-clean corner outright."""
    log = tmp_path / "sta_SS.log"
    log.write_text(COMMENTED_LOG + REAL_WARNING)
    assert R._sta_blackboxed_masters(log) == ["foo_fd_sc__clkinv_1"]


def test_the_banner_url_does_not_reach_the_next_line(tmp_path):
    """MEASURED on 64 real per-corner logs on a fleet host: `//` appeared on 50
    lines and every one was this GPL banner URL — none was a warning line. A
    strip written with DOTALL would swallow the file from that URL onward and
    report NO masters at all, which is the falsely-clean corner again."""
    log = tmp_path / "sta_SS.log"
    log.write_text(BANNER + REAL_WARNING)
    assert R._sta_blackboxed_masters(log) == ["foo_fd_sc__clkinv_1"]
