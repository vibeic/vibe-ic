"""GAP-E2E-4 FOLLOW-UP + GAP-E2E-9 DEEP ROOT — two program-first, chip-AGNOSTIC
Phase-3 backend enhancements in phase3_one_shot_runner.py.

GAP-E2E-4 FOLLOW-UP (die-util routing headroom + over-sparse downsize)
---------------------------------------------------------------------
v1.2.65 sized `--die-um auto` to the placement `--util` target, which is DENSE
for routing headroom. Two changes, tested here:
  (1) the auto-die geometry now targets `_AUTO_DIE_TARGET_UTIL` (~0.25 routing
      headroom), DECOUPLED from the placement `--util` (default 0.30, UNCHANGED);
  (2) a new `_compute_downsized_die` over-sparse MIRROR of the upsize-only
      `_compute_resized_die`, opt-in and floor-guarded.

GAP-E2E-9 DEEP ROOT (LVS power-aware sign-off)
----------------------------------------------
netgen prints `Top level cell failed pin matching` on every sky130 OSS run
because the yosys gate netlist has no power ports while the extracted layout
carries per-cell VPWR/VGND (the POWER_PIN_ONLY class). The fix is power-aware
sign-off — (b) globalise the power rails in the local netgen setup, and a
§4.05-guarded verdict resolution that clears a POWER_PIN_ONLY mismatch to MATCH
while a SIGNAL_NET_MISMATCH still FAILs.

All tests are docker-free: pure-logic helpers + one monkeypatched-`_docker_exec`
functional test of the LVS verdict wiring. No container is spawned.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# GAP-E2E-4 FOLLOW-UP (1) — auto-die targets ROUTING HEADROOM, not placement util
# ---------------------------------------------------------------------------
class TestAutoDieRoutingHeadroomTarget:
    _SITE_AREA = 1.2512  # sky130_fd_sc_hd unithd: 0.46 x 2.72

    class _Pdk:
        cell_lef = "/nonexistent.lef"  # forces the fallback avg-cell path

    def _nl(self, tmp_path: Path, n_cells: int) -> Path:
        # A netlist _count_placed_cells_from_netlist can count: n std-cell insts.
        lines = ["module top(); "]
        for i in range(n_cells):
            lines.append(f"sky130_fd_sc_hd__inv_1 u{i} (.A(a{i}), .Y(y{i}));")
        lines.append("endmodule")
        p = tmp_path / "top_synth.v"
        p.write_text("\n".join(lines))
        return p

    def test_target_constant_is_the_routing_headroom_value(self):
        # ~0.25 empirically-clean campaign value; strictly sparser than the
        # placement-dense internal fallback (0.40) and the placement --util 0.30.
        assert mod._AUTO_DIE_TARGET_UTIL == pytest.approx(0.25)
        assert mod._AUTO_DIE_TARGET_UTIL < mod._AUTO_DIE_DEFAULT_UTIL
        assert mod._AUTO_DIE_TARGET_UTIL < 0.30

    def test_auto_die_sizes_to_routing_headroom_not_placement_util(self, tmp_path):
        nl = self._nl(tmp_path, 5000)
        out, note = mod._resolve_auto_die_um("auto", nl, 0.40, self._Pdk())
        side = int(out.lower().split("x")[0])
        avg = mod._AUTO_DIE_FALLBACK_CELL_UM2
        util = 5000 * avg / (side * side)
        # The design lands near the 0.25 routing-headroom target, NOT the 0.40
        # placement util that was passed in.
        assert util == pytest.approx(mod._AUTO_DIE_TARGET_UTIL, rel=0.05)
        # die-util fidelity follow-up reworded the note; with no project the
        # target is the routing-headroom default.
        assert note is not None and "target_util=0.25" in note
        assert "routing-headroom-default" in note

    def test_auto_die_is_decoupled_from_placement_util(self, tmp_path):
        # The SAME auto die is produced regardless of the placement --util passed;
        # only the routing-headroom constant drives the geometry.
        nl = self._nl(tmp_path, 5000)
        d_low, _ = mod._resolve_auto_die_um("auto", nl, 0.20, self._Pdk())
        d_hi, _ = mod._resolve_auto_die_um("auto", nl, 0.60, self._Pdk())
        assert d_low == d_hi

    def test_explicit_wxh_passthrough_unchanged(self, tmp_path):
        # §4.05 — an explicit WxH die is NEVER re-sized; util arg is irrelevant.
        out, note = mod._resolve_auto_die_um(
            "640x480", tmp_path / "unused.v", 0.40, self._Pdk())
        assert out == "640x480" and note is None

    def test_placement_util_default_still_030(self):
        # §4.05 regression guard — the placement `--util` default MUST stay 0.30
        # (only the AUTO-DIE sizing target moved). The normalizer + the CLI
        # default both pin 0.30.
        u, _ = mod._normalize_util("default")
        assert u == 0.30
        src = Path(mod.__file__).read_text()
        assert 'p.add_argument("--util", type=float, default=0.30' in src


# ---------------------------------------------------------------------------
# GAP-E2E-4 FOLLOW-UP (2) — over-sparse DOWNSIZE mirror of the upsize retry
# ---------------------------------------------------------------------------
class TestDieDownsize:
    def test_downsize_tightens_over_sparse_die(self):
        # 900x900 landed at 4% util; target 25% → side *= sqrt(4/25) = 0.4.
        dims = mod._compute_downsized_die(900, 900, 4.0)
        assert dims is not None
        new_w, new_h = dims
        assert new_w < 900 and new_h < 900          # tightened
        assert (new_w, new_h) == (360, 360)         # sqrt(4/25)=0.4 → 360
        # the tightened die lands near the 25% routing-headroom target
        util_before = None  # geometry-only helper; verify direction via ratio
        assert new_w / 900 == pytest.approx((4.0 / 25.0) ** 0.5, rel=0.01)

    def test_downsize_none_when_not_over_sparse(self):
        # actual >= target → nothing to tighten → leave the die UNCHANGED.
        assert mod._compute_downsized_die(900, 900, 25.0) is None
        assert mod._compute_downsized_die(900, 900, 40.0) is None

    def test_downsize_respects_floor(self):
        # §4.05 — a downsize that would breach the safe floor returns None
        # (never shrink past _AUTO_DIE_MIN_SIDE_UM). 100x100 @0.5% → 100*sqrt(
        # 0.5/25)=14µm < 60µm floor → refuse.
        assert mod._compute_downsized_die(100, 100, 0.5) is None
        # A returned die is ALWAYS at or above the floor.
        for die, u in ((900, 4.0), (600, 10.0), (1200, 3.0)):
            dims = mod._compute_downsized_die(die, die, u)
            if dims is not None:
                assert min(dims) >= mod._AUTO_DIE_MIN_SIDE_UM

    def test_downsize_never_exceeds_input_cap(self):
        # §4.05 — downsize only shrinks: the tightened die is never LARGER than
        # the input (so the _DEFAULT_DIE_MAX_UM cap can never be breached here).
        dims = mod._compute_downsized_die(1500, 1500, 2.0)
        assert dims is not None and dims[0] <= 1500 and dims[1] <= 1500

    def test_downsize_ignores_nonpositive_signal(self):
        assert mod._compute_downsized_die(900, 900, 0.0) is None
        assert mod._compute_downsized_die(900, 900, -3.0) is None

    def test_downsize_custom_floor_param_respected(self):
        # A caller-supplied larger floor is honored.
        assert mod._compute_downsized_die(900, 900, 4.0, die_min_um=400) is None
        assert mod._compute_downsized_die(900, 900, 4.0, die_min_um=300) == (360, 360)


# ---------------------------------------------------------------------------
# GAP-E2E-4 FOLLOW-UP — the over-util UPSIZE path is UNCHANGED (still fires)
# ---------------------------------------------------------------------------
class TestUpsizeStillFires:
    def test_over_util_upsize_grows_die(self):
        # _compute_resized_die is the upsize path: an over-util die grows.
        dims = mod._compute_resized_die(200, 200, 90.0, 70.0)
        assert dims is not None
        assert dims[0] > 200 and dims[1] > 200

    def test_upsize_caps_at_max(self):
        # An impossible-to-grow die returns None (caller ERRORs out) — the cap
        # guarantee is intact.
        assert mod._compute_resized_die(1999, 1999, 100.0, 5.0) is None

    def test_upsize_and_downsize_are_opposite_directions(self):
        up = mod._compute_resized_die(300, 300, 90.0, 70.0)
        down = mod._compute_downsized_die(300, 300, 5.0, 25.0)
        assert up is not None and down is not None
        assert up[0] > 300      # upsize grows
        assert down[0] < 300    # downsize shrinks


# ---------------------------------------------------------------------------
# GAP-E2E-9 DEEP ROOT — power-aware sign-off DECISION (§4.05 load-bearing)
# ---------------------------------------------------------------------------
_POWER_ONLY_BLOB = (
    "Contents of circuit 1:  Circuit: 'top'\n"
    "Subcircuit pins:\n"
    "VPWR                                       |(no matching pin)\n"
    "VGND                                       |(no matching pin)\n"
    "VPB                                        |(no matching pin)\n"
    "VNB                                        |(no matching pin)\n"
    "Final result: Top level cell failed pin matching.\n"
)
# §4.05 NEGATIVE — a real signal-net mismatch (netgen's top-level failure-table
# `(no pin, node is …)` shape). This must NEVER be power-aware-cleared.
_SIGNAL_NET_BLOB = (
    "Contents of circuit 1:  Circuit: 'top'\n"
    "(no pin, node is data_out[3])              |wdata[3]\n"
    "(no pin, node is data_out[4])              |wdata[4]\n"
    "Final result: Top level cell failed pin matching.\n"
)
# §4.05 NEGATIVE — a device property-error mismatch is real, never benign.
_PROPERTY_ERR_BLOB = (
    "Property errors were found.\n"
    "Final result: Circuits match uniquely with property errors.\n"
)
_CLEAN_MATCH_BLOB = (
    "Contents of circuit 1:  Circuit: 'top'\n"
    "Final result: Circuits match uniquely.\n"
)
_INCOMPLETE_BLOB = "Flattening unmatched subcell ...\n"  # no terminal verdict


class TestPowerAwareDecision:
    def test_power_pin_only_is_power_aware_clearable(self):
        assert mod._lvs_power_pin_only_mismatch(_POWER_ONLY_BLOB) is True

    def test_signal_net_mismatch_never_cleared(self):
        # §4.05 CRITICAL negative proof — a signal-net mismatch is NOT converted.
        assert mod._lvs_power_pin_only_mismatch(_SIGNAL_NET_BLOB) is False

    def test_property_error_mismatch_never_cleared(self):
        assert mod._lvs_power_pin_only_mismatch(_PROPERTY_ERR_BLOB) is False

    def test_clean_match_not_power_aware_branch(self):
        assert mod._lvs_power_pin_only_mismatch(_CLEAN_MATCH_BLOB) is False

    def test_incomplete_not_power_aware_branch(self):
        assert mod._lvs_power_pin_only_mismatch(_INCOMPLETE_BLOB) is False


# ---------------------------------------------------------------------------
# GAP-E2E-9 (mechanism, option b) — the local netgen setup GLOBALISES power rails
# ---------------------------------------------------------------------------
class TestLocalNetgenSetupGlobalisesPower:
    def _emit(self, tmp_path: Path):
        pdk = mod._detect_pdk(Path("/nonexistent"), override="sky130A")
        host, _ = mod._emit_local_netgen_setup(tmp_path, pdk, "vibeic-eda")
        return host.read_text()

    def test_power_rails_globalised(self, tmp_path):
        body = self._emit(tmp_path)
        for rail in ("global VPWR", "global VGND", "global VPB", "global VNB",
                     "global vccd1", "global vssd1"):
            assert rail in body

    def test_existing_ignore_block_intact(self, tmp_path):
        # the pre-existing physical-cell ignore behavior is preserved. #211
        # generalised the patterns from vendor-literal to family-token, so the
        # emitted regexps still IGNORE the canonical sky130 physical cells
        # (checked behaviourally) while SPARING functional cells.
        body = self._emit(tmp_path)
        assert "sky130A_setup.tcl" in body
        assert "$cells1" in body and "$cells2" in body
        pats = [re.compile(m.replace("[[:digit:]]", r"\d")
                           .replace("[[:alpha:]]", "[A-Za-z]"))
                for m in re.findall(r"regexp \{([^}]*)\} \$_c", body)]
        assert pats, "no `ignore class` regexps emitted"
        for nm in ("sky130_fd_sc_hd__fill_8", "sky130_fd_sc_hd__tapvpwrvgnd_1",
                   "sky130_fd_sc_hd__decap_4", "sky130_ef_sc_hd__fakediode_2"):
            assert any(p.search(nm) for p in pats), f"not ignored: {nm}"
        for nm in ("sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__inv_2"):
            assert not any(p.search(nm) for p in pats), f"wrongly ignored: {nm}"

    def test_globalisation_targets_only_power_rails(self, tmp_path):
        # §4.05 — every emitted `global <net>` names a power/ground/IO rail;
        # NO signal net is globalised (globalisation can only merge power rails,
        # never hide a signal-net mismatch).
        body = self._emit(tmp_path)
        globals_ = re.findall(r"^global\s+(\S+)\s*$", body, re.M)
        assert globals_, "expected some global power-net declarations"
        rail_re = re.compile(
            r"^(?:VPWR|VGND|VPB|VNB|vcc\w*|vss\w*|vdd\w*|vddio|vssio|VDD|VSS)$",
            re.I)
        for net in globals_:
            assert rail_re.match(net), f"non-power net globalised: {net!r}"


# ---------------------------------------------------------------------------
# GAP-E2E-9 — FUNCTIONAL wiring: _run_extraction_lvs verdict (no container)
# ---------------------------------------------------------------------------
class TestRunExtractionLvsPowerAwareWiring:
    def _prep(self, tmp_path: Path):
        project = tmp_path / "proj"
        pdk = mod._detect_pdk(Path("/nonexistent"), override="sky130A")
        top = "top"
        ext_dir = mod._pl.extracted_dir(project)
        ext_dir.mkdir(parents=True, exist_ok=True)
        spice_out = ext_dir / f"{top}_extracted.sp"
        lvs_rpt = project / "reports" / "phase3" / "lvs.rpt"
        def_file = mod._pl.pnr_dir(project)
        def_file.mkdir(parents=True, exist_ok=True)
        def_file = def_file / f"{top}.def"
        def_file.write_text(
            "VERSION 5.8 ;\nDESIGN top ;\n"
            "PINS 1 ;\n- a + NET a ;\nEND PINS\n"
            "NETS 1 ;\n- a + ROUTED met1 ;\nEND NETS\nEND DESIGN\n")
        netlist = mod._pl.synth_dir(project)
        netlist.mkdir(parents=True, exist_ok=True)
        netlist = netlist / f"{top}_synth.v"
        netlist.write_text("module top(input a); endmodule\n")
        return project, top, pdk, def_file, netlist, spice_out, lvs_rpt

    def _run(self, tmp_path, monkeypatch, report_blob, netgen_rc):
        (project, top, pdk, def_file, netlist,
         spice_out, lvs_rpt) = self._prep(tmp_path)

        def fake_docker_exec(container, cmd, timeout=None, **_):
            if "magic -dnull" in cmd:
                spice_out.write_text(
                    ".subckt top a\nX0 a sky130_fd_sc_hd__inv_1\n.ends\n")
                # W2.3 — MODEL THE TOOL, NOT JUST ITS NETLIST. The extraction
                # recipe emits `feedback save <ext_dir>/extract_feedback.txt`,
                # and magic 8.3.681 writes that file on EVERY extraction: 0
                # bytes when it filed no feedback areas. That empty file is a
                # MEASURED zero illegal overlaps.
                #
                # This fake wrote the `.sp` and not the feedback file, which is
                # a state real magic cannot produce -- an extraction that ran
                # and dumped no feedback channel. `magic_illegal_overlap_check`
                # correctly calls that EXTRACTION_FEEDBACK_ABSENT (rc 1, "an
                # unmeasured nothing", not a zero) and `_run_extraction_lvs`
                # correctly aborts before netgen, so all three arms below
                # returned LVS_EXTRACTION_ILLEGAL_OVERLAP and never reached the
                # power-aware verdict logic they exist to test.
                #
                # Writing it EMPTY is deliberate and is the only value that
                # keeps these arms honest: a clean extraction. An arm that
                # wanted a non-empty feedback channel would be testing the
                # overlap gate, which has its own suite.
                (spice_out.parent
                 / mod._mio.FEEDBACK_NAMES[0]).write_text("")
                return (0, "0 errors\nMAGIC_EXT2SPICE_DONE", "")
            if "netgen -batch lvs" in cmd:
                lvs_rpt.parent.mkdir(parents=True, exist_ok=True)
                lvs_rpt.write_text(report_blob)
                return (netgen_rc, report_blob, "")
            return (0, "", "")

        monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
        res = mod._run_extraction_lvs(
            project, top, pdk, "vibeic-eda", def_file, netlist,
            "/nonexistent.magicrc", "/setup.tcl", 0.0)
        verdict = json.loads(
            (project / "reports" / "phase3" / "lvs_verdict.json").read_text())
        return res, verdict

    def test_power_pin_only_report_yields_power_aware_pass(
            self, tmp_path, monkeypatch):
        res, verdict = self._run(tmp_path, monkeypatch, _POWER_ONLY_BLOB, 1)
        assert res.status == "PASS"
        assert res.extras.get("finding") == "LVS_MATCH_POWER_AWARE"
        assert res.extras.get("power_aware_signoff") is True
        assert res.extras.get("mismatch_class") == "POWER_PIN_ONLY"
        assert verdict["status"] == "PASS"
        assert verdict["finding"] == "LVS_MATCH_POWER_AWARE"

    def test_signal_net_report_still_fails(self, tmp_path, monkeypatch):
        # §4.05 CRITICAL — a signal-net mismatch is NEVER converted to a MATCH;
        # the step FAILs with the ordinary LVS_MISMATCH finding.
        res, verdict = self._run(tmp_path, monkeypatch, _SIGNAL_NET_BLOB, 1)
        assert res.status == "FAIL"
        assert res.extras.get("finding") == "LVS_MISMATCH"
        assert res.extras.get("finding") != "LVS_MATCH_POWER_AWARE"
        assert verdict["status"] == "FAIL"
        assert verdict["finding"] == "LVS_MISMATCH"

    def test_clean_match_report_still_passes_plainly(
            self, tmp_path, monkeypatch):
        # a genuine clean MATCH is unchanged (NOT the power-aware branch).
        res, verdict = self._run(tmp_path, monkeypatch, _CLEAN_MATCH_BLOB, 0)
        assert res.status == "PASS"
        assert verdict["finding"] == "LVS_MATCH"

    def test_magic_extraction_cmd_exports_cad_root(
            self, tmp_path, monkeypatch):
        # REGRESSION (magic batch startup-tech): `magic -dnull -noconsole`
        # execs magicdnull, whose C init resolves its startup-tech search path
        # from getenv("CAD_ROOT"). With CAD_ROOT unset it collapses to
        # "/magic/sys", minimum.tech is not found, and magic aborts init BEFORE
        # reading the -rcfile — extracting NOTHING (rc=0, "produced no extracted
        # netlist"). The env_prefix MUST export CAD_ROOT (derived from magic's
        # own install prefix) so the batch extraction can start.
        (project, top, pdk, def_file, netlist,
         spice_out, lvs_rpt) = self._prep(tmp_path)
        captured = {}

        def fake_docker_exec(container, cmd, timeout=None, **_):
            if "magic -dnull" in cmd:
                captured["magic"] = cmd
                spice_out.write_text(
                    ".subckt top a\nX0 a sky130_fd_sc_hd__inv_1\n.ends\n")
                return (0, "0 errors\nMAGIC_EXT2SPICE_DONE", "")
            if "netgen -batch lvs" in cmd:
                lvs_rpt.parent.mkdir(parents=True, exist_ok=True)
                lvs_rpt.write_text(_CLEAN_MATCH_BLOB)
                return (0, _CLEAN_MATCH_BLOB, "")
            return (0, "", "")

        monkeypatch.setattr(mod, "_docker_exec", fake_docker_exec)
        mod._run_extraction_lvs(
            project, top, pdk, "vibeic-eda", def_file, netlist,
            "/nonexistent.magicrc", "/setup.tcl", 0.0)
        magic_cmd = captured.get("magic", "")
        assert magic_cmd, "magic extraction command was never issued"
        # CAD_ROOT must be exported BEFORE the `magic -dnull` invocation, and it
        # must be derived (not depend on the ambient env being pre-seeded).
        assert "CAD_ROOT" in magic_cmd, (
            "magic batch extraction must export CAD_ROOT or it aborts at "
            "startup-tech load and extracts nothing")
        assert magic_cmd.index("CAD_ROOT") < magic_cmd.index("magic -dnull"), (
            "CAD_ROOT must be exported before the magic invocation")
        # honors a pre-set CAD_ROOT (`:-` default) rather than clobbering it.
        assert "CAD_ROOT:-" in magic_cmd
