"""programs/tests/test_v0_2_97_issue472_473_476_phase2.py

End-to-end + regression coverage for three design_one_shot_runner defects
(all chip-AGNOSTIC; fixtures use synthetic structural names only):

  #472 (HIGH)  provenance.jsonl truncate-rewrite — a phase2 re-invocation
               destroyed phase3's openroad declarations (routed.def /
               <top>_pnr.v / sta.rpt / *.spef). The journal must be
               phase-scoped / append-only: the phase2 synth writer may
               retire ONLY entries it owns, never another phase's.

  #473 (MEDIUM) oracle truth vs skeleton split — the connectivity skeleton
               authored sim_full_stack/results.json with
               functional_verified:false (0/N UNVERIFIED), SHADOWING the
               genuine oracle PASS. The genuine oracle PASS must rewrite the
               canonical results.json to reflect the oracle verdict; a
               skeleton-only run keeps functional_verified:false.

  #476 (LOW)   oracle TB $readmemh relative paths don't resolve — the
               runner ran vvp with cwd=sim_full_stack/oracle_run while the
               TB-referenced hex sat in the parent. The runner must stage
               referenced $readmem{h,b} files into the run cwd so the
               firmware actually loads.

ACCEPTANCE DOCTRINE: each test builds a defect-artifact fixture shaped like
the issue's 現象, executes the issue's ## 驗收 criteria via the REAL program
path, and asserts the END state.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_PROGRAMS = _TESTS_DIR.parent
for _p in (str(_PROGRAMS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import design_one_shot_runner as p2  # noqa: E402
import _path_layout as _pl  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for ch in iter(lambda: f.read(65536), b""):
            h.update(ch)
    return "sha256:" + h.hexdigest()


def _read_journal(prov: Path) -> list[dict]:
    out = []
    for ln in prov.read_text().splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))
    return out


# ===========================================================================
# #472 — provenance journal is phase-scoped / append-only
# ===========================================================================
def _seed_phase3_provenance(project: Path) -> dict:
    """Author a defect-artifact journal exactly like the field .bak: three
    entries — one yosys (phase2 synth) + two openroad (phase3). Returns the
    openroad output paths so the test can assert survival."""
    # phase3 artefacts on disk so a consumer (provenance_check) can verify.
    pnr = project / "phase3/stage3/pnr"
    extracted = project / "phase3/stage3/extracted"
    pnr.mkdir(parents=True, exist_ok=True)
    extracted.mkdir(parents=True, exist_ok=True)
    routed = pnr / "routed.def"
    pnr_v = pnr / "chip_top_pnr.v"
    sta = pnr / "sta.rpt"
    spef = extracted / "synthtop.spef"
    routed.write_text("VERSION 5.8 ;\nDESIGN synthtop ;\nEND DESIGN\n")
    pnr_v.write_text("module synthtop(); endmodule\n")
    sta.write_text("worst slack 0.12\n")
    spef.write_text("*SPEF \"IEEE 1481-1998\"\n")

    prov = project / "provenance.jsonl"
    entries = [
        {  # phase2 yosys (stale — will be superseded by the real synth)
            "tool": "yosys", "exit_code": 0,
            "timestamp": "2026-06-01T00:00:00Z",
            "step": "phase2:yosys_synth",
            "outputs": {
                "phase2/stage2/synth/netlist_yosys.v": "sha256:" + "0" * 64,
                "phase2/stage2/synth/netlist.v": "sha256:" + "0" * 64,
            },
        },
        {  # phase3 openroad — pnr (THE entry the bug destroyed)
            "tool": "openroad", "exit_code": 0,
            "timestamp": "2026-06-02T00:00:00Z",
            "outputs": {
                "phase3/stage3/pnr/routed.def": _sha256(routed),
                "phase3/stage3/pnr/chip_top_pnr.v": _sha256(pnr_v),
                "phase3/stage3/pnr/sta.rpt": _sha256(sta),
            },
        },
        {  # phase3 openroad — extracted SPEF
            "tool": "openroad", "exit_code": 0,
            "timestamp": "2026-06-02T00:01:00Z",
            "outputs": {
                "phase3/stage3/extracted/synthtop.spef": _sha256(spef),
            },
        },
    ]
    prov.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return {
        "prov": prov,
        "openroad_paths": {
            "phase3/stage3/pnr/routed.def",
            "phase3/stage3/pnr/chip_top_pnr.v",
            "phase3/stage3/pnr/sta.rpt",
            "phase3/stage3/extracted/synthtop.spef",
        },
        "routed": routed,
    }


def _author_minimal_rtl(project: Path, top: str = "synthtop") -> Path:
    rtl_dir = _pl.rtl_dir(project)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    src = rtl_dir / f"{top}.v"
    src.write_text(
        f"module {top}(input wire clk, input wire rst,\n"
        f"             input wire [7:0] d, output reg [7:0] q);\n"
        f"  always @(posedge clk) begin\n"
        f"    if (rst) q <= 8'h00; else q <= d + 8'h01;\n"
        f"  end\n"
        f"endmodule\n")
    return src


@pytest.mark.skipif(shutil.which("yosys") is None,
                    reason="yosys not available for end-to-end synth re-run")
def test_472_phase2_resynth_preserves_phase3_provenance(tmp_path):
    """## 驗收 (472): fixture journal with phase3 openroad entries + re-run
    the phase2 writer → openroad entries preserved.

    END-TO-END: seed the defect-shaped journal, author minimal RTL, then run
    the REAL step_yosys_synth (host yosys). Assert the openroad entries
    survive AND the consumer (provenance_check.py) still PASSes on routed.def.
    """
    project = tmp_path / "proj"
    project.mkdir()
    seeded = _seed_phase3_provenance(project)
    _author_minimal_rtl(project, "synthtop")

    res = p2.step_yosys_synth(project, top_name="synthtop")
    assert res.status == "PASS", f"synth did not PASS: {res.detail[:400]}"

    entries = _read_journal(seeded["prov"])
    surviving_openroad = {
        rel
        for e in entries
        if e.get("tool") == "openroad"
        for rel in (e.get("outputs") or {})
    }
    # END STATE: every phase3 openroad output is still declared.
    assert seeded["openroad_paths"] <= surviving_openroad, (
        "phase3 openroad provenance was DESTROYED by the phase2 re-run; "
        f"missing={seeded['openroad_paths'] - surviving_openroad}")

    # A fresh yosys entry must now exist (the supersede dropped the stale one
    # and appended the current one) — exactly one phase2-owned yosys entry.
    yosys_entries = [e for e in entries if e.get("tool") == "yosys"]
    assert len(yosys_entries) == 1, (
        f"expected exactly 1 fresh yosys entry, got {len(yosys_entries)}")

    # Real consumer invocation: provenance_check on routed.def must PASS
    # (the openroad attribution survived AND its hash still matches disk).
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "provenance_check.py"),
         str(project),
         "--output", "phase3/stage3/pnr/routed.def", "--tool", "openroad"],
        capture_output=True, text=True)
    assert proc.returncode == 0, (
        "provenance_check FAILed on a genuine routed.def after phase2 "
        f"re-run:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}")
    assert "Overall: PASS" in proc.stdout, proc.stdout


def test_472_writer_unit_phase_scoped_supersede():
    """Unit guard for the phase-scoped supersede helper: a phase2 synth
    writer must NEVER retire a foreign-phase entry, even if (defensively)
    its outputs ever intersected the synth paths."""
    # phase3 entry that (pathologically) ALSO declares a phase2 synth path —
    # the OLD path-intersection rule would have dropped it; the new
    # phase-ownership rule keeps it because it carries a phase3 output too.
    foreign = {
        "tool": "openroad", "exit_code": 0,
        "outputs": {
            "phase3/stage3/pnr/routed.def": "sha256:" + "a" * 64,
            "phase2/stage2/synth/netlist.v": "sha256:" + "b" * 64,
        },
    }
    own_legacy = {  # legacy phase2 entry, no step tag, only phase2 outputs
        "tool": "yosys", "exit_code": 0,
        "outputs": {"phase2/stage2/synth/netlist.v": "sha256:" + "c" * 64},
    }
    own_tagged = {  # phase2-tagged entry
        "tool": "yosys", "exit_code": 0,
        "step": "phase2:yosys_synth",
        "outputs": {"phase2/stage2/synth/netlist_yosys.v": "sha256:" + "d" * 64},
    }
    no_outputs = {"tool": "analog", "exit_code": 0, "note": "no-outputs entry"}

    assert p2._is_phase2_owned(own_legacy) is True
    assert p2._is_phase2_owned(own_tagged) is True
    # A mixed entry that carries even one foreign output is NOT phase2-owned.
    assert p2._is_phase2_owned(foreign) is False
    # An entry with no outputs and no phase2: tag is not ours to retire.
    assert p2._is_phase2_owned(no_outputs) is False


# ===========================================================================
# #473 — genuine oracle PASS is authoritative for the canonical results.json
# ===========================================================================
def _skeleton_results(functional_verified: bool) -> dict:
    """A connectivity-skeleton results.json shaped like the defect: 0/8
    UNVERIFIED, functional_verified:false."""
    per_vector = [
        {"vector_id": f"vec_brk_{i}", "expected_bytes": None,
         "actual_bytes": None, "verdict": "UNVERIFIED",
         "evidence": "step_full_stack_tb_gen.bring_up_pad",
         "source": "bring-up padding"}
        for i in range(8)
    ]
    return {
        "verdict": "PASS", "pass": True, "connectivity_verified": True,
        "functional_verified": functional_verified,
        "functional_coverage": {"scored_with_golden": 0, "placeholder": 8},
        "tb": "tb_synthtop_full.v", "dut": "synthtop",
        "opcodes_tested": ["0x10", "0x20"],
        "input_doc_evidence": "Connectivity skeleton evidence",
        "command_oracle_applicable": True,
        "per_vector": per_vector,
        "vectors_total": 8, "vectors_passed": 0, "vectors_failed": 8,
    }


def _write_oracle_transcript(run_dir: Path, n_pass: int, n_total: int,
                             named: int) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(named):
        lines.append(f"ORACLE_VECTOR scenario_{i} PASS")
    lines.append(f"ORACLE_TB_DONE pass={n_pass}/{n_total}")
    transcript = run_dir / "oracle.log"
    transcript.write_text("\n".join(lines) + "\n")
    return transcript


def test_473_oracle_pass_rewrites_canonical_results(tmp_path):
    """## 驗收 (473): oracle-PASS replica → canonical results.json shows
    functional_verified:true with oracle counts.

    END-TO-END: skeleton authored the shadowing results.json; the genuine
    oracle bridge then runs the REAL merge. Assert the canonical file flips
    to the oracle verdict AND the downstream bit-level oracle gate accepts it.
    """
    project = tmp_path / "proj"
    sim_fs = _pl.sim_full_stack_dir(project)
    sim_fs.mkdir(parents=True, exist_ok=True)
    results_path = sim_fs / "results.json"
    # Defect-artifact: skeleton shadow (0/8 UNVERIFIED).
    results_path.write_text(json.dumps(_skeleton_results(False), indent=2))

    run_dir = sim_fs / "oracle_run"
    transcript = _write_oracle_transcript(run_dir, n_pass=8, n_total=8,
                                          named=8)

    ok = p2._merge_oracle_into_full_stack_results(
        project, transcript, n_pass=8, n_total=8)
    assert ok is True

    merged = json.loads(results_path.read_text())
    # END STATE: oracle verdict is now authoritative.
    assert merged["functional_verified"] is True
    assert merged["vectors_passed"] == 8
    assert merged["vectors_total"] == 8
    assert merged["vectors_failed"] == 0
    assert merged.get("verification_track") == "oracle_tb"
    assert len(merged["per_vector"]) == 8
    # Every vector is a concrete-golden PASS (never UNVERIFIED).
    assert all(v["verdict"] == "PASS" for v in merged["per_vector"])
    # Skeleton connectivity info preserved as a secondary section.
    assert "connectivity_skeleton" in merged
    assert merged["connectivity_skeleton"].get("connectivity_verified") is True

    # Real downstream gate invocation: bit_level_full_stack_tb_oracle_check
    # must NOT FAIL on the merged file (no shadow, concrete goldens).
    proc = subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "bit_level_full_stack_tb_oracle_check.py"),
         str(project)],
        capture_output=True, text=True)
    # exit 0 = PASS/SKIP, exit 1 = FAIL. The merged file is a real functional
    # PASS, so it must not be a FAIL.
    assert proc.returncode == 0, (
        "bit-level oracle gate FAILed on the merged oracle results.json:\n"
        f"STDOUT={proc.stdout}\nSTDERR={proc.stderr}")


def test_473_oracle_pass_pads_when_log_names_fewer(tmp_path):
    """When the transcript summary counts more matched vectors than it names
    individually, the merge pads with positional concrete-golden PASS vectors
    (never UNVERIFIED) so vectors_passed==vectors_total holds."""
    project = tmp_path / "proj"
    sim_fs = _pl.sim_full_stack_dir(project)
    (sim_fs / "oracle_run").mkdir(parents=True, exist_ok=True)
    transcript = _write_oracle_transcript(
        sim_fs / "oracle_run", n_pass=10, n_total=10, named=3)
    ok = p2._merge_oracle_into_full_stack_results(
        project, transcript, n_pass=10, n_total=10)
    assert ok is True
    merged = json.loads((sim_fs / "results.json").read_text())
    assert merged["vectors_total"] == 10
    assert len(merged["per_vector"]) == 10
    assert all(v["verdict"] == "PASS" for v in merged["per_vector"])
    # input_doc_evidence is always a non-empty string (gate Rule 3).
    assert isinstance(merged["input_doc_evidence"], str)
    assert merged["input_doc_evidence"].strip()


def test_473_negative_skeleton_only_stays_false(tmp_path):
    """Negative: a skeleton-only run (no oracle verdict) keeps
    functional_verified:false — the merge is never invoked, and a degenerate
    (non-genuine) call must refuse to write."""
    project = tmp_path / "proj"
    sim_fs = _pl.sim_full_stack_dir(project)
    sim_fs.mkdir(parents=True, exist_ok=True)
    results_path = sim_fs / "results.json"
    results_path.write_text(json.dumps(_skeleton_results(False), indent=2))

    # No genuine PASS conditions: n_pass != n_total → merge refuses.
    run_dir = sim_fs / "oracle_run"
    transcript = _write_oracle_transcript(run_dir, n_pass=4, n_total=8,
                                          named=4)
    refused = p2._merge_oracle_into_full_stack_results(
        project, transcript, n_pass=4, n_total=8)
    assert refused is False
    # END STATE unchanged: still the skeleton false verdict.
    still = json.loads(results_path.read_text())
    assert still["functional_verified"] is False
    assert still["vectors_passed"] == 0


# ===========================================================================
# #476 — $readmem relative-path staging contract for the oracle run
# ===========================================================================
def test_476_stage_readmem_copies_hex_into_run_cwd(tmp_path):
    """Unit: a TB referencing a relative $readmemh with the hex next to the
    TB → the staging helper copies it into the run cwd."""
    sim_fs = tmp_path / "sim_full_stack"
    sim_fs.mkdir(parents=True)
    tb = sim_fs / "tb_synthtop_oracle.v"
    tb.write_text(
        "module tb_synthtop_oracle;\n"
        "  reg [7:0] mem [0:15];\n"
        "  initial $readmemh(\"fw.hex\", mem);\n"
        "endmodule\n")
    (sim_fs / "fw.hex").write_text("01\n02\n03\n")
    run_dir = sim_fs / "oracle_run"
    run_dir.mkdir()

    staged = p2._stage_readmem_files(tb, run_dir)
    assert staged == ["fw.hex"]
    # END STATE: the run cwd now resolves the reference.
    assert (run_dir / "fw.hex").is_file()
    assert (run_dir / "fw.hex").read_text() == "01\n02\n03\n"


def test_476_stage_readmem_subdir_and_idempotent(tmp_path):
    """Sub-directory refs are staged preserving the sub-path; an already
    resolvable ref is left alone; an absolute path that already resolves at
    sim time is NOT re-staged (cwd-independent)."""
    sim_fs = tmp_path / "sim_full_stack"
    (sim_fs / "rom").mkdir(parents=True)
    tb = sim_fs / "tb_x_oracle.v"
    abs_hex = tmp_path / "abs_fw.hex"
    abs_hex.write_text("ff\n")
    tb.write_text(
        "module tb_x_oracle;\n"
        "  reg [7:0] m [0:3];\n"
        "  reg [7:0] n [0:3];\n"
        "  reg [7:0] a [0:3];\n"
        "  initial begin\n"
        "    $readmemh(\"rom/code.hex\", m);\n"
        "    $readmemb(\"present.hex\", n);\n"
        f"    $readmemh(\"{abs_hex}\", a);\n"
        "  end\n"
        "endmodule\n")
    (sim_fs / "rom" / "code.hex").write_text("0a\n")
    run_dir = sim_fs / "oracle_run"
    run_dir.mkdir()
    # `present.hex` already resolvable from run cwd — must be left untouched.
    (run_dir / "present.hex").write_text("KEEP\n")

    staged = p2._stage_readmem_files(tb, run_dir)
    # sub-path preserved
    assert (run_dir / "rom" / "code.hex").is_file()
    assert (run_dir / "rom" / "code.hex").read_text() == "0a\n"
    assert "rom/code.hex" in staged
    # already-present ref untouched (NOT re-staged)
    assert (run_dir / "present.hex").read_text() == "KEEP\n"
    assert "present.hex" not in staged
    # An ABSOLUTE path already resolves at sim time regardless of cwd — it is
    # NOT staged (no copy needed) and is not reported as staged.
    assert str(abs_hex) not in staged
    assert not (run_dir / "abs_fw.hex").exists()


def test_476_stage_readmem_missing_source_is_skipped(tmp_path):
    """A referenced file with no resolvable source is skipped silently (the
    oracle FAIL transcript already surfaces an unloaded memory)."""
    sim_fs = tmp_path / "sim_full_stack"
    sim_fs.mkdir(parents=True)
    tb = sim_fs / "tb_y_oracle.v"
    tb.write_text(
        "module tb_y_oracle;\n"
        "  reg [7:0] m [0:3];\n"
        "  initial $readmemh(\"nowhere.hex\", m);\n"
        "endmodule\n")
    run_dir = sim_fs / "oracle_run"
    run_dir.mkdir()
    staged = p2._stage_readmem_files(tb, run_dir)
    assert staged == []
    assert not (run_dir / "nowhere.hex").exists()


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available for end-to-end oracle run")
def test_476_oracle_run_loads_firmware_via_staged_hex(tmp_path):
    """## 驗收 (476): TB with a relative $readmemh + hex in TB dir → the
    staged run cwd contains the hex (or cwd strategy resolves it) and the
    reference resolves.

    END-TO-END: a real iverilog/vvp oracle run whose TB loads firmware via a
    relative $readmemh. Without staging the memory stays X (firmware never
    loads); with the fix the hex is staged into oracle_run/ and the firmware
    value is observable in the transcript.
    """
    project = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(project)
    rtl_dir.mkdir(parents=True)
    # Minimal DUT (the oracle run requires rtl/ to be non-empty).
    (rtl_dir / "synthtop.v").write_text(
        "module synthtop(input wire clk, output wire [7:0] q);\n"
        "  assign q = 8'h00;\n"
        "endmodule\n")

    sim_fs = _pl.sim_full_stack_dir(project)
    sim_fs.mkdir(parents=True)
    tb = sim_fs / "tb_synthtop_oracle.v"
    # The TB loads firmware via a RELATIVE $readmemh — hex lives next to TB.
    tb.write_text(
        "`timescale 1ns/1ps\n"
        "module tb_synthtop_oracle;\n"
        "  reg [7:0] fw [0:3];\n"
        "  integer _pass; integer _total;\n"
        "  initial begin\n"
        "    _pass = 0; _total = 1;\n"
        "    $readmemh(\"fw.hex\", fw);\n"
        "    #1;\n"
        "    $display(\"FW0=%02x\", fw[0]);\n"
        "    if (fw[0] === 8'hAB) begin\n"
        "      _pass = 1;\n"
        "      $display(\"ORACLE_VECTOR fw_load PASS\");\n"
        "    end else begin\n"
        "      $display(\"ORACLE_VECTOR fw_load FAIL (mem unloaded)\");\n"
        "    end\n"
        "    $display(\"ORACLE_TB_DONE pass=%0d/%0d\", _pass, _total);\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    # Firmware sits next to the TB (the parent of the run cwd) — the exact
    # defect topology: vvp runs in oracle_run/, hex is in sim_full_stack/.
    (sim_fs / "fw.hex").write_text("AB\n")

    res = p2._run_oracle_tb(project, "synthtop", tb,
                            track_reason="test", t0=p2.time.time(),
                            container="vibeic-eda")
    assert res is not None, "oracle run returned None (no simulator?)"

    run_dir = sim_fs / "oracle_run"
    # END STATE 1: the staged run cwd contains the hex.
    assert (run_dir / "fw.hex").is_file(), (
        "the $readmemh-referenced hex was NOT staged into the run cwd")
    # END STATE 2: the firmware actually loaded (mem != X) → oracle PASS.
    transcript = (run_dir / "oracle.log").read_text()
    assert "FW0=ab" in transcript, (
        f"firmware did not load (mem stayed X); transcript:\n{transcript}")
    assert res.status == "PASS", (
        f"oracle run did not PASS despite staged firmware: {res.detail[:400]}")
    assert res.extras.get("functional_verified") is True


@pytest.mark.skipif(
    shutil.which("iverilog") is None or shutil.which("vvp") is None,
    reason="iverilog/vvp not available")
def test_476_regression_without_staging_firmware_would_not_load(tmp_path):
    """Regression witness: prove the DEFECT topology (hex in parent, cwd in
    child) is exactly what the fix addresses — running vvp directly in a child
    cwd does NOT see the parent hex, but the staged copy does.
    """
    sim_fs = tmp_path / "sim_full_stack"
    sim_fs.mkdir(parents=True)
    tb = sim_fs / "tb_z_oracle.v"
    tb.write_text(
        "`timescale 1ns/1ps\n"
        "module tb_z_oracle;\n"
        "  reg [7:0] fw [0:1];\n"
        "  initial begin\n"
        "    $readmemh(\"fw.hex\", fw);\n"
        "    #1 $display(\"FW0=%02x\", fw[0]);\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    (sim_fs / "fw.hex").write_text("5C\n")
    run_dir = sim_fs / "oracle_run"
    run_dir.mkdir()

    vvp = run_dir / "z.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(tb)],
                   check=True, capture_output=True)

    # BEFORE staging: cwd=run_dir cannot see parent's fw.hex → mem stays X.
    before = subprocess.run(["vvp", str(vvp)], cwd=run_dir,
                            capture_output=True, text=True)
    assert "fw0=xx" in before.stdout.lower(), (
        "expected unloaded memory before staging; got: " + before.stdout)

    # AFTER staging via the contract: the firmware loads.
    staged = p2._stage_readmem_files(tb, run_dir)
    assert "fw.hex" in staged
    after = subprocess.run(["vvp", str(vvp)], cwd=run_dir,
                           capture_output=True, text=True)
    assert "fw0=5c" in after.stdout.lower(), (
        "firmware did not load after staging; got: " + after.stdout)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
