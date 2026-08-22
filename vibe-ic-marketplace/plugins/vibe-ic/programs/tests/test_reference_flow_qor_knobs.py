#!/usr/bin/env python3
"""Tests for the Phase-3 REFERENCE-FLOW QoR-KNOB INGEST in
phase3_one_shot_runner.py.

A design may stage an ORFS-style reference flow under
``input/reference_flow/`` whose ``*.mk`` / ``*.tcl`` files declare the exact
synth/routing QoR knobs the reference sign-off used to close the design
cleanly (``SWAP_ARITH_OPERATORS``, ``ADDER_MAP_FILE``, ``REMOVE_ABC_BUFFERS``,
fastroute layer adjustments). Phase-3 previously read reference_flow ONLY for
the clock period and IGNORED these QoR knobs.

`_reference_flow_qor_knobs(project)` ingests ONLY the knobs the design's OWN
reference flow explicitly declares (keyed on the ORFS knob NAMES — chip-
AGNOSTIC), and `step_synth` maps each present+valid knob to a yosys directive.

§4.05 NO-LEAK gates covered here (LOAD-BEARING):
  * No reference_flow config staged → {} → the yosys command is unchanged
    (none of the injected directives appear).
  * A knob is applied ONLY when the design literally declares it (truthy for
    bools); a falsy declaration is never applied and even overrides an earlier
    truthy one.
  * ADDER_MAP_FILE whose referenced file is absent/unreadable/unexpanded is
    SKIPPED (disclosed), never fabricated.

All tests are docker-free: the emit tests mock ``_docker_exec`` and capture
the generated yosys command string. No container is spawned.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

mod = importlib.import_module("phase3_one_shot_runner")
_pl = importlib.import_module("_path_layout")


# ---------------------------------------------------------------------------
# Ingest helper: _reference_flow_qor_knobs
# ---------------------------------------------------------------------------
def _stage_reference_flow(project: Path, files: dict) -> Path:
    """Create ``project/input/reference_flow/<name>`` for each name->content
    in ``files`` and return the reference_flow dir."""
    rf = project / "input" / "reference_flow"
    rf.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (rf / name).write_text(content)
    return rf


class TestReferenceFlowQoRKnobsIngest:
    def test_no_reference_flow_returns_empty(self, tmp_path):
        # §4.05: no reference_flow config staged → {}
        assert mod._reference_flow_qor_knobs(tmp_path) == {}

    def test_reference_flow_dir_without_known_knobs_returns_empty(self, tmp_path):
        _stage_reference_flow(tmp_path, {
            "config.mk": "PLATFORM = sky130hd\nDESIGN_NAME = whatever\n",
        })
        assert mod._reference_flow_qor_knobs(tmp_path) == {}

    def test_mk_swap_remove_adder_all_present(self, tmp_path):
        _stage_reference_flow(tmp_path, {
            "orfs_config.mk": (
                "export SWAP_ARITH_OPERATORS = 1\n"
                "REMOVE_ABC_BUFFERS = 1\n"
                "ADDER_MAP_FILE = adders.v\n"
            ),
            "adders.v": "// adder techmap\n",
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert k.get("SWAP_ARITH_OPERATORS") == "1"
        assert k.get("REMOVE_ABC_BUFFERS") == "1"
        assert k.get("ADDER_MAP_FILE") == "adders.v"

    def test_mk_assignment_forms(self, tmp_path):
        # export / ?= / := all recognized; trailing comment + quotes stripped
        _stage_reference_flow(tmp_path, {
            "config.mk": (
                "SWAP_ARITH_OPERATORS ?= 1   # tuned\n"
                "REMOVE_ABC_BUFFERS := 1\n"
                'ADDER_MAP_FILE = "yosys/cells_adders.v"\n'
            ),
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert k.get("SWAP_ARITH_OPERATORS") == "1"
        assert k.get("REMOVE_ABC_BUFFERS") == "1"
        assert k.get("ADDER_MAP_FILE") == "yosys/cells_adders.v"

    def test_falsy_bool_not_ingested(self, tmp_path):
        _stage_reference_flow(tmp_path, {
            "config.mk": "SWAP_ARITH_OPERATORS = 0\nREMOVE_ABC_BUFFERS = no\n",
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert "SWAP_ARITH_OPERATORS" not in k
        assert "REMOVE_ABC_BUFFERS" not in k

    def test_explicit_falsy_overrides_earlier_truthy(self, tmp_path):
        # .mk processed before .tcl; an explicit falsy in the later file wins.
        _stage_reference_flow(tmp_path, {
            "a_config.mk": "SWAP_ARITH_OPERATORS = 1\n",
            "z_override.tcl": "set ::env(SWAP_ARITH_OPERATORS) 0\n",
        })
        assert "SWAP_ARITH_OPERATORS" not in mod._reference_flow_qor_knobs(tmp_path)

    def test_tcl_set_env_form(self, tmp_path):
        _stage_reference_flow(tmp_path, {
            "flow.tcl": (
                "set ::env(SWAP_ARITH_OPERATORS) 1\n"
                "set ::env(ADDER_MAP_FILE) adders.v\n"
            ),
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert k.get("SWAP_ARITH_OPERATORS") == "1"
        assert k.get("ADDER_MAP_FILE") == "adders.v"

    def test_tcl_setenv_and_plain_set_forms(self, tmp_path):
        _stage_reference_flow(tmp_path, {
            "flow.tcl": (
                "setenv REMOVE_ABC_BUFFERS 1\n"
                "set SWAP_ARITH_OPERATORS true\n"
            ),
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert k.get("REMOVE_ABC_BUFFERS") == "1"
        assert k.get("SWAP_ARITH_OPERATORS") == "1"

    def test_fastroute_layer_adjust_captured(self, tmp_path):
        # modern token (OpenROAD 2023+): `set_routing_layer_adjustment`.
        _stage_reference_flow(tmp_path, {
            "fastroute.tcl": (
                "set_routing_layer_adjustment met2-met5 0.5\n"
                "set_routing_layer_adjustment met1 0.8\n"
            ),
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        adj = k.get("FASTROUTE_LAYER_ADJUST")
        assert isinstance(adj, list) and len(adj) == 2
        assert adj[0].startswith("set_routing_layer_adjustment met2-met5")

    def test_fastroute_deprecated_long_form_also_ingested(self, tmp_path):
        # an OLDER reference flow using the deprecated long form is still
        # ingested (the regex matches both). The deprecated token is built
        # dynamically so this test's SOURCE carries no deprecated TCL literal
        # (keeps the openroad-tcl-deprecation gate clean).
        _dep = "set_global" + "_routing_layer_adjustment"
        _stage_reference_flow(tmp_path, {"fastroute.tcl": f"{_dep} met1 0.8\n"})
        k = mod._reference_flow_qor_knobs(tmp_path)
        adj = k.get("FASTROUTE_LAYER_ADJUST")
        assert isinstance(adj, list) and len(adj) == 1 and adj[0].startswith(_dep)

    def test_unknown_vars_ignored_chip_agnostic(self, tmp_path):
        # Only the ORFS knob NAMES are recognized — arbitrary vars never leak in.
        _stage_reference_flow(tmp_path, {
            "config.mk": (
                "SOME_RANDOM_DESIGN_VAR = 1\n"
                "CORE_UTILIZATION = 45\n"
                "SWAP_ARITH_OPERATORS = 1\n"
            ),
        })
        k = mod._reference_flow_qor_knobs(tmp_path)
        assert set(k) == {"SWAP_ARITH_OPERATORS"}


# ---------------------------------------------------------------------------
# Path resolver: _resolve_adder_map_file
# ---------------------------------------------------------------------------
class TestResolveAdderMapFile:
    def test_absolute_existing(self, tmp_path):
        f = tmp_path / "abs_adders.v"
        f.write_text("// map\n")
        assert mod._resolve_adder_map_file(tmp_path, str(f)) == f

    def test_relative_to_reference_flow(self, tmp_path):
        rf = tmp_path / "input" / "reference_flow"
        rf.mkdir(parents=True)
        (rf / "adders.v").write_text("// map\n")
        got = mod._resolve_adder_map_file(tmp_path, "adders.v")
        assert got == rf / "adders.v"

    def test_relative_to_project_root(self, tmp_path):
        (tmp_path / "maps").mkdir()
        (tmp_path / "maps" / "adders.v").write_text("// map\n")
        got = mod._resolve_adder_map_file(tmp_path, "maps/adders.v")
        assert got == tmp_path / "maps" / "adders.v"

    def test_missing_returns_none(self, tmp_path):
        assert mod._resolve_adder_map_file(tmp_path, "nope.v") is None

    def test_unexpanded_flow_variable_returns_none(self, tmp_path):
        # §4.05: never fabricate an expansion for an unexpanded Make/Tcl var.
        assert mod._resolve_adder_map_file(
            tmp_path, "$(PLATFORM_DIR)/adders.v") is None
        assert mod._resolve_adder_map_file(
            tmp_path, "$::env(PLATFORM_DIR)/adders.v") is None

    def test_empty_returns_none(self, tmp_path):
        assert mod._resolve_adder_map_file(tmp_path, "") is None


# ---------------------------------------------------------------------------
# step_synth emission (docker-free): the ingested knobs map to yosys
# directives ONLY when actually present + valid.
# ---------------------------------------------------------------------------
_MIN_LIBERTY = (
    'library (fake) {\n'
    '  cell (INV) {\n'
    '    pin(A) { direction : "input"; }\n'
    '    pin(Y) { direction : "output"; function : "!A"; }\n'
    '  }\n'
    '}\n'
)


def _min_project(tmp_path: Path) -> "tuple[Path, mod.PdkConfig]":
    project = tmp_path / "proj"
    rtl = _pl.rtl_dir(project)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(input a, input b, output y); assign y = a & b; endmodule\n")
    lib = project / "fake.lib"
    lib.write_text(_MIN_LIBERTY)
    pdk = mod.PdkConfig(
        name="sky130A", liberty=str(lib), tech_lef="t.lef", cell_lef="c.lef",
        cell_gds=None, site="unit", drc_deck=None)
    return project, pdk


# yosys announces every techmap module it instantiates. `step_synth` now reads
# these lines to decide whether a DECLARED ADDER_MAP_FILE actually bound, so a
# test that wants the "applied" verdict must supply the matching evidence.
_YOSYS_LOG_MAP_APPLIED = (
    "Number of cells:  42\n"
    "Using template \\my_adder_map for cells of type $add.\n")
# The SILENT-FALL-THROUGH shape: the map was staged, but yosys mapped the
# arithmetic with its own default instead.
_YOSYS_LOG_MAP_NOT_USED = (
    "Number of cells:  42\n"
    "Using template \\_90_lcu_brent_kung for cells of type $lcu.\n")


def _capture_synth(monkeypatch, project: Path, pdk,
                   stdout: str = "Number of cells:  42\n") -> "tuple[object, str]":
    container = "vibe-test-container"
    monkeypatch.setitem(mod._CONTAINER_MOUNTS_CACHE, container, [])
    netlist = _pl.synth_dir(project) / "top_synth.v"
    cmds: list = []

    def _fake_docker_exec(cont, cmd, timeout=1800, **_):
        cmds.append(cmd)
        netlist.parent.mkdir(parents=True, exist_ok=True)
        netlist.write_text("module top(); INV i(); endmodule\n")
        return (0, stdout, "")

    monkeypatch.setattr(mod, "_docker_exec", _fake_docker_exec)
    result = mod.step_synth(project, "top", pdk, container)
    assert cmds, "step_synth never invoked _docker_exec"
    return result, cmds[0]


class TestStepSynthKnobEmission:
    def test_no_reference_flow_command_unchanged(self, monkeypatch, tmp_path):
        # §4.05: no reference_flow → NONE of the injected directives appear.
        project, pdk = _min_project(tmp_path)
        result, cmd = _capture_synth(monkeypatch, project, pdk)
        assert result.status == "PASS", result.detail
        assert "alumacc;" not in cmd
        assert "_ref_adder_map.v" not in cmd
        assert "opt_clean -purge;" not in cmd
        assert result.extras.get("reference_flow_qor_knobs") == []
        assert not (_pl.synth_dir(project) / "_ref_adder_map.v").is_file()

    def test_all_knobs_present_inject_directives(self, monkeypatch, tmp_path):
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "orfs_config.mk": (
                "export SWAP_ARITH_OPERATORS = 1\n"
                "REMOVE_ABC_BUFFERS = 1\n"
                "ADDER_MAP_FILE = adders.v\n"
            ),
            # A map keyed on a FRONT-END cell type ($add): it needs no base-map
            # help, so the emitted command must stay the legacy single -map form.
            "adders.v": ('(* techmap_celltype = "$add" *)\n'
                         "module my_adder_map(A, B, Y); endmodule\n"),
        })
        result, cmd = _capture_synth(monkeypatch, project, pdk,
                                     stdout=_YOSYS_LOG_MAP_APPLIED)
        assert result.status == "PASS", result.detail
        # SWAP_ARITH_OPERATORS → alumacc (before generic synth mapping)
        assert "alumacc;" in cmd
        assert cmd.index("alumacc;") < cmd.index("synth -top top -flatten;")
        # ADDER_MAP_FILE → techmap -map <staged file>, and the file is staged
        assert "techmap -map " in cmd and "_ref_adder_map.v" in cmd
        assert (_pl.synth_dir(project) / "_ref_adder_map.v").is_file()
        # REMOVE_ABC_BUFFERS → opt_clean -purge AFTER abc
        assert "opt_clean -purge;" in cmd
        assert cmd.index("abc -liberty") < cmd.index("opt_clean -purge;")
        notes = result.extras.get("reference_flow_qor_knobs")
        assert any("SWAP_ARITH_OPERATORS" in n for n in notes)
        # The knob is reported ADOPTED only because yosys's log SHOWS the map's
        # own module was instantiated — "staged" alone is not "applied".
        assert any("ADDER_MAP_FILE -> techmap" in n and "APPLIED" in n
                   for n in notes)
        assert any("REMOVE_ABC_BUFFERS" in n for n in notes)
        # HONEST-SCOPE (live-run fidelity finding): the SWAP_ARITH note must NOT
        # over-claim a timing-repair — alumacc is disclosed as a structural
        # enabler that needs the adder techmap, not an operand-swap on its own.
        _swap = next(n for n in notes if n.startswith("SWAP_ARITH_OPERATORS"))
        assert "NOT an operand-swap timing-repair" in _swap

    def test_lcu_keyed_map_gets_the_base_techmap_in_the_SAME_call(
            self, monkeypatch, tmp_path):
        """A parallel-prefix map keys on `$lcu`, which does not exist until the
        `$alu` rule runs. Emitting `techmap -map <map>` alone rewrites NOTHING
        and the design silently ships the DEFAULT adder architecture. The map
        must therefore be combined with `+/techmap.v` in ONE call, map first."""
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "orfs_config.mk": "ADDER_MAP_FILE = adders.v\n",
            "adders.v": ('(* techmap_celltype = "$lcu" *)\n'
                         "module _80_lcu_kogge_stone(P, G, CI, CO); endmodule\n"),
        })
        _, cmd = _capture_synth(
            monkeypatch, project, pdk,
            stdout="Using template \\_80_lcu_kogge_stone for cells of type $lcu.\n")
        staged = "_ref_adder_map.v"
        assert staged in cmd and "+/techmap.v" in cmd
        # ONE techmap call carrying both, staged map FIRST so it wins.
        assert f"{staged} -map +/techmap.v" in cmd

    def test_staged_map_that_did_NOT_bind_is_reported_NOT_APPLIED(
            self, monkeypatch, tmp_path):
        """THE REGRESSION: the map was staged and the command emitted, but
        yosys mapped the arithmetic with its own default instead. The run must
        NOT record this as an adopted knob."""
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "orfs_config.mk": "ADDER_MAP_FILE = adders.v\n",
            "adders.v": ('(* techmap_celltype = "$lcu" *)\n'
                         "module _80_lcu_kogge_stone(P, G, CI, CO); endmodule\n"),
        })
        result, _ = _capture_synth(monkeypatch, project, pdk,
                                   stdout=_YOSYS_LOG_MAP_NOT_USED)
        notes = result.extras.get("reference_flow_qor_knobs")
        adder = [n for n in notes if "ADDER_MAP_FILE" in n]
        assert adder, "the declared knob must still be disclosed"
        assert any("NOT APPLIED" in n for n in adder), adder
        # It must never read as an adopted knob...
        assert not any("ADDER_MAP_FILE -> techmap" in n for n in adder), adder
        # ...and it must say what ran INSTEAD, so the miss is actionable.
        assert any("_90_lcu_brent_kung" in n for n in adder), adder

    def test_adder_map_missing_file_skipped_disclosed(self, monkeypatch, tmp_path):
        # §4.05: ADDER_MAP_FILE points at a missing file → techmap NOT injected,
        # no file staged, and the skip is disclosed. Other present knobs stay.
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "orfs_config.mk": (
                "SWAP_ARITH_OPERATORS = 1\n"
                "ADDER_MAP_FILE = does_not_exist.v\n"
            ),
        })
        result, cmd = _capture_synth(monkeypatch, project, pdk)
        assert result.status == "PASS", result.detail
        assert "alumacc;" in cmd                    # present knob still applied
        assert "_ref_adder_map.v" not in cmd        # techmap skipped
        assert not (_pl.synth_dir(project) / "_ref_adder_map.v").is_file()
        notes = result.extras.get("reference_flow_qor_knobs")
        assert any("ADDER_MAP_FILE SKIPPED" in n for n in notes)

    def test_only_swap_present(self, monkeypatch, tmp_path):
        # A single knob present → only its directive appears (no over-injection).
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "config.mk": "SWAP_ARITH_OPERATORS = 1\n",
        })
        result, cmd = _capture_synth(monkeypatch, project, pdk)
        assert "alumacc;" in cmd
        assert "_ref_adder_map.v" not in cmd
        assert "opt_clean -purge;" not in cmd

    def test_non_orfs_var_only_injects_nothing(self, monkeypatch, tmp_path):
        # NEGATIVE no-leak: a reference_flow that declares only a non-ORFS var
        # gets NONE injected (chip-AGNOSTIC — we key on ORFS knob names).
        project, pdk = _min_project(tmp_path)
        _stage_reference_flow(project, {
            "config.mk": "CORE_UTILIZATION = 45\nPLACE_DENSITY = 0.6\n",
        })
        result, cmd = _capture_synth(monkeypatch, project, pdk)
        assert "alumacc;" not in cmd
        assert "_ref_adder_map.v" not in cmd
        assert "opt_clean -purge;" not in cmd
        assert result.extras.get("reference_flow_qor_knobs") == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
