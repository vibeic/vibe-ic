"""ORGANIC #581 — the #557 post-route SPEF repair block emitted into
pnr.tcl was not valid Tcl: a plain-string fragment kept an
f-string-escaped `}}` (→ `]}}`) and a multi-line `catch {...}` was nested
inside the bracketed `if {[catch {` expression. OpenROAD died with
`missing close-bracket in expression "[catch { catch {def..."` AFTER
detailed route fully converged, so GDS / final DEF were never written —
on EVERY phase3 run (the block is emitted unconditionally).

Fixes:
(a) the SPEF repair block is restructured as strictly sequential
    one-line `if {[catch {...} e]} {...}` statements;
(b) the COMPLETE pnr.tcl template is extracted into the pure builder
    `_build_pnr_tcl_text` (v0.1.49 doctrine) and validated here by an
    ACTUAL tclsh parse/eval — string-content assertions alone proved
    insufficient (the broken block passed a content-only field audit).

The tclsh harness (`_pnr_tcl_stub.STUB`) makes every OpenROAD command a
no-op while the Tcl PARSER still sees the real structure. The four
primitives whose RETURN VALUE the deck reads -- `utl::redirectString*`,
`utl::report`, `report_dont_use` and `[ord::get_db] findMaster` -- are
modelled with real semantics, because a no-op is not a stand-in for a
command a block branches on: with `unknown` alone the v1.19.95 CTS
legality block's own "the capture did not work" guard fired and the deck
aborted 316 lines into 1,717, so 82% of it stopped being parsed at all.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pnr_tcl_stub import STUB as _STUB  # noqa: E402


def _run_tclsh(script_path: Path):
    return _pr.run([tclsh, str(script_path)],
                          capture_output=True, text=True)










# ── the issue's exact 現象: full pnr.tcl must survive a real tclsh ──────────







@needs_tclsh
def test_harness_catches_the_v0_3_38_broken_shape(tmp_path):
    """NEGATIVE pin: the v0.3.38 broken emission (extra `}` after the
    write_spef bracket, verbatim from the field repro) MUST fail this
    harness — proving the tclsh eval actually catches the bug class that
    content-only assertions missed."""
    broken = (
        "set _prs_rules captable\n"
        "if {$_prs_rules ne \"\"} {\n"
        "  if {[catch {\n"
        "    catch {define_process_corner -ext_model_index 0 X}\n"
        "    extract_parasitics -ext_model_file $_prs_rules\n"
        "    if {[catch {write_spef /out/x.spef} _w]}} "
        "{ puts \"W: $_w\" }\n"
        "    puts \"SPEF_REPAIR_COMPLETE\"\n"
        "  } _e]} {\n"
        "    puts \"SPEF_REPAIR_NONFATAL: $_e\"\n"
        "  }\n"
        "} else {\n"
        "  puts \"SKIP\"\n"
        "}\n"
    )
    script = tmp_path / "broken.tcl"
    script.write_text(_STUB + broken)
    result = _run_tclsh(script)
    assert result.returncode != 0
    assert "close-bracket" in (result.stderr + result.stdout)


# ── ORGANIC #581 round-3 — measure-only: NO repair after detailed route ─────







# ── the harness is a STAND-IN, not a bypass: prove it both ways ────────────
