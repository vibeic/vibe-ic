"""ORGANIC #774 — duplicate-module crash-gate (#639) scanned the REACHABLE
closure only, so a prunable-tail duplicate returned a false-PASS then
crashed yosys-slang raw.

現象 (round-14 v1.0.85, opentitan_aes reused-IP, adversarial-verified NEW):
the #639 duplicate-module crash-gate scans only the reachable closure of
synth_top (catalog_glue_closure_resolver.resolve, ~L325-326 pre-fix), but
`design_one_shot_runner._select_asic_rtl_sources` feeds the FULL flat glob
to yosys_synth (prune is advisory — "never auto-drop"). So a duplicate-
module pair classified PRUNABLE is invisible to the gate (duplicates=[],
verdict=PASS) yet still handed to synth → yosys-slang aborts raw with
"duplicate definition", with no plugin diagnostic.

  resolve('chip_top', 285 files) → verdict=PASS, duplicates=[], reachable=98,
  prunable=187. module tlul_adapter_vh declared in BOTH
  tlul_adapter_shim.sv AND tlul_adapter_vh.sv — both PRUNABLE → gate blind.

Fix: run the duplicate-module scan over the ENTIRE staged set the runner
feeds to synth (full flat glob), surfaced as a hard-gated STAGED_DUPLICATE
verdict distinct from #639's reachable-only DUPLICATE so neither facet
masks the other. step_yosys_synth now gates on STAGED_DUPLICATE too.

§4.05 NO-LEAK (load-bearing): clean staging still PASSes; a clean but
over-broad prunable tail still PASSes (no false-FAIL); and the genuine
defect the relaxation must NOT mask — a reachable-closure duplicate — is
STILL caught as DUPLICATE (no #639 regression). Distinct from #639
(reachable-only): this is the advisory-prunable-tail facet. Bucket A.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import catalog_glue_closure_resolver as R  # noqa: E402

_RESOLVER = PROG / "catalog_glue_closure_resolver.py"


def _stage(d: Path, files: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


# A flat vendor bundle shaped like the 現象: a clean reachable design
# (chip_top -> leaf), PLUS a duplicate-module pair (tlul_adapter_vh declared
# in BOTH tlul_adapter_shim.sv AND tlul_adapter_vh.sv) that is in the
# PRUNABLE tail — NOT reachable from chip_top. Pre-fix the gate is blind to
# it; the runner still feeds the full glob to synth → yosys-slang crash.
_PRUNABLE_TAIL_DUP = {
    "chip_top.sv": (
        "module chip_top (input clk, input rst_n, output [7:0] out);\n"
        "  cipher_core u_core (.clk(clk), .rst_n(rst_n), .out(out));\n"
        "endmodule\n"),
    "cipher_core.sv": (
        "module cipher_core (input clk, input rst_n, output [7:0] out);\n"
        "  assign out = {8{clk}};\n"
        "endmodule\n"),
    # The duplicate-module pair — BOTH files are unreachable from chip_top
    # (nobody instantiates tlul_adapter_vh) → classified PRUNABLE.
    "tlul_adapter_vh.sv": (
        "module tlul_adapter_vh (input clk);\nendmodule\n"),
    "tlul_adapter_shim.sv": (
        "module tlul_adapter_vh (input clk); // shim variant\nendmodule\n"),
}


# ===========================================================================
# NEW-PATH: the prunable-tail duplicate is now caught as STAGED_DUPLICATE.
# ===========================================================================
def test_prunable_tail_duplicate_is_caught_staged_not_false_pass(tmp_path):
    """The #774 fix: a duplicate-module pair in the PRUNABLE tail (both
    files unreachable from chip_top) is no longer a false-PASS. It surfaces
    as STAGED_DUPLICATE — distinct from #639's reachable-only DUPLICATE —
    with the canonical-vs-variant diagnosis intact, so the runner can FAIL
    early instead of letting yosys-slang crash raw."""
    d = _stage(tmp_path / "vendor_rtl", _PRUNABLE_TAIL_DUP)
    rep = R.resolve("chip_top", d)
    assert rep["verdict"] == "STAGED_DUPLICATE", rep
    assert rep["verdict"] != "PASS"
    # Both defining files are in the prunable tail (the gate was blind).
    assert rep["files_prunable"] == 2
    dup = next(x for x in rep["duplicates"]
               if x["module"] == "tlul_adapter_vh")
    assert dup["scope"] == "staged"
    assert Path(dup["canonical"]).name == "tlul_adapter_vh.sv"
    assert "tlul_adapter_shim.sv" in [Path(v).name for v in dup["variants"]]
    assert "duplicate-module" in dup["message"]
    assert "PRUNABLE tail" in dup["message"]


def test_step_yosys_synth_gates_prunable_tail_duplicate(tmp_path,
                                                        monkeypatch):
    """Integration: stage the prunable-tail duplicate into the runner's
    rtl/ layout and invoke the REAL step_yosys_synth. The pre-synth gate
    must FAIL with the #774 STAGED_DUPLICATE diagnostic, and (load-bearing)
    yosys must NOT have been invoked — the crash is prevented, not triaged
    after it aborts."""
    import design_one_shot_runner as P2

    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    _stage(rtl, _PRUNABLE_TAIL_DUP)

    def _boom(*a, **k):
        raise AssertionError(
            "yosys/_run must NOT be invoked — the #774 gate should "
            "short-circuit on the prunable-tail duplicate-module defect")
    monkeypatch.setattr(P2, "_run", _boom)

    res = P2.step_yosys_synth(proj, top_name="chip_top")
    assert res.status == "FAIL"
    assert "#774" in res.detail or "STAGED_DUPLICATE" in res.detail \
        or "CATALOG_GLUE_CLOSURE" in res.detail
    assert "duplicate-module" in res.detail
    cg = res.extras.get("catalog_glue_closure", {})
    assert cg.get("verdict") == "STAGED_DUPLICATE"


# ===========================================================================
# §4.05 NO-LEAK — the genuine defect the relaxation must NOT mask, plus the
# two "clean must still PASS" directions.
# ===========================================================================
def test_no_leak_reachable_closure_dup_still_duplicate(tmp_path):
    """§4.05 (load-bearing): the genuine #639 defect the #774 widening must
    NOT mask — a duplicate-module pair INSIDE the reachable closure — is
    STILL caught as the top-level DUPLICATE verdict (not silently widened
    or downgraded to STAGED_DUPLICATE). No #639 regression."""
    files = {
        "chip_top.sv": (
            "module chip_top (input clk, output o);\n"
            "  tlul_adapter_vh u (.clk(clk));\n"
            "  assign o = clk;\n"
            "endmodule\n"),
        "tlul_adapter_vh.sv": (
            "module tlul_adapter_vh (input clk);\nendmodule\n"),
        "tlul_adapter_shim.sv": (
            "module tlul_adapter_vh (input clk); // shim\nendmodule\n"),
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("chip_top", d)
    assert rep["verdict"] == "DUPLICATE", rep
    dup = next(x for x in rep["duplicates"]
               if x["module"] == "tlul_adapter_vh")
    assert dup["scope"] == "reachable"


def test_no_leak_split_reachable_prunable_dup_is_duplicate(tmp_path):
    """§4.05 (load-bearing): when a duplicate spans one reachable + one
    prunable file, the reachable (#639) facet MUST win — verdict DUPLICATE,
    never downgraded to STAGED_DUPLICATE. The prunable widening must not be
    able to demote a reachable crash defect."""
    files = {
        "chip_top.sv": (
            "module chip_top (input clk, output o);\n"
            "  dup_mod u (.clk(clk));\n"
            "  assign o = clk;\n"
            "endmodule\n"),
        "dup_mod.sv": "module dup_mod (input clk);\nendmodule\n",
        "dup_mod_shim.sv": "module dup_mod (input clk); // shim\nendmodule\n",
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("chip_top", d)
    assert rep["verdict"] == "DUPLICATE", rep
    dup = next(x for x in rep["duplicates"] if x["module"] == "dup_mod")
    assert dup["scope"] == "reachable"


def test_no_leak_clean_over_broad_tail_still_passes(tmp_path):
    """§4.05 (the other direction): a clean bundle with an over-broad
    PRUNABLE tail but NO duplicate-module defect must still PASS — the #774
    widening scans the whole staged set but must not false-FAIL a merely
    over-broad (yet duplicate-free) bundle."""
    files = {
        "top.sv": (
            "module top (input a, output b);\n"
            "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": ("module leaf (input a, output b); "
                    "assign b = ~a; endmodule\n"),
        "unrelated_ip.sv": "module unrelated_ip (input x); endmodule\n",
        "another_ip.sv": "module another_ip (input y); endmodule\n",
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("top", d)
    assert rep["verdict"] == "PASS", rep["duplicates"]
    assert rep["files_prunable"] == 2
    assert rep["duplicates"] == []


def test_no_leak_header_redeclare_in_tail_not_flagged(tmp_path):
    """§4.05: an include-only header (.svh) in the prunable tail that
    textually contains a module name is NOT a duplicate-module bundle
    defect — only synthesizable .sv/.v files count, even under the widened
    full-staged-set scan. Must still PASS."""
    files = {
        "top.sv": (
            "module top (input a, output b);\n"
            "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": ("module leaf (input a, output b); "
                    "assign b = ~a; endmodule\n"),
        "leaf_decl.svh": "`define LEAF_NOTE module leaf is canonical\n",
        "unrelated.sv": "module unrelated (input x); endmodule\n",
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("top", d)
    assert rep["verdict"] == "PASS", rep["duplicates"]


# ===========================================================================
# #478 END-STATE: DIRECT-write a tmp_path artifact and invoke the REAL
# program via subprocess; assert the returncode end-state (rc=1 = a real
# bundle defect that would crash synth).
# ===========================================================================
def test_endstate_real_program_subprocess_returncode(tmp_path):
    """#478 end-state: DIRECT-write the prunable-tail-duplicate staging
    artifact to tmp_path, run the REAL catalog_glue_closure_resolver.py via
    subprocess, and assert the process END-STATE — returncode == 1 (a real
    duplicate-module bundle defect that would crash synth) and the
    STAGED_DUPLICATE diagnostic in stdout. Not a stub: the actual program
    on a real on-disk artifact."""
    vendor = tmp_path / "vendor_rtl"
    vendor.mkdir(parents=True)
    for name, text in _PRUNABLE_TAIL_DUP.items():
        (vendor / name).write_text(text)
    json_out = tmp_path / "closure.json"

    proc = subprocess.run(
        [sys.executable, str(_RESOLVER),
         "--top", "chip_top", str(vendor),
         "--json", str(json_out)],
        capture_output=True, text=True, timeout=60)

    # END-STATE 1: returncode == 1 (real defect; 0=PASS, 2=arg/empty error).
    assert proc.returncode == 1, (
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    # END-STATE 2: the program surfaced the staged-duplicate diagnostic.
    assert "STAGED_DUPLICATE" in proc.stdout
    assert "tlul_adapter_vh" in proc.stdout
    # END-STATE 3: the JSON artifact records the hard-gated verdict.
    import json as _json
    report = _json.loads(json_out.read_text())
    assert report["verdict"] == "STAGED_DUPLICATE"
    assert any(d["scope"] == "staged" for d in report["duplicates"])


def test_endstate_clean_program_subprocess_returncode_zero(tmp_path):
    """#478 end-state (no-leak direction): a clean staging artifact run
    through the REAL program END-STATE returncode == 0 (PASS). Confirms the
    widened scan does not flip a clean bundle to a non-zero crash verdict."""
    vendor = tmp_path / "vendor_rtl"
    vendor.mkdir(parents=True)
    (vendor / "top.sv").write_text(
        "module top (input a, output b);\n"
        "  leaf u (.a(a), .b(b));\nendmodule\n")
    (vendor / "leaf.sv").write_text(
        "module leaf (input a, output b); assign b = ~a; endmodule\n")

    proc = subprocess.run(
        [sys.executable, str(_RESOLVER), "--top", "top", str(vendor)],
        capture_output=True, text=True, timeout=60)

    assert proc.returncode == 0, (
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    assert "verdict: PASS" in proc.stdout


# ── Step-2.7 remediation: TOP_NOT_FOUND must not short-circuit the scan ──────
def test_774r2_top_not_found_with_staged_dup_is_staged_duplicate(tmp_path):
    """Finding (Step-2.7): a staged duplicate whose top does NOT resolve must
    STILL surface as STAGED_DUPLICATE — the unconditional full-staged scan runs
    even on the TOP_NOT_FOUND branch (else the prunable-tail dup crashes synth)."""
    files = {
        "a.sv": "module dup_mod(input a); endmodule\n",
        "b.sv": "module dup_mod(input b); endmodule\n",
        "c.sv": "module other(input c); endmodule\n",
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("no_such_top", d)
    assert rep["verdict"] == "STAGED_DUPLICATE", rep
    assert any(x["module"] == "dup_mod" for x in rep["duplicates"]), rep


def test_774r2_noleak_top_not_found_no_dup_stays_top_not_found(tmp_path):
    """§4.05 NO-LEAK: TOP_NOT_FOUND with NO duplicate stays TOP_NOT_FOUND (the
    unconditional scan does not manufacture a false STAGED_DUPLICATE)."""
    files = {"a.sv": "module m1(input a); endmodule\n",
             "b.sv": "module m2(input b); endmodule\n"}
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("no_such_top", d)
    assert rep["verdict"] == "TOP_NOT_FOUND", rep
