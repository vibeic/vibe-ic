#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P1 — multi-corner SPEF + AOCV/blackbox discovery (runner).

These exercise the DETERMINISTIC runner helpers without a live container by
stubbing _docker_exec. The heart of the fix they guard: the iic-osic-tools
`bash -lc` login BANNER (`[INFO] Final PATH variable: ...`) must NOT leak into a
discovered captable / AOCV / blackbox path (a naive `head -1` captured the
banner). Also verifies:
  * multi-corner captable discovery returns the .magic model per corner;
  * AOCV discovery is None on a PDK that ships none (honest);
  * corner-STA recipe splits SETUP(max-RC) / HOLD(min-RC);
  * the disclosure JSON logic (single- vs multi-corner) is honest.
"""
from __future__ import annotations

import sys
from pathlib import Path

from _source_pin import func_src

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P  # noqa: E402


_BANNER = ("[INFO] Final PATH variable: /foss/tools/bin:/usr/bin\n"
           "[INFO] Final PYTHONPATH variable: /usr/lib/python3.12\n")


def _mk_pdk(tmp_path):
    # tech_lef must contain '/libs.ref/' so the PDK root is derivable.
    return P.PdkConfig(
        name="sky130A",
        liberty="/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/x.lib",
        tech_lef="/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/techlef/x.tlef",
        cell_lef="/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lef/x.lef",
        cell_gds="/x.gds", site="unithd", drc_deck="/x.lydrc",
        metal_prefix="met")


# ---------------------------------------------------------------------------
def test_container_ls_paths_filters_login_banner(monkeypatch):
    # The banner lines start with '[INFO]' not '/', and must be dropped; only
    # the real path line (containing must_contain) survives.
    def fake_exec(container, cmd, timeout=20, **_):
        return (0, _BANNER +
                "/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.nom.magic\n",
                "")
    monkeypatch.setattr(P, "_docker_exec", fake_exec)
    hits = P._container_ls_paths("c", "expr", "rules.openrcx")
    assert hits == [
        "/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.nom.magic"]
    # a query that filters on a banner-only token still returns nothing
    assert P._container_ls_paths("c", "expr", "no-such-token") == []


def test_discover_captables_picks_magic_per_corner(monkeypatch):
    def fake_exec(container, cmd, timeout=20, **_):
        # emulate `ls` for whichever corner is embedded in the expr
        for corner in ("min", "nom", "max"):
            if f".{corner}.magic" in cmd or f".{corner} " in cmd or cmd.endswith(f".{corner}"):
                return (0, _BANNER +
                        f"/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.{corner}.magic\n"
                        f"/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.{corner}.spef_extractor\n",
                        "")
        return (0, _BANNER, "")
    monkeypatch.setattr(P, "_docker_exec", fake_exec)
    caps = P._discover_openrcx_captables(_mk_pdk(Path("/tmp")), "c")
    assert set(caps) == {"min", "nom", "max"}
    for corner, path in caps.items():
        assert path.endswith(f".{corner}.magic")  # prefers the .magic model
        assert "[INFO]" not in path                # banner never leaks


def test_discover_captables_empty_when_none(monkeypatch):
    monkeypatch.setattr(P, "_docker_exec", lambda c, cmd, timeout=20, **_: (0, _BANNER, ""))
    assert P._discover_openrcx_captables(_mk_pdk(Path("/tmp")), "c") == {}


def test_aocv_discovery_none_when_pdk_ships_none(monkeypatch, tmp_path):
    # no design-supplied .aocv, container ls returns only the banner => None.
    monkeypatch.setattr(P, "_docker_exec", lambda c, cmd, timeout=20, **_: (0, _BANNER, ""))
    assert P._discover_aocv_table(tmp_path, _mk_pdk(tmp_path), "c") is None


def test_aocv_discovery_finds_design_supplied(monkeypatch, tmp_path):
    d = tmp_path / "input" / "constraints"
    d.mkdir(parents=True)
    (d / "corners.aocv").write_text("* aocv table *\n")
    # design-supplied is found WITHOUT touching the container.
    monkeypatch.setattr(P, "_docker_exec",
                        lambda c, cmd, timeout=20, **_: (_ for _ in ()).throw(
                            AssertionError("should not hit container")))
    got = P._discover_aocv_table(tmp_path, _mk_pdk(tmp_path), "c")
    assert got is not None and got.endswith("corners.aocv")


def test_blackbox_discovery_prefers_plain(monkeypatch):
    def fake_exec(container, cmd, timeout=20, **_):
        return (0, _BANNER +
                "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd__blackbox.v\n"
                "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd__blackbox_pp.v\n",
                "")
    monkeypatch.setattr(P, "_docker_exec", fake_exec)
    bb = P._discover_blackbox_verilog(_mk_pdk(Path("/tmp")), "c")
    assert "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd__blackbox.v" in bb
    # the _pp variant of the SAME family is dropped in favour of the plain one
    assert not any(b.endswith("_pp.v") for b in bb)
    assert all("[INFO]" not in b for b in bb)


# ---- structure of the corner-aware STA + multi-corner extraction recipe ----
def test_corner_sta_recipe_splits_setup_max_hold_min():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    window = func_src(src, "_emit_corner_spef_sta")
    assert 'setup_corner = ("max"' in window   # setup at slow/max-RC
    assert 'hold_corner = ("min"' in window    # hold at fast/min-RC
    assert 'report_worst_slack' in window
    assert '"SETUP"' in window and '"HOLD"' in window
    # the report must state which LIBERTY each corner was analysed with, and
    # must ask OpenSTA for DRV — N corner sections over one silently-shared
    # library used to be indistinguishable from genuine multi-corner sign-off,
    # and max_slew violations could not appear in this report at all.
    assert "# corner_liberty:" in window
    assert "distinct_corner_libraries" in window
    assert "_report_check_types_tcl(rpt_c)" in window


def test_multicorner_extract_recipe_loops_corners():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    window = func_src(src, "_emit_spef_corners")
    # one OpenROAD run reads the DEF once then extract+write per corner
    assert "extract_parasitics -ext_model_file" in window
    assert "write_spef" in window
    assert "define_process_corner" in window


def test_multicorner_disclosure_is_honest():
    # the stance JSON must carry both the multi-corner claim AND an honest
    # single-corner disclosure branch.
    #
    # #563 r3 — the fallback text was re-derived. It used to read
    # "SINGLE-CORNER (nom) only — this PDK did not ship the min/max OpenRCX
    # captables", which asserted a CAUSE the code never checked (measured
    # counter-example: the failing run's own log named all three captables it
    # read). "Honest" now means it reports the observation and names no cause,
    # so this assertion tracks the observation wording instead of the old
    # PDK-blaming sentence.
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("multi_corner_spef_stance.json")
    window = src[i:i + 8000]
    assert "SINGLE-CORNER only (extracted:" in window   # honest fallback text
    assert "NOT attributed to the PDK" in window
    assert '"multi_corner"' in window
    assert '"setup_corner"' in window and '"hold_corner"' in window
    # ...and the corner->liberty resolution, so the corner COUNT can never be
    # read as a library count.
    assert '"corner_library_resolution"' in window
