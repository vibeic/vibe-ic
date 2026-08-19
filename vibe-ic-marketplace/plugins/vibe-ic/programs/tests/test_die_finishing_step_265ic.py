#!/usr/bin/env python3
"""Step 26.5ic — die finishing: the producer, the gate, and the two halves.

WHAT THIS DEFENDS, and where the bar comes from
-----------------------------------------------
Not this repo's opinion. wafer.space's own precheck container, run 2026-08-19
against a GDS this flow published (spm, sha256 fb08d9ed…), refused at stage 3
of 16 with ``Layer 'GUARD_RING_MK' is not used. wafers.space requires a seal
ring (guard ring) around the die.`` Their check is
``/workspace/scripts/klayout/check_size.py``. The flow had no chip-finishing
track, so no die it has ever produced carried one.

Every test below breaks something the change defends and requires the failure:

  * the generator produced nothing but exited 0  -> FAIL, not a silent pass
  * the generator added geometry that is not a ring -> FAIL
  * the PDK ships no generator                   -> DISCLOSED SKIP, rc 2, with
                                                    a STATED reason naming the
                                                    PDK, mirroring LibreLane
  * the die-id half is undetermined              -> the step is INCOMPLETE, and
                                                    is NEITHER clean NOR red,
                                                    and does not take a
                                                    verified seal ring down
  * the ring is inserted after the sign-off DRC  -> the ordering assertion
                                                    reddens

The flow declaration itself is NOT edited by this change and is asserted here
only as the contract the two programs must satisfy.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _klayout_launch as KL                                  # noqa: E402
import die_finishing_check as DFC                             # noqa: E402
import die_finishing_gen as DFG                               # noqa: E402

_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_STEP = "26.5ic"


def _steps():
    return yaml.safe_load(_FLOW.read_text())["steps"]


def _step(sid):
    for s in _steps():
        if str(s["id"]) == str(sid):
            return s
    raise AssertionError(f"step {sid} not in the flow")


# ── the contract the flow declares, which these two programs must satisfy ───

def test_the_step_is_declared_between_the_antenna_check_and_pv():
    """The load-bearing placement, asserted from the flow rather than assumed.

    LibreLane's chip flow substitutes the seal ring in after the antenna checker
    (``"+Checker.KLayoutAntenna": KLayout.SealRing``). Adding it after Step 31
    instead would mean the die Step 31 signed off is NOT the die that ships:
    metal added after the evidence, never itself DRC'd or LVS'd.
    """
    ids = [str(s["id"]) for s in _steps()]
    assert ids.count(_STEP) == 1
    assert ids.index("26") < ids.index(_STEP) < ids.index("31")
    assert _step(_STEP)["blocks_on"] == [26]


def test_the_two_programs_the_step_names_exist_and_are_split():
    """Generator and checker are separate programs, as they are upstream
    (KLayout.Density then Checker.KLayoutDensity), and the CHECKER is the one
    that fails the flow."""
    st = _step(_STEP)
    assert st["programs"] == ["die_finishing_gen"]
    gate = st["gate"]
    cmd = gate["program_exit_zero"] if "program_exit_zero" in gate else None
    assert cmd and cmd.startswith("die_finishing_check "), gate
    assert "--json reports/phase3/die_finishing.json" in cmd
    assert (_PROGRAMS / "die_finishing_gen.py").is_file()
    assert (_PROGRAMS / "die_finishing_check.py").is_file()
    assert (_PROGRAMS / "sealring" / "sealring_verify.py").is_file()


def test_the_declared_artefact_paths_are_the_ones_the_programs_use():
    outs = " ".join(_step(_STEP)["required_outputs"])
    for rel in (DFG._REPORT_REL, DFG._DEF_REL, DFG._SKIPPED_REL):
        assert rel in outs, (rel, outs)
    assert DFC._REPORT_REL == DFG._REPORT_REL
    assert DFC._DEF_REL == DFG._DEF_REL and DFC._SKIPPED_REL == DFG._SKIPPED_REL


def test_the_gate_never_opens_a_layout():
    """`die_finishing_check` re-reports; it must not be able to mutate the die
    it audits. The producer/auditor split is only real if the auditor cannot
    reach the layout at all."""
    src = (_PROGRAMS / "die_finishing_check.py").read_text()
    for forbidden in ("import pya", "subprocess", "_klayout_launch"):
        assert forbidden not in src, (
            f"die_finishing_check reaches for {forbidden!r}; it must only read "
            "the producer's report")


def test_this_repo_draws_no_seal_ring_of_its_own():
    """The ring is PDK geometry — width, layer stack, corner construction, slot
    pattern. Re-deriving it here would recreate the exact 'our own bar instead
    of the industry's' defect this step exists to remove."""
    gen = (_PROGRAMS / "die_finishing_gen.py").read_text()
    assert "import pya" not in gen, (
        "die_finishing_gen must not manipulate geometry; it calls the PDK's "
        "generator and measures the result")
    ver = (_PROGRAMS / "sealring" / "sealring_verify.py").read_text()
    for name, src in (("die_finishing_gen.py", gen),
                      ("sealring_verify.py", ver)):
        # Every layer is either DISCOVERED by diffing the two layouts or comes
        # from the caller as `--marker`; none is written down here.
        assert not re.search(r"LayerInfo\s*\(\s*\d", src), (
            f"{name} names a PDK layer number instead of discovering it")


def test_the_upstream_interface_is_used_unchanged():
    """LibreLane's generic path is exactly four flags. Drifting from it would
    mean this program drives PDK scripts nobody else can drive."""
    r = _LocalRunner()
    argv = DFG._emit_argv("pya-cli", r, "/pdk/sealring.py", "python3", None,
                          "/in.gds", "/out.gds", 100.0, 200.0)
    assert argv[:2] == ["python3", "/pdk/sealring.py"]
    assert argv[2:] == ["--input", "/in.gds", "--output", "/out.gds",
                        "--die-width", "100.000000",
                        "--die-height", "200.000000"]


def test_the_klayout_batch_form_sets_the_technology_search_path():
    """LibreLane's `run_ihp_sg13g2` sets KLAYOUT_PATH "so that KLayout can load
    the technology definition". A batch script driven with `-n <tech>` needs it;
    dropping it makes the PCell library silently unavailable."""
    gen = (_PROGRAMS / "die_finishing_gen.py").read_text()
    assert "KLAYOUT_PATH" in gen
    assert "libs.tech/klayout" in gen


# ── the ordering the runner must keep ───────────────────────────────────────

def test_runner_inserts_the_ring_before_the_signoff_gds_is_consumed():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    seal = [m.start() for m in re.finditer(r"(?<!def )_die_finishing\(project", src)]
    assert seal, "phase3_one_shot_runner must call _die_finishing"
    fill = [m.start() for m in
            re.finditer(r"(?<!def )_density_metal_fill\(project", src)]
    assert fill, "expected the density-fill call sites to still exist"
    # Every streamout branch that fills must seal FIRST — LibreLane's chip-flow
    # order is SealRing -> Filler -> Density. If a future edit moves the seal
    # after the fill (or after DRC), this reddens.
    assert len(seal) == len(fill), (
        f"{len(seal)} die-finishing call site(s) against {len(fill)} "
        "density-fill call site(s): every streamout branch that fills must "
        "also finish the die")
    for s_at, f_at in zip(seal, fill):
        assert s_at < f_at, (
            "the seal ring is inserted AFTER the fill/density pass; the die "
            "Step 31 verifies would then not be the die that ships")
    assert src.index("def step_gds") < src.index("def step_drc"), (
        "stream-out must precede sign-off DRC for the ring to be verified "
        "with the rest of the die")


class _LocalRunner:
    """A KLayout runner that is simply this process's environment.

    Keeps every test below hermetic: no docker, no container name, no reliance
    on which of strmrun/klayout happens to be installed.
    """
    kind = "test"
    detail = "in-process"

    def cpath(self, p):
        return str(p)

    def covers(self, p):
        return True

    def exists(self, p):
        return Path(str(p)).is_file()

    def klayout_bin(self):
        return "klayout"

    def run_argv(self, argv, env, timeout=1800):
        full = dict(os.environ)
        full.update({k: str(v) for k, v in env.items()})
        cp = subprocess.run([str(a) for a in argv], capture_output=True,
                            text=True, env=full, timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr

    def run(self, script, env, path_keys=(), timeout=1800):
        return self.run_argv([sys.executable, str(script)], env,
                             timeout=timeout)


def _project(tmp_path, die=200.0):
    """A project tree with a real GDS at the sign-off path."""
    pya = pytest.importorskip("pya")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("chip_top")
    li = ly.layer(pya.LayerInfo(10, 0))
    n = int(die * 1000)
    # A core block that leaves a margin, so a ring has somewhere to go.
    top.shapes(li).insert(pya.Box(0, 0, n, n))
    ly.write(str(pnr / "chip_top.gds"))
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"DIEAREA ( 0 0 ) ( {n} {n} ) ;\nEND DESIGN\n")
    return tmp_path


_GEN_HEAD = '''import sys
import pya
# --die-width : declares the pya-cli interface (see sealring_insert._PYA_CLI_MARKER)
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
src, dst = a["--input"], a["--output"]
w, h = float(a["--die-width"]), float(a["--die-height"])
ly = pya.Layout(); ly.read(src); top = ly.top_cell()
'''


def _generator(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(_GEN_HEAD + body)
    return p




def _project(tmp_path, die=200.0):
    """A project tree with a real GDS at the sign-off path."""
    pya = pytest.importorskip("pya")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("chip_top")
    li = ly.layer(pya.LayerInfo(10, 0))
    n = int(die * 1000)
    # A core block that leaves a margin, so a ring has somewhere to go.
    top.shapes(li).insert(pya.Box(0, 0, n, n))
    ly.write(str(pnr / "chip_top.gds"))
    (pnr / "routed.def").write_text(
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"DIEAREA ( 0 0 ) ( {n} {n} ) ;\nEND DESIGN\n")
    return tmp_path



_GEN_HEAD = '''import sys
import pya
# --die-width : declares the pya-cli interface (see sealring_insert._PYA_CLI_MARKER)
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
src, dst = a["--input"], a["--output"]
w, h = float(a["--die-width"]), float(a["--die-height"])
ly = pya.Layout(); ly.read(src); top = ly.top_cell()
'''


def _generator(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(_GEN_HEAD + body)
    return p




def _run(project, script, monkeypatch, **kw):
    monkeypatch.setattr(KL, "find_runner", lambda *a, **k: _LocalRunner())
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    return DFG.run(project, None, str(script) if script else None, None, None,
                   kw.pop("pdk_root", None), kw.pop("pdk", None),
                   sys.executable, kw.pop("marker", None), None, None,
                   None, True, None)


def _ring_body(extra=""):
    return ('li = ly.layer(pya.LayerInfo(99, 0))\n'
            'n = int(w * 1000)\n'
            'outer = pya.Region(pya.Box(-3000, -3000, n + 3000, n + 3000))\n'
            'inner = pya.Region(pya.Box(-1000, -1000, n + 1000, n + 1000))\n'
            'for p in (outer - inner).each():\n'
            '    top.shapes(li).insert(p)\n'
            + extra + 'ly.write(dst)\n')


# ── the seal-ring half ──────────────────────────────────────────────────────

def test_a_generator_that_exits_zero_and_writes_nothing_is_a_FAIL(
        tmp_path, monkeypatch):
    """THE TRAP, measured on a real PDK.

    The gf180mcuD PDK shipped in this project's EDA image carries
    ``libs.tech/klayout/tech/scripts/sealring.py`` but not the PCell library it
    imports. The script prints ``Error: Couldn't load the seal ring library.``
    and calls ``sys.exit()`` with NO argument — so the process exits **0** and
    writes no output file. LibreLane trusts that exit status. A gate that read
    it would have recorded a seal ring that does not exist, on a PDK that ships
    the script.
    """
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_silent.py",
                     'print("Error: Couldn\'t load the seal ring library.")\n'
                     'sys.exit()\n')
    res = _run(project, gen, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", res
    assert seal["generator_rc"] == 0, (
        "this test is worthless unless the stub really did exit 0")
    assert "produced no output layout" in seal["reason"]
    assert "unsealed" in seal["reason"]
    # Neither marker artefact may be left behind by a failed finish.
    assert not (project / DFG._DEF_REL).is_file()
    assert not (project / DFG._SKIPPED_REL).is_file()


def test_geometry_that_is_not_a_ring_is_a_FAIL(tmp_path, monkeypatch):
    """A dot is not a seal ring, and 'the script added something' must not be
    the pass condition."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_dot.py",
                     'li = ly.layer(pya.LayerInfo(99, 0))\n'
                     'top.shapes(li).insert(pya.Box(0, 0, 1000, 1000))\n'
                     'ly.write(dst)\n')
    gds = project / "phase3" / "stage3" / "pnr" / "chip_top.gds"
    before = gds.read_bytes()
    res = _run(project, gen, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", res
    assert "enclose" in seal["reason"], seal["reason"]
    r = seal["ring_check"]["ring"]
    assert r["horizontal_crossings"] < 2 or r["vertical_crossings"] < 2
    # AN UNVERIFIED RING IS NEVER PROMOTED. Swapping it in would hand the
    # sign-off DRC/LVS geometry that nothing has confirmed is a seal ring.
    assert gds.read_bytes() == before, (
        "the unverified layout was promoted into the sign-off GDS")
    assert "gds_out" not in seal and "gds_out_unpromoted" in seal


def test_a_solid_slab_over_the_whole_die_is_a_FAIL(tmp_path, monkeypatch):
    """A filled block covers the die but is not a ring: it would short the whole
    core. It crosses a centre scan line ONCE, so the enclosure test rejects it."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_slab.py",
                     'li = ly.layer(pya.LayerInfo(99, 0))\n'
                     'n = int(w * 1000)\n'
                     'top.shapes(li).insert(pya.Box(-2000, -2000, n + 2000, n + 2000))\n'
                     'ly.write(dst)\n')
    res = _run(project, gen, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", res
    assert seal["ring_check"]["ring"]["centre_covered"] is True
    assert "enclose" in seal["reason"], seal["reason"]


def test_a_ring_that_also_paints_the_core_is_a_FAIL(tmp_path, monkeypatch):
    """Crossing twice on both axes is not sufficient on its own: a ring PLUS a
    patch over the core does that, and metal dropped on the core during chip
    finishing shorts the design. Hollowness is the second half of the test."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring_patch.py", _ring_body(
        'top.shapes(li).insert(pya.Box(n // 2 - 5000, n // 2 - 5000,\n'
        '                             n // 2 + 5000, n // 2 + 5000))\n'))
    res = _run(project, gen, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "FAIL", res
    r = seal["ring_check"]["ring"]
    assert r["horizontal_crossings"] >= 2 and r["vertical_crossings"] >= 2, r
    assert r["centre_covered"] is True
    assert "centre" in seal["reason"], seal["reason"]


def test_a_real_ring_PASSES_is_promoted_and_leaves_a_finished_die(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring.py", _ring_body())
    gds = project / "phase3" / "stage3" / "pnr" / "chip_top.gds"
    before = gds.read_bytes()
    res = _run(project, gen, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "PASS", res
    assert seal["ring_check"]["ring"] == {"horizontal_crossings": 2,
                                          "vertical_crossings": 2,
                                          "centre_covered": False}
    assert gds.read_bytes() != before, (
        "--in-place must promote the sealed layout, or Step 31 verifies the "
        "unsealed die")
    fin = project / DFG._DEF_REL
    assert fin.is_file() and not (project / DFG._SKIPPED_REL).is_file()
    # The finished-die DEF states the band as a real placement blockage, from
    # the ring this run MEASURED — not from a nominal ring width.
    text = fin.read_text()
    assert "BLOCKAGES 4 ;" in text and text.count("- PLACEMENT RECT") == 4
    assert "DIEAREA" in text


def test_the_finished_def_band_comes_from_the_measured_ring(tmp_path):
    """A band derived from a nominal width would be this program inventing the
    foundry data it is careful not to invent anywhere else."""
    ext = {"outer": {"um": [0, 0, 100, 200]}, "inner": {"um": [5, 5, 95, 195]}}
    bands = DFG.seal_ring_bands(ext)
    assert bands == [[0, 0, 100, 5], [0, 195, 100, 200],
                     [0, 5, 5, 195], [95, 5, 100, 195]]
    # Anything unmeasured refuses rather than guesses.
    assert DFG.seal_ring_bands({"outer": {"um": [0, 0, 100, 200]}}) is None
    assert DFG.seal_ring_bands(
        {"outer": {"um": [0, 0, 100, 200]},
         "inner": {"um": [0, 0, 100, 200]}}) is None


def test_the_emitted_blockages_are_the_measured_band_and_never_degenerate(
        tmp_path, monkeypatch):
    """CLOSES A MEASURED GAP IN THIS FILE'S OWN GUARD. A mutation that made
    `write_finished_def` fall back to a zero-area band instead of refusing
    passed every other test here: the DEF still had four `PLACEMENT RECT`
    lines, and nothing read what was in them. A blockage of nothing is a DEF
    statement about nothing, which is worse than no statement."""
    project = _project(tmp_path, die=200.0)
    gen = _generator(tmp_path, "gen_ring_band.py", _ring_body())
    res = _run(project, gen, monkeypatch)
    assert res["seal_ring"]["state"] == "PASS"
    ext = res["seal_ring"]["ring_check"]["ring_extent"]
    rects = re.findall(
        r"- PLACEMENT RECT \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \) ;",
        (project / DFG._DEF_REL).read_text())
    assert len(rects) == 4
    boxes = [[int(v) for v in r] for r in rects]
    for x0, y0, x1, y1 in boxes:
        assert x1 > x0 and y1 > y0, (
            f"degenerate placement blockage ({x0} {y0}) ({x1} {y1}) — a "
            "blockage of zero area states nothing")
    # And they are the MEASURED band, in DEF units, not a nominal one.
    ol, ob, orr, ot = ext["outer"]["um"]
    il, ib, ir, it = ext["inner"]["um"]
    assert sorted(boxes) == sorted(
        [[round(v * 1000) for v in b] for b in
         ([ol, ob, orr, ib], [ol, it, orr, ot],
          [ol, ib, il, it], [ir, ib, orr, it])]), (boxes, ext)


def test_an_existing_blockages_section_is_merged_not_clobbered(tmp_path):
    routed = tmp_path / "routed.def"
    routed.write_text("VERSION 5.8 ;\nDESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\n"
                      "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
                      "BLOCKAGES 1 ;\n    - PLACEMENT RECT ( 1 1 ) ( 2 2 ) ;\n"
                      "END BLOCKAGES\nEND DESIGN\n")
    out = tmp_path / "die_finished.def"
    ok, why = DFG.write_finished_def(
        routed, out, {"outer": {"um": [0, 0, 100, 100]},
                      "inner": {"um": [5, 5, 95, 95]}})
    assert ok, why
    text = out.read_text()
    assert "BLOCKAGES 5 ;" in text, text
    assert "( 1 1 ) ( 2 2 )" in text, "the pre-existing blockage was dropped"
    assert text.count("- PLACEMENT RECT") == 5


# ── the honest skip ─────────────────────────────────────────────────────────

def test_a_pdk_with_no_generator_skips_out_loud_and_names_the_pdk(
        tmp_path, monkeypatch, capsys):
    """ACCEPTANCE: a PDK that ships no generator SKIPS, and says why.

    LibreLane's own message is "KLAYOUT_SEALRING_SCRIPT is unset.
    KLayout.SealRing may not be supported for the {PDK} PDK. This step will be
    skipped." Same shape here. Measured on a real PDK: sky130A ships a
    magic-based seal-ring generator and no KLayout one, and its LibreLane
    config.tcl leaves KLAYOUT_SEALRING_SCRIPT commented out — so this is the
    shipped behaviour of a PDK this flow supports, not a hypothetical.
    """
    project = _project(tmp_path)
    monkeypatch.delenv("KLAYOUT_SEALRING_SCRIPT", raising=False)
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())

    res = _run(project, None, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "DISCLOSED_SKIP", res
    assert "SKIPPED" in seal["reason"]
    # A skip must NAME what it looked for. "not supported" says nothing a
    # reader can check or fix.
    for expected in ("signoff_config.json", "KLAYOUT_SEALRING_SCRIPT",
                     "libs.tech/klayout/tech/scripts/sealring.py"):
        assert expected in seal["reason"], (expected, seal["reason"])
    # And the skip is RECORDED where the flow declares it.
    assert (project / DFG._SKIPPED_REL).is_file()
    assert not (project / DFG._DEF_REL).is_file()

    assert DFG.main([str(project)]) == DFG.SKIP == 2, (
        "the disclosed skip must exit 2 — the flow's VACUOUS-PASS tier — never "
        "0, which would be a bare PASS earned by a checker that did not run")
    assert "VACUOUS_PASS:" in capsys.readouterr().out


def test_the_skip_reason_survives_into_the_gate(tmp_path, monkeypatch):
    """The producer must PERSIST its reason, or the gate reports the useless
    generic 'die_finishing_gen has not run' and the real reason is lost."""
    project = _project(tmp_path)
    for v in ("PDK_ROOT", "PDK", "KLAYOUT_SEALRING_SCRIPT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    _run(project, None, monkeypatch)
    got = DFC.evaluate(project)
    assert got["verdict"] == "DISCLOSED_SKIP"
    assert "no seal-ring generator" in got["reason"], got
    assert DFC.main([str(project)]) == DFC.SKIP == 2


def test_a_step_that_COULD_NOT_RUN_leaves_no_skipped_marker(
        tmp_path, monkeypatch):
    """A DECIDED skip and a step that could not run are different facts.

    MEASURED on a published run tree carrying no `phase3/stage3/pnr` at all:
    the earlier version wrote `die_finishing.SKIPPED.txt` for "cannot determine
    the die size", and `flow_compliance_check` then reported Step 26.5ic as
    VACUOUS-PASS on a tree that never produced a die. An upstream failure had
    been converted into this step looking fine. Only "this PDK ships no
    generator" earns the marker.
    """
    project = _project(tmp_path)
    (project / "phase3" / "stage3" / "pnr" / "routed.def").unlink()
    monkeypatch.setenv("KLAYOUT_SEALRING_SCRIPT", str(tmp_path / "seal.py"))
    (tmp_path / "seal.py").write_text("# --die-width\n")
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    res = _run(project, None, monkeypatch)
    seal = res["seal_ring"]
    assert seal["state"] == "DISCLOSED_SKIP"
    assert "cannot determine the die size" in seal["reason"]
    assert seal["marker"] is False
    assert not (project / DFG._SKIPPED_REL).is_file(), (
        "a step that could not run recorded itself as deliberately skipped")
    assert not (project / DFG._DEF_REL).is_file()
    # The gate still discloses it, and does NOT invent a cross-check failure
    # about a marker the producer never claimed to write.
    got = DFC.evaluate(project)
    assert got["verdict"] == "DISCLOSED_SKIP"
    assert "cannot determine the die size" in got["reason"]


def test_a_pdk_decision_skip_DOES_leave_the_marker(tmp_path, monkeypatch):
    """The other side of the same distinction: a PDK that ships no generator IS
    a decided outcome, and the flow declares an artefact for it."""
    project = _project(tmp_path)
    for v in ("PDK_ROOT", "PDK", "KLAYOUT_SEALRING_SCRIPT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    res = _run(project, None, monkeypatch)
    assert res["seal_ring"]["marker"] is True
    assert (project / DFG._SKIPPED_REL).is_file()


def test_a_declared_script_that_is_absent_is_reported_as_declared(
        tmp_path, monkeypatch):
    """A broken DECLARATION and a PDK that simply ships none are different
    facts, and the skip must not blame the PDK for this program's own guess."""
    project = _project(tmp_path)
    monkeypatch.setattr(DFG._kl, "find_runner", lambda *a, **k: _LocalRunner())
    res = _run(project, tmp_path / "nope.py", monkeypatch)
    assert res["seal_ring"]["state"] == "DISCLOSED_SKIP"
    assert "declared by --script" in res["seal_ring"]["reason"]

    res = _run(project, None, monkeypatch,
               pdk_root=str(tmp_path / "pdks"), pdk="nosuch")
    assert res["seal_ring"]["state"] == "DISCLOSED_SKIP"
    assert "no seal-ring generator for the nosuch PDK" in res["seal_ring"]["reason"]


def test_no_klayout_at_all_is_a_skip_not_a_pass(tmp_path, monkeypatch):
    project = _project(tmp_path)
    # A script IS declared, so the skip below can only be about KLayout.
    monkeypatch.setenv("KLAYOUT_SEALRING_SCRIPT", str(tmp_path / "seal.py"))
    monkeypatch.setenv("VIBEIC_KLAYOUT_FORCE_ABSENT", "1")
    res = DFG.run(project, None, None, None, None, None, None, sys.executable,
                  None, None, None, None, True, None)
    assert res["seal_ring"]["state"] == "DISCLOSED_SKIP"
    assert "no KLayout runner available" in res["seal_ring"]["reason"]


def test_strict_refuses_to_let_a_skip_stand(tmp_path, monkeypatch):
    """A tapeout must be able to say 'a disclosed skip is not good enough'."""
    project = _project(tmp_path)
    monkeypatch.setenv("KLAYOUT_SEALRING_SCRIPT", str(tmp_path / "seal.py"))
    monkeypatch.setenv("VIBEIC_KLAYOUT_FORCE_ABSENT", "1")
    assert DFG.main([str(project), "--strict"]) == DFG.FAIL


# ── the die-identification half, and that it never merges with the ring ─────

def _bridge_cfg(project, die_id):
    b = project / "input" / "pdk" / "bridge"
    b.mkdir(parents=True, exist_ok=True)
    (b / "signoff_config.json").write_text(
        json.dumps({"die_finishing": {"die_id": die_id}}))


def test_an_undeclared_packaging_choice_is_not_determined_and_names_the_fix(
        tmp_path, monkeypatch):
    """The die-id requirement is CONDITIONAL and the condition is not declared
    anywhere in this flow, so the honest answer is 'undecided' plus the name of
    the declaration that would decide it."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring_id.py", _ring_body())
    res = _run(project, gen, monkeypatch)
    assert res["seal_ring"]["state"] == "PASS"
    die = res["die_id"]
    assert die["state"] == "NOT_DETERMINED"
    assert "die_finishing.die_id.packaging" in die["reason"]
    assert "does not gate the seal ring" in die["reason"]


def test_a_non_cob_submission_is_NOT_APPLICABLE_not_a_pass_by_silence(
        tmp_path, monkeypatch, capsys):
    """MEASURED on the operator's own tool: `generate_id.py` puts its whole
    four-cell requirement behind `if cob:`, and `--cob` is `action="store_true"`
    — default OFF. A non-CoB submission legitimately carries none of the cells,
    so an UNCONDITIONAL die-id gate would refuse correct designs."""
    project = _project(tmp_path)
    _bridge_cfg(project, {"packaging": "wire-bond"})
    gen = _generator(tmp_path, "gen_ring_nc.py", _ring_body())
    res = _run(project, gen, monkeypatch)
    die = res["die_id"]
    assert die["state"] == "NOT_APPLICABLE", die
    assert "not a pass by silence" in die["reason"]
    assert die["packaging"] == "wire-bond"
    got = DFC.evaluate(project)
    # A DECIDED answer: nothing is left for anyone to come back to, so this is
    # not the INCOMPLETE tier.
    assert got["verdict"] == "PASS" and got["tier"] == "SUBSTANTIVE_PASS"
    assert DFC.main([str(project), "--strict"]) == DFC.PASS, (
        "--strict must not refuse a condition that was read and did not hold")


def test_a_cob_submission_with_no_declared_cell_list_is_not_determined(
        tmp_path, monkeypatch):
    """The requirement is known; the LIST is the operator's declaration and is
    not this flow's to invent."""
    project = _project(tmp_path)
    _bridge_cfg(project, {"packaging": "cob"})
    gen = _generator(tmp_path, "gen_ring_cnl.py", _ring_body())
    res = _run(project, gen, monkeypatch)
    die = res["die_id"]
    assert die["state"] == "NOT_DETERMINED", die
    assert "die_finishing.die_id.cells" in die["reason"]
    assert "The requirement is known" in die["reason"]


def test_a_cob_cell_instantiated_twice_is_ABSENT(tmp_path, monkeypatch):
    """The operator's own script asserts `len(cell_insts) == 1` per cell, so
    'present twice' is its failure too — a boolean presence check would credit
    it."""
    project = _project(tmp_path)
    _bridge_cfg(project, {"packaging": "cob", "cells": ["shuttle_id_cell"]})
    gen = _generator(tmp_path, "gen_ring_dup.py", _ring_body(
        'idc = ly.create_cell("shuttle_id_cell")\n'
        'idc.shapes(li).insert(pya.Box(0, 0, 100, 100))\n'
        'top.insert(pya.CellInstArray(idc.cell_index(), pya.Trans(0, 0)))\n'
        'top.insert(pya.CellInstArray(idc.cell_index(), pya.Trans(5000, 5000)))\n'))
    res = _run(project, gen, monkeypatch)
    die = res["die_id"]
    assert die["state"] == "ABSENT", die
    assert die["duplicated"] == ["shuttle_id_cell"], die
    assert DFC.evaluate(project)["verdict"] == "FAIL"


def test_an_undetermined_die_id_does_not_fail_a_verified_seal_ring(
        tmp_path, monkeypatch, capsys):
    """The whole point of reporting the halves separately: the die-id half's
    silence must not redden a ring the flow actually verified, and must not be
    reported as clean either. The flow's word for that is INCOMPLETE."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring_i2.py", _ring_body())
    _run(project, gen, monkeypatch)
    got = DFC.evaluate(project)
    assert got["verdict"] == "PASS"
    assert got["tier"] == "INCOMPLETE"
    assert got["seal_ring"]["state"] == "PASS"
    assert got["die_id"]["state"] == "NOT_DETERMINED"
    assert DFC.main([str(project)]) == DFC.PASS
    out = capsys.readouterr().out
    # The token the flow's roll-up reads to raise the INCOMPLETE tier.
    assert any(ln.lstrip().startswith("INCOMPLETE")
               for ln in out.splitlines()), out
    assert "SUBSTANTIVE_PASS" not in out


def test_strict_refuses_to_certify_an_undetermined_die_id(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring_i3.py", _ring_body())
    _run(project, gen, monkeypatch)
    assert DFC.main([str(project)]) == DFC.PASS
    assert DFC.main([str(project), "--strict"]) == DFC.FAIL


def test_a_cob_submission_missing_its_declared_cells_is_a_FAIL(
        tmp_path, monkeypatch):
    """A chip-on-board submission is hard-blocked by the operator without these
    cells, so here it is a real failure — not an open question."""
    project = _project(tmp_path)
    _bridge_cfg(project, {"packaging": "cob", "cells": ["shuttle_id_cell"]})
    gen = _generator(tmp_path, "gen_ring_i4.py", _ring_body())
    res = _run(project, gen, monkeypatch)
    assert res["seal_ring"]["state"] == "PASS"
    assert res["die_id"]["state"] == "ABSENT"
    assert "shuttle_id_cell" in res["die_id"]["missing"]
    assert DFC.evaluate(project)["verdict"] == "FAIL"


def test_a_cob_submission_carrying_its_cells_is_a_substantive_pass(
        tmp_path, monkeypatch, capsys):
    project = _project(tmp_path)
    _bridge_cfg(project, {"packaging": "CoB", "cells": ["shuttle_id_cell"]})
    gen = _generator(tmp_path, "gen_ring_i5.py", _ring_body(
        'idc = ly.create_cell("shuttle_id_cell")\n'
        'idc.shapes(li).insert(pya.Box(0, 0, 100, 100))\n'
        'top.insert(pya.CellInstArray(idc.cell_index(), pya.Trans(0, 0)))\n'))
    res = _run(project, gen, monkeypatch)
    assert res["die_id"]["state"] == "PRESENT", res["die_id"]
    assert res["die_id"]["instances"] == {"shuttle_id_cell": 1}
    got = DFC.evaluate(project)
    assert got["verdict"] == "PASS" and got["tier"] == "SUBSTANTIVE_PASS"
    assert DFC.main([str(project)]) == DFC.PASS
    assert "SUBSTANTIVE_PASS" in capsys.readouterr().out


# ── the gate: it reports, it does not decide on its own ─────────────────────

def test_the_gate_refuses_a_report_it_cannot_attribute(tmp_path):
    project = _project(tmp_path)
    rep = project / DFG._REPORT_REL
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({"verdict": "PASS", "seal_ring": {"state": "PASS"}}))
    got = DFC.evaluate(project)
    assert got["verdict"] == "FAIL"
    assert "not a die_finishing_gen report" in got["reason"]


def test_the_gate_cross_checks_the_report_against_the_disk(tmp_path):
    """A claim and the thing it claims about are two different facts."""
    project = _project(tmp_path)
    rep = project / DFG._REPORT_REL
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({
        "producer": "die_finishing_gen", "check": "die_finishing",
        "seal_ring": {"state": "PASS"},
        "die_id": {"state": "NOT_DETERMINED", "reason": "x"}}))
    got = DFC.evaluate(project)
    assert got["verdict"] == "FAIL"
    assert "not on disk" in got["reason"]


def test_the_gate_is_idempotent_over_its_own_output(tmp_path, monkeypatch):
    """The gate's --json target is the same path the producer writes. Reading
    its own output back must not lose the measurement or change the verdict."""
    project = _project(tmp_path)
    gen = _generator(tmp_path, "gen_ring_idem.py", _ring_body())
    _run(project, gen, monkeypatch)
    target = str(project / DFG._REPORT_REL)
    first = DFC.main([str(project), "--json", target])
    once = json.loads((project / DFG._REPORT_REL).read_text())
    second = DFC.main([str(project), "--json", target])
    twice = json.loads((project / DFG._REPORT_REL).read_text())
    assert first == second == DFC.PASS
    assert once == twice, "the gate is not idempotent over its own output"
    assert once["run"]["producer"] == "die_finishing_gen"
    assert once["run"]["seal_ring"]["ring_check"]["verdict"] == "PASS", (
        "the producer's measurement was lost when the verdict was written")


def test_a_missing_report_is_a_skip_not_a_pass(tmp_path):
    project = _project(tmp_path)
    got = DFC.evaluate(project)
    assert got["verdict"] == "DISCLOSED_SKIP"
    assert "has not run on this project" in got["reason"]
    assert got["die_id"]["state"] == "NOT_DETERMINED"


# ── how the PDK's script is driven ──────────────────────────────────────────

def test_the_invocation_form_is_read_from_the_script_not_from_a_pdk_name(
        tmp_path):
    """LibreLane branches on the PDK's NAME to choose how to call its script.
    A name says nothing checkable about how a file wants to be called, so this
    reads the interface the script itself declares."""
    r = _LocalRunner()
    cli = tmp_path / "cli.py"
    cli.write_text('import click\n@click.option("--die-width")\n')
    batch = tmp_path / "batch.py"
    batch.write_text('# driven with -rd width=... -rd height=...\n')
    assert DFG.detect_form(r, str(cli))[0] == "pya-cli"
    assert DFG.detect_form(r, str(batch))[0] == "klayout-rd"
    # An UNREADABLE script keeps the documented default rather than silently
    # switching how the PDK is driven.
    form, why = DFG.detect_form(r, str(tmp_path / "gone.py"))
    assert form == "pya-cli" and "could not read" in why


def test_the_technology_name_comes_from_the_pdk_s_own_file(tmp_path):
    r = _LocalRunner()
    tech = tmp_path / "libs.tech" / "klayout" / "tech"
    (tech / "scripts").mkdir(parents=True)
    script = tech / "scripts" / "sealring.py"
    script.write_text("# batch\n")
    (tech / "x.lyt").write_text("<technology><name>sg13g2</name></technology>")
    name, why = DFG.derive_tech(r, str(script))
    assert name == "sg13g2", why
    assert "x.lyt" in why


def test_two_technology_files_refuse_rather_than_guess(tmp_path):
    r = _LocalRunner()
    tech = tmp_path / "libs.tech" / "klayout" / "tech"
    (tech / "scripts").mkdir(parents=True)
    script = tech / "scripts" / "sealring.py"
    script.write_text("# batch\n")
    (tech / "a.lyt").write_text("<technology><name>aa</name></technology>")
    (tech / "b.lyt").write_text("<technology><name>bb</name></technology>")
    name, why = DFG.derive_tech(r, str(script))
    assert name is None and "more than one" in why


def test_the_die_comes_from_the_floorplan_not_the_bounding_box(tmp_path):
    project = _project(tmp_path, die=200.0)
    w, h, src = DFG.die_size(project, project / "phase3/stage3/pnr/chip_top.gds",
                             None, None)
    assert (w, h) == (200.0, 200.0)
    assert "DIEAREA" in src


def test_the_signoff_gds_is_preferred_over_the_published_copy():
    """Step 31's DRC and LVS read `phase3/stage3/pnr`; `phase3/stage4/gds` is
    only published when it is byte-identical to it. Sealing the published copy
    would seal the die after its evidence."""
    assert DFG._GDS_GLOBS[0].startswith("phase3/stage3/pnr/")
