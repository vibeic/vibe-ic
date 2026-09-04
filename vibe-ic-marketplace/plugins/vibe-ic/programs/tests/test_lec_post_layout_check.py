#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P1 — lec_post_layout_check.py (post-layout LEC gate).

Step 13 proves RTL==synth. This gate re-proves the FINAL routed/repaired netlist ==
synth/RTL after CTS/PnR/ECO/fill. §4.05: a non-proof / vacuous match is a FAIL,
never a pass; an absent routed netlist is an HONEST SKIP.

Covered:
  * build_yosys_equiv_script: emits equiv_make/equiv_simple/equiv_induct/
    equiv_status + reads the PDK blackbox verilog for physical-only cells.
  * parse_equiv_log: proven/unproven counts + verdict from real yosys phrasing.
  * evaluate_report: PASS (real non-vacuous proof) / FAIL (unproven, vacuous,
    non-equivalent, run-error) / SKIP (no routed netlist).
  * CLI: SKIP when the artefact is absent (exit 0, honest not-applicable);
    FAIL when the artefact proves nothing; PASS on a real proof.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lec_post_layout_check as L  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ---- recipe ---------------------------------------------------------------
def test_recipe_has_equiv_engine_and_blackbox():
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top",
        blackbox_v=["/pdk/sc__blackbox.v"])
    for cmd in ("equiv_make gold gate equiv", "equiv_simple", "equiv_induct",
                "equiv_status", "read_liberty -lib lib.lib"):
        assert cmd in ys, cmd
    # the physical-cell blackbox is read as -lib (inert modules), and
    # -nooverwrite so it can only ADD cells the Liberty does not define — a
    # plain -lib read collides with the Liberty cells of the same name and
    # yosys aborts the whole proof ("Re-definition of module").
    assert "read_verilog -lib -nooverwrite /pdk/sc__blackbox.v" in ys
    assert "read_verilog -sv gold.v" in ys and "read_verilog -sv gate.v" in ys


def test_recipe_no_blackbox_ok():
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top")
    assert "equiv_status" in ys
    assert "read_verilog -lib" not in ys  # none supplied


# ---- FUNCTIONAL (sound) recipe -------------------------------------------
def test_functional_recipe_reads_liberty_without_lib():
    # functional_lib=True → SOUND models: `read_liberty <lib>` (NO -lib) so
    # equiv proves each cell's function instead of assuming matched cells equal.
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top",
                                    functional_lib=True)
    assert "read_liberty lib.lib" in ys        # functional read
    assert "read_liberty -lib lib.lib" not in ys   # NOT the blackbox false-pass
    # the three GOTCHA transforms that make functional models reach the miter:
    assert "flatten" in ys                     # GOTCHA 1: models survive copy
    assert "async2sync" in ys                  # GOTCHA 2: latch/ICG handling
    assert "opt -purge" in ys and "opt_clean -purge" in ys  # GOTCHA 3: dead nets
    # engine tail unchanged
    for cmd in ("equiv_make gold gate equiv", "equiv_simple", "equiv_induct",
                "equiv_status"):
        assert cmd in ys, cmd
    # order: flatten before design -stash (so models are inlined before copy),
    # async2sync after prep and before equiv_make.
    assert ys.index("flatten") < ys.index("design -stash gold")
    assert ys.index("async2sync") < ys.index("equiv_make gold gate equiv")


def test_functional_recipe_keeps_physical_blackbox():
    # physical-only cells (fill/tap/decap/diode) still read -lib as inert
    # blackboxes even in the functional recipe (they carry no function).
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top",
        blackbox_v=["/pdk/sc__fill.v"], functional_lib=True)
    assert "read_verilog -lib -nooverwrite /pdk/sc__fill.v" in ys


def test_functional_recipe_strips_gate_supply_ports():
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top",
        strip_gate_ports=["VDD", "VSS"], functional_lib=True)
    assert "delete top/w:VDD" in ys and "delete top/w:VSS" in ys
    assert ys.index("delete top/w:VDD") < ys.index("equiv_make gold gate equiv")


@pytest.mark.parametrize("functional", [True, False])
def test_recipe_reads_exact_extra_liberty_and_constrains_each_arm(functional):
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "std.lib", "top",
        extra_libs=["io.lib"], functional_lib=functional,
        constant_gold_wires={"VDD": 1, "VSS": 0},
        constant_gate_wires={"VDD": 1, "VSS": 0})
    option = "" if functional else "-lib "
    assert ys.count(f"read_liberty {option}std.lib") == 2
    assert ys.count(f"read_liberty {option}io.lib") == 2
    gold_half, gate_half = ys.split("design -stash gold", 1)
    for half in (gold_half, gate_half):
        assert "connect -set VDD 1'b1" in half
        assert "connect -set VSS 1'b0" in half
        assert half.index("connect -set VDD") < half.index("opt")


def test_recipe_refuses_non_boolean_supply_constant():
    with pytest.raises(ValueError, match="non-Boolean"):
        L.build_yosys_equiv_script(
            "gold.v", "gate.v", "std.lib", "top",
            constant_gate_wires={"VDD": 2})


def test_restore_named_instance_connections_adds_only_requested_pins_and_wires():
    src = """module chip_top(input a, output y);
  PAD u_pad (
    .PAD(a),
    .Y(y)
  );
endmodule
"""
    out, stats = L.restore_named_instance_connections(
        src, "chip_top", [("u_pad", "OE", "VDD"),
                           ("u_pad", "PU", "VSS")],
        internal_wires=["VDD", "VSS"])
    assert "wire VDD;" in out and "wire VSS;" in out
    assert ".OE(VDD)" in out and ".PU(VSS)" in out
    assert ".PAD(a)" in out and ".Y(y)" in out
    assert stats["requested"] == 2 and stats["restored"] == 2
    again, stats2 = L.restore_named_instance_connections(
        out, "chip_top", [("u_pad", "OE", "VDD"),
                           ("u_pad", "PU", "VSS")],
        internal_wires=["VDD", "VSS"])
    assert again == out
    assert stats2["already_present"] == 2 and stats2["restored"] == 0


def test_restore_named_instance_connections_refuses_conflict_and_missing_instance():
    src = ("module chip_top(input a, output y); "
           "PAD u_pad(.PAD(a), .Y(y), .OE(VSS)); endmodule\n")
    with pytest.raises(ValueError, match="does not equal DEF-proven"):
        L.restore_named_instance_connections(
            src, "chip_top", [("u_pad", "OE", "VDD")])
    with pytest.raises(ValueError, match="found 0"):
        L.restore_named_instance_connections(
            src, "chip_top", [("u_absent", "OE", "VDD")])


def test_blackbox_recipe_is_the_default_and_unchanged():
    # functional_lib defaults False → the always-available (-lib) recipe, byte-
    # for-byte the pre-functional script (guards the proven path from drift).
    default = L.build_yosys_equiv_script("g.v", "n.v", "l.lib", "top")
    explicit = L.build_yosys_equiv_script("g.v", "n.v", "l.lib", "top",
                                          functional_lib=False)
    assert default == explicit
    assert "read_liberty -lib l.lib" in default
    assert "async2sync" not in default  # no functional-only transforms


# ---- functional read_liberty capability probe ----------------------------
def test_probe_classifier_detects_icg_abort():
    # the pre-fork functional read_liberty abort on an ICG cell → fall back.
    log = ("Executing Liberty frontend.\n"
           "ERROR: Missing function on output GCLK of cell dlclkp.\n")
    assert L.functional_read_liberty_aborted(log) is True


def test_probe_classifier_ignores_equiv_sat_gap():
    # the equiv-time "No SAT model available for cell …" is the NORMAL inert
    # physical-cell gap — it must NOT trigger a spurious functional→-lib fallback.
    log = ("Found 10 $equiv cells in equiv:\n"
           "ERROR: No SAT model available for cell _1__gate (FILLER).\n")
    assert L.functional_read_liberty_aborted(log) is False


def test_build_functional_probe_script():
    s = L.build_functional_probe_script("/pdk/x.lib")
    assert s.strip() == "read_liberty /pdk/x.lib"   # NO -lib → functional read


# ---- SOUNDNESS parser gate: matched-output function bug is NEVER a PASS ----
def test_parser_matched_output_function_bug_is_not_pass():
    # A gold NAND2 vs gate NOR2 (matched ports, genuinely different function)
    # leaves the output $equiv cell UNPROVEN. The parser MUST return UNPROVEN,
    # never PROVEN_EQUIVALENT — this locks in that we never regress to the -lib
    # blackbox false-pass (which reports this pair "proven").
    log = ("Found 1 $equiv cells in equiv:\n"
           "  Of those cells 0 are proven and 1 are unproven.\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_UNPROVEN
    assert r["equivalent"] is False
    assert L.evaluate_report({"verdict": r["verdict"], "total_points": 1,
                              "proven_points": 0, "unproven_points": 1,
                              "equivalent": False})["result"] == "FAIL"


def test_parser_buffer_insert_positive_proves():
    log = ("Found 3 $equiv cells in equiv:\n"
           "  Of those cells 3 are proven and 0 are unproven.\n"
           "Equivalence successfully proven!\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_PASS and r["equivalent"] is True


# ---- REAL in-container soundness negative control (fork-safe, NDA-clean) ---
# The strongest gate: actually run the FUNCTIONAL recipe on a synthetic
# combinational Liberty and assert the engine UNPROVES a matched-output function
# bug and PROVES a buffer-insert. functional read_liberty works on the current
# image for combinational cells (the fork fix is only needed for ICG cells), so
# this runs TODAY. Skips when no usable, path-visible container is available.
def _container_sees(root: Path) -> bool:
    """True iff `docker exec vibeic-eda` can read a probe file under `root` (i.e.
    the path is bind-mounted at the same absolute path inside the container)."""
    try:
        probe = root / ".lec_container_probe"
        probe.write_text("ok")
        r = _pr.run(
            ["docker", "exec", "vibeic-eda", "bash", "-lc",
             f"test -f {probe} && cat {probe}"],
            capture_output=True, text=True)
        probe.unlink(missing_ok=True)
        return r.returncode == 0 and "ok" in (r.stdout or "")
    except (subprocess.SubprocessError, OSError):
        return False


def _mounted_workdir(tmp_path: Path):
    """A container-visible work dir + a cleanup callback. Prefer pytest's
    tmp_path (auto-cleaned); if that isn't bind-mounted into the container, fall
    back to a self-cleaning tempdir under $HOME (mounted here). Returns
    (dir, cleanup) or (None, noop) when no container-visible path exists."""
    if _container_sees(tmp_path):
        return tmp_path, (lambda: None)
    import tempfile
    import shutil
    d = Path(tempfile.mkdtemp(prefix=".lec_it_", dir=str(Path.home())))
    if _container_sees(d):
        return d, (lambda: shutil.rmtree(d, ignore_errors=True))
    shutil.rmtree(d, ignore_errors=True)
    return None, (lambda: None)


def _run_equiv_in_container(ys_text: str, ys_path: Path) -> dict:
    ys_path.write_text(ys_text)
    cmd = (f"export PATH=/foss/tools/yosys/bin:/foss/tools/bin:$PATH && "
           f"yosys -s {ys_path} 2>&1")
    r = _pr.run(["docker", "exec", "vibeic-eda", "bash", "-lc", cmd],
                       capture_output=True, text=True)
    log = "\n".join(ln for ln in (r.stdout or "").splitlines()
                    if not ln.lstrip().startswith("[INFO]"))
    return L.parse_equiv_log(log)


_SOUNDNESS_LIB = """library(soundness) {
  cell(AND2X1) { area:1;
    pin(A){direction:input;} pin(B){direction:input;}
    pin(Y){direction:output; function:"(A*B)";} }
  cell(NAND2X1) { area:1;
    pin(A){direction:input;} pin(B){direction:input;}
    pin(Y){direction:output; function:"(A*B)'";} }
  cell(BUFX1) { area:1;
    pin(A){direction:input;}
    pin(Y){direction:output; function:"A";} }
}
"""


def test_functional_recipe_unproves_function_bug_in_container(tmp_path):
    work, cleanup = _mounted_workdir(tmp_path)
    if work is None:
        pytest.skip("vibeic-eda container not available / path not bind-mounted")
    try:
        lib = work / "soundness.lib"
        lib.write_text(_SOUNDNESS_LIB)
        (work / "gold_and.v").write_text(
            "module top(input a, input b, output y);\n"
            "  AND2X1 u0(.A(a), .B(b), .Y(y));\nendmodule\n")
        (work / "gate_nand.v").write_text(
            "module top(input a, input b, output y);\n"
            "  NAND2X1 u0(.A(a), .B(b), .Y(y));\nendmodule\n")
        (work / "gold_buf.v").write_text(
            "module top(input a, output y);\n"
            "  BUFX1 u0(.A(a), .Y(y));\nendmodule\n")
        (work / "gate_buf.v").write_text(
            "module top(input a, output y);\n  wire t;\n"
            "  BUFX1 u0(.A(a), .Y(t));\n  BUFX1 u1(.A(t), .Y(y));\nendmodule\n")

        # (neg) functional recipe MUST NOT prove a matched-output function bug.
        neg = _run_equiv_in_container(
            L.build_yosys_equiv_script(str(work / "gold_and.v"),
                                       str(work / "gate_nand.v"), str(lib), "top",
                                       functional_lib=True),
            work / "neg.ys")
        assert neg["verdict"] != L.V_PASS, neg
        assert neg["equivalent"] is False

        # (bug) the -lib blackbox recipe FALSE-PASSES the same pair — documents
        # the unsoundness the functional path fixes (-lib is fallback-only).
        bug = _run_equiv_in_container(
            L.build_yosys_equiv_script(str(work / "gold_and.v"),
                                       str(work / "gate_nand.v"), str(lib), "top",
                                       functional_lib=False),
            work / "bug.ys")
        assert bug["verdict"] == L.V_PASS, (
            "the -lib blackbox recipe is expected to false-pass; if it no "
            "longer does, update this soundness rationale")

        # (pos) functional recipe MUST prove a genuine buffer-insert equivalence.
        pos = _run_equiv_in_container(
            L.build_yosys_equiv_script(str(work / "gold_buf.v"),
                                       str(work / "gate_buf.v"), str(lib), "top",
                                       functional_lib=True),
            work / "pos.ys")
        assert pos["verdict"] == L.V_PASS, pos
        assert pos["unproven"] == 0
    finally:
        cleanup()


# ---- v1.3.93 gate-only supply-port strip ----------------------------------
def test_recipe_strips_gate_supply_ports_before_equiv():
    # The routed gate netlist carries PDN-added VDD/VSS top ports the synth gold
    # lacks; equiv_make can't match the port lists. The recipe must delete those
    # supply ports from the GATE design (after prep, before equiv_make).
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top",
        strip_gate_ports=["VDD", "VSS"])
    assert "delete top/w:VDD" in ys and "delete top/w:VSS" in ys
    # the strip must sit AFTER the gate prep and BEFORE equiv_make
    assert ys.index("delete top/w:VDD") < ys.index("equiv_make gold gate equiv")
    assert "opt_clean" in ys


def test_recipe_no_strip_when_none():
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top")
    assert "delete top/w:" not in ys  # nothing stripped by default


# ---- auto-escalating sequential-induction depth ---------------------------
def test_recipe_default_escalates_seq_depth():
    # Default must emit escalating equiv_induct -seq passes (retiming/pipeline
    # equivalence needs induction depth >= latency; the shallow yosys default
    # -seq 4 falsely reports UNPROVEN). Escalation is sound: deeper only proves
    # more genuinely-equivalent cells, never an inequivalent pair.
    ys = L.build_yosys_equiv_script("gold.v", "gate.v", "lib.lib", "top")
    for d in L.DEFAULT_SEQ_DEPTHS:
        assert f"equiv_induct -seq {d}" in ys, d
    # ascending order (shallow first keeps the common case cheap)
    idxs = [ys.index(f"equiv_induct -seq {d}") for d in (4, 16, 64)]
    assert idxs == sorted(idxs)
    # deepest induct comes before the final status readout
    assert ys.index("equiv_induct -seq 64") < ys.index("equiv_status")


def test_recipe_custom_seq_depths_sorted_deduped():
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "top", seq_depths=[32, 8, 8, 0, -1])
    # positives only, de-duplicated, ascending
    assert "equiv_induct -seq 8" in ys and "equiv_induct -seq 32" in ys
    assert "equiv_induct -seq 0" not in ys and "equiv_induct -seq -1" not in ys
    assert ys.index("equiv_induct -seq 8") < ys.index("equiv_induct -seq 32")
    assert ys.count("equiv_induct -seq 8") == 1  # de-duplicated


# ---- parser ---------------------------------------------------------------
def test_parse_clean_pass():
    log = ("Found 128 $equiv cells in equiv:\n"
           "  Of those cells 128 are proven and 0 are unproven.\n"
           "Equivalence successfully proven!\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_PASS
    assert r["proven"] == 128 and r["unproven"] == 0 and r["total"] == 128
    assert r["equivalent"] is True


def test_parse_unproven_is_not_pass():
    # the REAL spm RTL-vs-routed shape: 32 proven / 32 unproven -> UNPROVEN.
    log = ("Found 64 $equiv cells in equiv:\n"
           "  Of those cells 32 are proven and 32 are unproven.\n")
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_UNPROVEN
    assert r["unproven"] == 32 and r["proven"] == 32 and r["total"] == 64
    assert r["equivalent"] is False


def test_parse_vacuous_zero_cells():
    log = "Found 0 $equiv cells in equiv:\nEquivalence successfully proven!\n"
    r = L.parse_equiv_log(log)
    assert r["verdict"] == L.V_VACUOUS
    assert r["equivalent"] is False


def test_parse_run_error_empty():
    assert L.parse_equiv_log("")["verdict"] == L.V_RUN_ERROR
    assert L.parse_equiv_log("ERROR: Module foo not found\n")["verdict"] \
        == L.V_RUN_ERROR


def test_parse_sat_gap_cells_surfaced():
    log = ("Warning: Failed to import cell INVD1: has no model for cell type "
           "`INVD1'\n"
           "Found 10 $equiv cells in equiv:\n"
           "  Of those cells 8 are proven and 2 are unproven.\n")
    r = L.parse_equiv_log(log)
    assert "INVD1" in r["sat_unsupported_cells"]
    assert r["verdict"] == L.V_UNPROVEN  # 2 unproven -> not a clean pass


# ---- gate over the artefact ----------------------------------------------
def test_gate_pass_on_real_proof():
    doc = {"verdict": L.V_PASS, "total_points": 286, "proven_points": 286,
           "unproven_points": 0, "equivalent": True}
    assert L.evaluate_report(doc)["result"] == "PASS"


def test_gate_fail_on_unproven():
    doc = {"verdict": L.V_UNPROVEN, "total": 64, "proven": 32, "unproven": 32,
           "equivalent": False}
    res = L.evaluate_report(doc)
    assert res["result"] == "FAIL"
    assert any("UNPROVEN" in f for f in res["findings"])


def test_gate_fail_on_vacuous_true():
    # §4.05: equivalent==true with 0 points compared is NOT a pass.
    doc = {"verdict": L.V_PASS, "total_points": 0, "equivalent": True}
    assert L.evaluate_report(doc)["result"] == "FAIL"


def test_gate_fail_on_non_equivalent():
    doc = {"verdict": L.V_NONEQUIV, "total_points": 10, "proven_points": 8,
           "non_equivalent_points": 2, "equivalent": False}
    res = L.evaluate_report(doc)
    assert res["result"] == "FAIL"


def test_gate_skip_when_no_routed_netlist():
    res = L.evaluate_report({"verdict": L.V_SKIP, "skipped": True,
                             "skip_reason": "not placed-and-routed"})
    assert res["result"] == "SKIP"


# ---- CLI ------------------------------------------------------------------
def _write(project: Path, doc: dict) -> Path:
    p = project / "reports" / "phase3" / "lec_post_layout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))
    return p


def test_cli_skip_when_absent(tmp_path):
    # No artefact => honest SKIP => exit 0 (not a FAIL of a check that could not
    # apply, and never a vacuous pass).
    assert L.main([str(tmp_path)]) == 0


def test_cli_pass(tmp_path):
    _write(tmp_path, {"verdict": L.V_PASS, "total_points": 100,
                      "proven_points": 100, "unproven_points": 0,
                      "equivalent": True})
    assert L.main([str(tmp_path)]) == 0


def test_cli_fail_on_unproven(tmp_path):
    _write(tmp_path, {"verdict": L.V_UNPROVEN, "total": 64, "proven": 32,
                      "unproven": 32, "equivalent": False})
    assert L.main([str(tmp_path)]) == 1


def test_cli_fail_on_unparseable(tmp_path):
    p = tmp_path / "reports" / "phase3" / "lec_post_layout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert L.main([str(tmp_path)]) == 1
