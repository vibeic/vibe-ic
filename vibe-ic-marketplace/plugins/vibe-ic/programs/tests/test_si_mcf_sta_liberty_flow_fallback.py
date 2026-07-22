"""si_mcf_sta — resolve the timing liberty from the flow's OWN read_liberty when
no liberty is staged under input/pdk/liberty/, and hard-ERROR clearly when none
is resolvable (never a malformed `read_liberty <dir>`).

Field observation (caravel_user_project × sky130A): the caravel harness never
stages a liberty under input/pdk/liberty/ — the sky130A PDK liberty lives only
inside the EDA container (/foss/pdks/...). si_mcf_sta's liberty fallback set
`liberty = ""`, and `_abs("")` resolves to the project DIR, so the emitted
`read_liberty <project_dir>` made OpenSTA fail ("line 1, syntax error"). The
whole SI multi-corner STA then reported a SELF-INFLICTED ERROR (windows_rc=1,
nets_with_windows=0, null slacks) instead of a real verdict — even though the
design meets SI timing with large margin.

Fix: recover the liberty the phase-3 flow ALREADY resolved (the first
`read_liberty <path>` in the PnR / STA TCLs — a container path that passes
through the translation unchanged); and if a liberty is genuinely unresolvable,
emit a CLEAR, NAMED ERROR verdict rather than a malformed path.

chip/PDK-AGNOSTIC: returns whatever liberty the flow used, no PDK/cell literal.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parent.parent / "si_mcf_sta.py"
_spec = importlib.util.spec_from_file_location("_si_mcf_sta_libfix", _PROG)
M = importlib.util.module_from_spec(_spec)
sys.modules["_si_mcf_sta_libfix"] = M
_spec.loader.exec_module(M)


def _pnr(project: Path, tcl_body: str) -> None:
    d = project / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pnr.tcl").write_text(tcl_body)


def test_resolve_flow_liberty_from_pnr_tcl(tmp_path):
    p = tmp_path / "proj"
    _pnr(p, "read_verilog x.v\nlink_design top\n"
            "read_liberty /foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
            "sky130_fd_sc_hd__tt_025C_1v80.lib\n")
    lib = M._resolve_flow_liberty(p)
    assert lib and lib.endswith("sky130_fd_sc_hd__tt_025C_1v80.lib"), lib


def test_resolve_flow_liberty_skips_comments_and_strips_braces(tmp_path):
    p = tmp_path / "proj"
    _pnr(p, "# read_liberty /commented/should_not_match.lib\n"
            "read_liberty {/foss/pdks/x/lib/real_typ.lib}\n")
    assert M._resolve_flow_liberty(p) == "/foss/pdks/x/lib/real_typ.lib"


def test_resolve_flow_liberty_from_sta_tcl_when_no_pnr(tmp_path):
    p = tmp_path / "proj"
    d = p / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True)
    (d / "sta_spef_setup.tcl").write_text(
        "read_liberty /foss/pdks/y/lib/typ.lib\nread_spef z.spef\n")
    assert M._resolve_flow_liberty(p) == "/foss/pdks/y/lib/typ.lib"


def test_resolve_flow_liberty_none_when_absent(tmp_path):
    p = tmp_path / "proj"
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    assert M._resolve_flow_liberty(p) is None


def test_run_errors_clearly_when_no_liberty_anywhere(tmp_path):
    """NEGATIVE CONTROL: a genuinely unresolvable liberty yields a CLEAR, NAMED
    ERROR verdict — never a vacuous pass, never an opaque `read_liberty <dir>`
    OpenSTA crash. No staged input/pdk/liberty AND no read_liberty in any
    phase-3 TCL. The guard returns before any container exec, so no EDA
    container is needed."""
    p = tmp_path / "proj"
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    rep = M.run(p, container="dummy_never_exec")
    assert rep["verdict"] == "ERROR", rep
    assert "liberty" in rep.get("error", "").lower(), rep
    j = json.loads((p / "reports" / "phase3" / "si_mcf_sta.json").read_text())
    assert j["verdict"] == "ERROR"
    # The guard fires ONLY on an unresolvable liberty: with a flow read_liberty
    # present the fallback resolves it (proven by the resolution tests above),
    # so `if not liberty` is False and this ERROR path is bypassed.
