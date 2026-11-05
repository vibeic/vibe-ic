"""Step 31 extracts the layout with the physical views place-and-route used.

MEASURED on a pad-ring die (gf180mcuD, IC path, 2026-09-29): a step-31 LVS in
a process that had not run place-and-route (a bounded `--entry-step 31`
window starts from `_detect_pdk`) read no IO LEF and the distribution tech LEF
instead of the via-legalized one.  Magic then loaded every pad master from the
PDK's `mag/` library as a full transistor-level layout, both power-aware
compares mismatched and the plain compare crashed netgen (rc 139).  The same
DEF matched uniquely inside the run that routed it.

Pinned here:
* the bounded window restores the tech LEF, the LEFs PnR read and the pad
  library GDS views from the run's own records before anything reads the PDK
  (the GDS admission basis hashes it; step 31 extracts with it);
* a tech-LEF record that does not verify refuses the window (NOT_MEASURED,
  named) and the unverified file never becomes a macro LEF;
* a window that routes again (`pnr`, `enclosing_pnr`, `enclosing_phase3`)
  restores nothing;
* an extraction that read a placed master from a library path stops before
  netgen with NOT_MEASURED naming the master; a clean extraction reaches it.
"""
from __future__ import annotations

import hashlib
import importlib
import json

import pytest
from pathlib import Path

mod = importlib.import_module("phase3_one_shot_runner")

_MOVED = "/elsewhere/run/proj"          # where the records were written
_IO_LEF = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/lef/gf180mcu_fd_io__fill1.lef"
_IO_GDS = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/gds/gf180mcu_fd_io.gds"


def _pdk():
    """A PDK object as `_detect_pdk` returns it: distribution views only."""
    return mod.PdkConfig(name="calpdk", liberty="/pdk/lib/cells.lib",
                         tech_lef="/pdk/techlef/cells__nom.tlef",
                         cell_lef="/pdk/lef/cells.lef", cell_gds=None,
                         site="core", drc_deck=None)


def _recorded_run(tmp_path: Path, *, sha_ok: bool = True):
    project = tmp_path / "proj"
    pnr = mod._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    staged = pnr / "active_via_legalized.tlef"
    staged.write_text("VERSION 5.8 ;\nEND LIBRARY\n")
    sha = hashlib.sha256(staged.read_bytes()).hexdigest()
    pdk = _pdk()
    reports = project / "reports"
    (reports / "phase3").mkdir(parents=True)
    moved_tlef = f"{_MOVED}/phase3/stage3/pnr/active_via_legalized.tlef"
    (reports / "pdk_via_patch_legalization.json").write_text(json.dumps({
        "status": "APPLIED", "source_tech_lef": pdk.tech_lef,
        "derived_tech_lef": moved_tlef,
        "derived_sha256": sha if sha_ok else "0" * 64}))
    (reports / "phase3/physical_view_inventory.json").write_text(json.dumps({
        "schema": "vibe-ic/physical-view-inventory/1",
        "read_lef_paths": [moved_tlef, pdk.cell_lef, _IO_LEF]}))
    (reports / "phase3/io_pad_chip_top.json").write_text(json.dumps({
        "verdict": "WROTE", "chip_top_verilog": "phase3/chip_top_io.v"}))
    return project, pdk






def test_local_checkpoint_restores_installed_pad_gds(tmp_path, monkeypatch):
    project, pdk = _recorded_run(tmp_path)
    calls = []

    def discover(view, container):
        calls.append(container)
        return [_IO_LEF], [_IO_GDS]

    monkeypatch.setattr(mod, "_discover_padring_io_views", discover)
    result = mod._restore_recorded_physical_views(project, pdk, "")
    assert calls == [""]
    assert _IO_GDS in pdk.macro_gds
    assert result["macro_gds"] == [_IO_GDS]






# --- the extraction guard ----------------------------------------------------

_DEF = ("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 2 ;\n"
        "    - u_inv gf180mcu_fd_sc_mcu7t5v0__inv_1 + PLACED ( 0 0 ) N ;\n"
        "    - u_fill gf180mcu_fd_io__fill1 + FIXED ( 0 0 ) N ;\n"
        "END COMPONENTS\nPINS 1 ;\n- a + NET a ;\nEND PINS\n"
        "NETS 1 ;\n- a + ROUTED met1 ;\nEND NETS\nEND DESIGN\n")
#: Magic's own line, as the calibration log `cal_views_magic_positive.log`
#: records it for the same master.
_LIBRARY_READ = ("Cell gf180mcu_fd_io__fill1 read from path "
                 "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/mag\n")


def _extract(tmp_path, monkeypatch, magic_says: str):
    project = tmp_path / "proj"
    pdk = _pdk()
    ext_dir = mod._pl.extracted_dir(project)
    ext_dir.mkdir(parents=True)
    spice_out = ext_dir / "top_extracted.sp"
    pnr = mod._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    def_file = pnr / "top.def"
    def_file.write_text(_DEF)
    netlist = pnr / "top_pnr.v"
    netlist.write_text("module top(input a); endmodule\n")
    calls = []

    def fake_docker_exec(container, cmd, timeout=None, **_):
        if "magic -dnull" in cmd:
            calls.append("magic")
            spice_out.write_text(".subckt top a\n.ends\n")
            (ext_dir / mod._mio.FEEDBACK_NAMES[0]).write_text("")
            return (0, magic_says + "0 errors\nMAGIC_EXT2SPICE_DONE", "")
        if "netgen -batch lvs" in cmd:
            calls.append("netgen")
            rpt = project / "reports/phase3/lvs.rpt"
            rpt.parent.mkdir(parents=True, exist_ok=True)
            rpt.write_text("Final result: Circuits match uniquely.\n")
            return (0, "", "")
        return (0, "", "")

    monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
    res = mod._run_extraction_lvs(project, "top", pdk, "c", def_file, netlist,
                                  "/nonexistent.magicrc", "/setup.tcl", 0.0)
    return res, calls, project


def test_an_extraction_of_library_layouts_never_reaches_netgen(tmp_path, monkeypatch):
    res, calls, project = _extract(tmp_path, monkeypatch, _LIBRARY_READ)
    assert "netgen" not in calls
    assert res.status == "NOT_MEASURED", res.detail
    assert res.extras["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT"
    assert set(res.extras["library_layout_masters"]) == {"gf180mcu_fd_io__fill1"}
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    assert verdict["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT"
    assert verdict["status"] != "PASS"


def test_an_abstract_extraction_reaches_netgen(tmp_path, monkeypatch):
    _res, calls, _ = _extract(tmp_path, monkeypatch, "")
    assert calls[-1] == "netgen"


@pytest.mark.parametrize("control,directory,placed", [
    ("plain", "library_plain", "neutral_master"),
    ("space_path", "library root", "neutral_master"),
    ("unplaced", "library root", "other_master"),
])
def test_native_magic_library_log_reaches_current_extraction_refusal(
        tmp_path, monkeypatch, control, directory, placed):
    """Real Magic log/parser component; runner tool transport is SOURCE_CONTROL.

    Built-in scmos and authored MAG geometry supply no PDK/PV/signoff credit.
    The DEF is the helper's authored population, not a native DEF-read claim.
    """
    import hashlib
    import subprocess
    import sys
    import lvs_layout_view_census as census
    library = tmp_path / directory
    library.mkdir()
    work = tmp_path / "native_work"
    work.mkdir()
    mag = library / "neutral_master.mag"
    mag.write_text("magic\ntech scmos\ntimestamp 0\n<< metal1 >>\n"
                   "rect 0 0 10 10\n<< end >>\n")
    rcfile = tmp_path / "empty.magicrc"
    rcfile.write_text("")
    script = ("tech load scmos\nload " + json.dumps(str(mag)) +
              "\nselect top cell\nextract all\nputs {OWN_TOY_LOAD_END}\nquit -noprompt\n")
    (tmp_path / "native.tcl").write_text(script)
    argv = ["magic", "-dnull", "-noconsole", "-rcfile", str(rcfile)]
    native = subprocess.run(argv, input=script, cwd=work, text=True,
                            capture_output=True, timeout=30)
    log = native.stdout + native.stderr
    (tmp_path / "magic.stdout").write_text(native.stdout)
    (tmp_path / "magic.stderr").write_text(native.stderr)
    (tmp_path / "magic.log").write_text(log)
    # The existing owning runner fixture now consumes this actual log and its
    # declared current population. Its native Magic/netgen transport stays
    # controlled; no successful netgen/PV measurement is invented.
    def_text = ("VERSION 5.8 ;\nDESIGN top ;\nCOMPONENTS 1 ;\n"
                f"- u0 {placed} + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n"
                "PINS 1 ;\n- a + NET a ;\nEND PINS\nNETS 1 ;\n"
                "- a + ROUTED met1 ;\nEND NETS\nEND DESIGN\n")
    monkeypatch.setattr(sys.modules[__name__], "_DEF", def_text)
    parsed = census.masters_read_from_library(log, census.def_component_masters(def_text))
    result, calls, project = _extract(tmp_path, monkeypatch, log)
    verdict = json.loads((project / "reports/phase3/lvs_verdict.json").read_text())
    ext = library / "neutral_master.ext"
    observed = {"control": control, "scope": "native Magic log/parser; runner SOURCE_CONTROL, not PV",
                "native_argv": argv, "native_rc": native.returncode,
                "mag_sha256": hashlib.sha256(mag.read_bytes()).hexdigest(),
                "DEF_sha256": hashlib.sha256(def_text.encode()).hexdigest(),
                "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
                "ext_present": ext.is_file(),
                "actual_read_lines": [line for line in log.splitlines() if "read from path" in line],
                "census": parsed, "step_status": result.status,
                "next_netgen_count": calls.count("netgen"), "current_verdict": verdict}
    (tmp_path / "native_census_observed.json").write_text(json.dumps(observed, indent=2) + "\n")
    assert native.returncode == 0 and ext.is_file(), observed
    assert f"Cell neutral_master read from path {library}" in log, observed
    if control == "unplaced":
        assert parsed == {}, observed
        assert calls.count("netgen") == 1, observed
    else:
        assert parsed == {"neutral_master": str(library)}, observed
        assert result.status == "NOT_MEASURED", observed
        assert result.extras["finding"] == "LVS_EXTRACTION_VIEW_NOT_ABSTRACT", observed
        assert calls.count("netgen") == 0, observed
        assert verdict["status"] != "PASS", observed
