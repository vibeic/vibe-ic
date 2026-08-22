"""Bidirectional negative control for the Liberty-evidence corner classifier.

The base checker mines the hold Tcl's *line text* (filename + any echoed
banner) for the standard ss/tt/ff designator family. A PDK whose corner *codes*
are not in that family (a best/worst-case-interconnect naming, a foundry code)
leaves a genuine fast-corner hold sign-off unrecognised -> a false
NO_FEED_CORNER. The fix opens the Liberty the `read_liberty` line points at and
classifies it from the Liberty's OWN `operating_conditions` /
`default_operating_conditions` -- the authoritative statement of the corner
that feeds the analysis -- WITHOUT trusting a self-declared `process=FF` banner.

The Liberty is referenced by an ABSOLUTE path with a designator-free filename,
and evaluate() is called with NO base_dir, so the SAME test runs unmodified on
the pre-fix single-arg signature and the post-fix one. A guard asserts the
constructed path carries no standard designator, so the control can never be
silently defeated by a tmp base that happens to spell one.

  FORWARD (fail pre / pass post)   fast Liberty by evidence -> PASS.
  FORWARD (fail pre / pass post)   the _liberty_corner_from_file unit itself.
  INVARIANT (pass pre AND post)    slow Liberty -> still FAIL (anti-blanket).
  INVARIANT (pass pre AND post)    standard _ff_ filename -> still PASS.
  INVARIANT (pass pre AND post)    ambiguous Liberty -> still NO_FEED_CORNER.
  INVARIANT (pass pre AND post)    `process=FF` banner text alone -> no corner.
"""
import importlib

mod = importlib.import_module("hold_corner_coverage_check")


def _lib(op_cond_name, *, default=True, extra_block=None):
    """A minimal but well-formed Liberty header carrying operating conditions."""
    hot = op_cond_name in ("fast", "ff")
    volt = "1.980000" if hot else "1.620000"
    temp = "-40.000000" if hot else "125.000000"
    blocks = f"""\
  operating_conditions ({op_cond_name}) {{
    process : 1.000000;
    temperature : {temp};
    voltage : {volt};
  }}
"""
    if extra_block:
        blocks += f"""\
  operating_conditions ({extra_block}) {{
    process : 1.000000;
    temperature : 25.000000;
    voltage : 1.800000;
  }}
"""
    dflt = f"  default_operating_conditions : {op_cond_name};\n" if default else ""
    return f"""library (widget_stdcells) {{
  delay_model : table_lookup;
  nom_process : 1.000000;
  nom_voltage : {volt};
  nom_temperature : {temp};
{dflt}{blocks}}}
"""


def _hold_tcl(lib_abspath):
    """A hold sign-off script whose only corner clue is which Liberty it reads.
    A self-declared banner is present on purpose (it must NOT decide anything)."""
    return f"""\
read_liberty {lib_abspath}
read_verilog design.v
link_design widget
read_sdc design.sdc
puts "=== HOLD corner: process=FF liberty={lib_abspath} ==="
report_worst_slack -min
report_checks -path_delay min -group_path_count 3
"""


def _mk(tmp_path, lib_name, lib_text):
    d = tmp_path / "wk"
    d.mkdir()
    lib = d / lib_name
    lib.write_text(lib_text)
    # Control-integrity guard: the ABSOLUTE Liberty path must carry NO standard
    # designator, else the pre-fix filename miner could classify it and the
    # forward control would be moot. _corners_in exists in both versions.
    assert mod._corners_in(f"read_liberty {lib}") == [], \
        f"tmp path leaks a corner designator, control invalid: {lib}"
    return lib


def _run(tmp_path, lib_name, lib_text):
    lib = _mk(tmp_path, lib_name, lib_text)
    # NO base_dir: the call is valid on both the pre-fix and post-fix signatures.
    return mod.evaluate(_hold_tcl(str(lib)))


# ── FORWARD: fail on pre-fix, pass after ─────────────────────────────────────
def test_forward_hi_corner_by_evidence_passes(tmp_path):
    verdict, rc, rep = _run(tmp_path, "pdkcode_hivt.lib", _lib("fast"))
    assert verdict == "PASS", rep
    assert rc == 0
    assert rep.get("reason") == "HOLD_AT_FF"
    assert rep.get("hold_liberty_corners") == ["FF"]
    assert rep.get("corner_basis") == "liberty_feed"


def test_forward_lo_corner_classified_and_rejected(tmp_path):
    # Post-fix the slow Liberty is CLASSIFIED (SS) and rejected — not merely
    # unrecognised. Pre-fix there is no such key, so this forward test fails.
    verdict, rc, rep = _run(tmp_path, "pdkcode_lovt.lib", _lib("slow"))
    assert verdict == "FAIL"
    assert rep.get("hold_liberty_corners") == ["SS"]
    assert rep.get("reason") == "HOLD_NOT_AT_FF"


# ── INVARIANT: correct both before and after (anti-blanket / no-regression) ──
def test_invariant_lo_corner_is_never_a_pass(tmp_path):
    # The one control that catches a fix that just greens everything: a slow
    # hold sign-off must stay FAIL — true on pre-fix and post-fix alike.
    verdict, rc, rep = _run(tmp_path, "pdkcode_lovt.lib", _lib("slow"))
    assert verdict == "FAIL", rep
    assert rc == 1


def test_invariant_ff_filename_without_liberty_on_disk_passes(tmp_path):
    tcl = ("read_liberty stdcells__ff_1v98_n40C.lib\n"
           "report_worst_slack -min\nreport_checks -path_delay min\n")
    verdict, rc, rep = mod.evaluate(tcl)
    assert verdict == "PASS", rep


def test_invariant_ambiguous_liberty_no_default_is_not_a_pass(tmp_path):
    # Two operating_conditions, no default -> the reader refuses to guess, so a
    # designator-free filename remains NO_FEED_CORNER, not a false pass. Holds
    # on pre-fix (no reader at all) and post-fix (reader declines to guess).
    verdict, rc, rep = _run(
        tmp_path, "pdkcode_multi.lib",
        _lib("fast", default=False, extra_block="slow"))
    assert verdict == "FAIL", rep
    assert rep.get("reason") == "NO_FEED_CORNER"


def test_invariant_banner_process_ff_alone_is_not_trusted():
    assert mod._corners_in("=== HOLD corner: process=FF liberty=x_bci.lib ===") == []
