"""v1.5.x regression — SYNTHESIS don't-use from the PDK's own
``synth_excluded.cells`` (librelane), the synthesis sibling of the PnR
``set_dont_use``. Pins _synth_dont_use_cells so area-mode ABC can never again
map DATA logic onto clock / delay / low-power-isolation / probe / scan cells
(the sha256 x sky130A post-route setup-violation root cause: 159
lpflow_isobufsrc + clkdlybuf4s50 + a 13.3 ns ss clkinv on the address-decode
path). Docker-free: _docker_exec is monkeypatched."""
import importlib

p = importlib.import_module("phase3_one_shot_runner")


class _PC:
    liberty = ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
               "sky130_fd_sc_hd__tt_025C_1v80.lib")


_SYNTHEX = (
    "# clock buffers/inverters (used in CTS)\n"
    "sky130_fd_sc_hd__clkbuf*\n"
    "sky130_fd_sc_hd__clkinv*\n"
    "# clock delay buffers\n"
    "sky130_fd_sc_hd__clkdlybuf*\n"
    "# low power flow\n"
    "sky130_fd_sc_hd__lpflow_*\n"
    "# probe\n"
    "sky130_fd_sc_hd__probe*\n"
    "# scan\n"
    "sky130_fd_sc_hd__s*\n"
)
_LIBCELLS = "\n".join([
    "sky130_fd_sc_hd__clkbuf_1",
    "sky130_fd_sc_hd__clkinv_1",
    "sky130_fd_sc_hd__clkdlybuf4s50_1",
    "sky130_fd_sc_hd__lpflow_isobufsrc_1",
    "sky130_fd_sc_hd__probe_p_8",
    "sky130_fd_sc_hd__sdfxtp_1",
    "sky130_fd_sc_hd__and2_0",       # regular — MUST stay usable
    "sky130_fd_sc_hd__inv_2",        # regular — MUST stay usable
    "sky130_fd_sc_hd__dfxtp_1",      # regular FF — MUST stay usable
]) + "\n"


def _mk_exec(synthex_rc=0, synthex_txt=_SYNTHEX, cells_txt=_LIBCELLS):
    def fake(container, cmd, *a, **kw):
        if cmd.strip().startswith("cat "):
            return (synthex_rc, synthex_txt if synthex_rc == 0 else "", "")
        return (0, cells_txt, "")           # the liberty cell-name grep
    return fake


def test_expands_globs_excludes_specialty_keeps_regular(monkeypatch):
    monkeypatch.setattr(p, "_docker_exec", _mk_exec())
    du = set(p._synth_dont_use_cells(_PC(), "c"))
    # specialty cells that ruined the sha256 critical path are excluded
    for c in ("sky130_fd_sc_hd__clkbuf_1", "sky130_fd_sc_hd__clkinv_1",
              "sky130_fd_sc_hd__clkdlybuf4s50_1",
              "sky130_fd_sc_hd__lpflow_isobufsrc_1",
              "sky130_fd_sc_hd__probe_p_8", "sky130_fd_sc_hd__sdfxtp_1"):
        assert c in du, c
    # ordinary logic + flops stay usable (never over-excluded)
    for c in ("sky130_fd_sc_hd__and2_0", "sky130_fd_sc_hd__inv_2",
              "sky130_fd_sc_hd__dfxtp_1"):
        assert c not in du, c


def test_empty_when_pdk_ships_no_synth_excluded(monkeypatch):
    # NONFATAL, backward-compatible: no file → no flags → legacy flow unchanged
    monkeypatch.setattr(p, "_docker_exec", _mk_exec(synthex_rc=1))
    assert p._synth_dont_use_cells(_PC(), "c") == []


def test_empty_when_liberty_not_under_libs_ref(monkeypatch):
    class _Bad:
        liberty = "/somewhere/custom/foo.lib"
    monkeypatch.setattr(p, "_docker_exec", _mk_exec())
    assert p._synth_dont_use_cells(_Bad(), "c") == []
