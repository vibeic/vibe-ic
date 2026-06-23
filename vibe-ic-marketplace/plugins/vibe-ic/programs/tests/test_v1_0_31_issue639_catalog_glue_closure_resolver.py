"""ORGANIC #639 — REUSED-IP / catalog-glue staging has no instantiation-
closure pruning or duplicate-module dedup.

現象: for a REUSED-IP processor / crypto-accelerator class whose vendor
RTL is dropped FLAT (one directory, no per-IP rtl_files manifest), the
catalog-glue WAIVE fallback stages every *.sv/*.v as-is and the runner
source selector (_select_asic_rtl_sources) flat-globs all of them.
Selection is purely additive — it never computes the transitive
module/package instantiation closure FROM the authored chip_top to drop
unrelated sibling IPs, and no program detects duplicate-module
definitions (two files declaring the same module name) on the staged
synth set. Two failure facets: (1) unrelated IPs drag in macros/packages
the synth define-set never satisfies → spurious elaboration errors;
(2) a vendor bundle duplicate-module defect crashes yosys-slang with a
raw "duplicate definition" abort and no diagnostic.

Fix: new catalog_glue_closure_resolver.py walks the transitive
module/package/macro instantiation closure from the top, reports the
reachable (stage) vs prunable (over-broad tail) split, and detects
duplicate-module bundle defects on the reachable closure (naming the
canonical file vs the variant/shim). step_yosys_synth runs it as a
PRE-synth gate so the duplicate-module crash is caught — with a precise
diagnostic — before the expensive elaborate.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import catalog_glue_closure_resolver as R  # noqa: E402


# ---------------------------------------------------------------------------
# A flat vendor RTL bundle shaped like the 現象:
#   chip_top -> cipher_core -> { cipher_pkg, `PRIM_FLOP_SPARSE_FSM (macro in
#   an .svh) -> prim_sparse_fsm_flop, tlul_adapter_vh }
#   PLUS unrelated sibling IPs (ascon/flash/sha2/keccak) that are NOT
#   reachable from chip_top, PLUS a real duplicate-module bundle defect
#   (tlul_adapter_vh declared in BOTH tlul_adapter_vh.sv and the shim).
# ---------------------------------------------------------------------------
_FILES = {
    "chip_top.sv": (
        "module chip_top (input clk, input rst_n, output [7:0] out);\n"
        "  cipher_core u_core (.clk(clk), .rst_n(rst_n), .out(out));\n"
        "endmodule\n"),
    "cipher_core.sv": (
        "module cipher_core (input clk, input rst_n, output [7:0] out);\n"
        "  import cipher_pkg::*;\n"
        "  `PRIM_FLOP_SPARSE_FSM(u_fsm, clk, rst_n)\n"
        "  tlul_adapter_vh u_tl (.clk(clk));\n"
        "endmodule\n"),
    "cipher_pkg.sv": (
        "package cipher_pkg;\n"
        "  typedef enum logic [1:0] {A, B} state_e;\n"
        "endpackage\n"),
    # include-only macro header (.svh): its `define instantiates a module,
    # so the closure must chain prim_sparse_fsm_flop in via the macro body.
    "prim_macros.svh": (
        "`define PRIM_FLOP_SPARSE_FSM(name, c, r) "
        "prim_sparse_fsm_flop name (.clk(c), .rst_n(r));\n"),
    "prim_sparse_fsm_flop.sv": (
        "module prim_sparse_fsm_flop (input clk, input rst_n);\n"
        "endmodule\n"),
    # real duplicate-module bundle defect — same module in two files.
    "tlul_adapter_vh.sv": (
        "module tlul_adapter_vh (input clk);\nendmodule\n"),
    "tlul_adapter_shim.sv": (
        "module tlul_adapter_vh (input clk); // shim variant\nendmodule\n"),
    # unrelated sibling IPs — the over-broad tail (NOT reachable).
    "ascon_core.sv": "module ascon_core (input clk); endmodule\n",
    "flash_ctrl.sv": "module flash_ctrl (input clk); endmodule\n",
    "sha2_core.sv": "module sha2_core (input clk); endmodule\n",
    "keccak_round.sv": "module keccak_round (input clk); endmodule\n",
}


def _stage(d: Path, files: dict) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / name).write_text(text)
    return d


# ===========================================================================
# Resolver-level: closure prune + duplicate-module detection (the fix).
# ===========================================================================
def test_closure_prunes_unrelated_ips(tmp_path):
    """The 4 unrelated sibling IPs are NOT reachable from chip_top and are
    reported as prunable; the real closure (top + cipher_core + pkg + the
    macro-instantiated flop + its .svh header + the adapter) is reachable."""
    d = _stage(tmp_path / "vendor_rtl", _FILES)
    rep = R.resolve("chip_top", d)
    reach = {Path(p).name for p in rep["reachable"]}
    prune = {Path(p).name for p in rep["prunable"]}
    # Reachable closure must contain the real design + the macro chain.
    assert "chip_top.sv" in reach
    assert "cipher_core.sv" in reach
    assert "cipher_pkg.sv" in reach
    assert "prim_macros.svh" in reach          # macro header chained in
    assert "prim_sparse_fsm_flop.sv" in reach  # macro-instantiated module
    # The over-broad tail is pruned, NOT staged.
    for ip in ("ascon_core.sv", "flash_ctrl.sv",
               "sha2_core.sv", "keccak_round.sv"):
        assert ip in prune, f"{ip} should be prunable"
        assert ip not in reach


def test_duplicate_module_bundle_defect_diagnosed(tmp_path):
    """The vendor bundle duplicate-module defect (tlul_adapter_vh declared
    in two reachable files) is surfaced with a precise diagnostic naming
    the canonical file (filename matches module name) and the variant to
    drop — instead of letting yosys-slang crash opaquely."""
    d = _stage(tmp_path / "vendor_rtl", _FILES)
    rep = R.resolve("chip_top", d)
    assert rep["verdict"] == "DUPLICATE"
    dup = next(x for x in rep["duplicates"]
               if x["module"] == "tlul_adapter_vh")
    assert Path(dup["canonical"]).name == "tlul_adapter_vh.sv"
    assert "tlul_adapter_shim.sv" in [Path(v).name for v in dup["variants"]]
    assert "duplicate-module" in dup["message"]


# ===========================================================================
# NEGATIVE no-leak: empty / foreign / clean inputs must NOT pass-through.
# ===========================================================================
def test_empty_dir_is_failsafe_not_pass(tmp_path):
    """An EMPTY staging dir must NOT be reported PASS — verdict EMPTY (a
    floor: an empty doc never sails through)."""
    d = tmp_path / "empty"
    d.mkdir()
    rep = R.resolve("chip_top", d)
    assert rep["verdict"] == "EMPTY"
    assert rep["verdict"] != "PASS"


def test_top_not_found_is_failsafe_not_pass(tmp_path):
    """A top module not defined in any staged file must NOT pass — a foreign /
    under-populated set is still caught. ORGANIC #774 round-2: the
    duplicate-module scan now runs UNCONDITIONALLY over the full staged set even
    when the top does not resolve; `_FILES` contains a duplicate
    `tlul_adapter_vh`, so the (more specific, equally fail-safe) verdict is
    STAGED_DUPLICATE — never PASS."""
    d = _stage(tmp_path / "vendor_rtl", _FILES)
    rep = R.resolve("no_such_top_module", d)
    assert rep["verdict"] in ("TOP_NOT_FOUND", "STAGED_DUPLICATE")
    assert rep["verdict"] != "PASS"
    assert rep["reachable"] == []


def test_clean_closure_passes_no_false_dup(tmp_path):
    """NEGATIVE no-leak (the other direction): a clean bundle with no
    unrelated IP and no duplicate-module defect must PASS — the gate does
    not over-fire on a legitimate closure."""
    clean = {
        "top.sv": (
            "module top (input a, output b);\n"
            "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": "module leaf (input a, output b); assign b = ~a; endmodule\n",
    }
    d = _stage(tmp_path / "clean", clean)
    rep = R.resolve("top", d)
    assert rep["verdict"] == "PASS", rep["duplicates"]
    assert rep["files_prunable"] == 0
    assert rep["duplicates"] == []


def test_header_redeclare_not_flagged_as_duplicate(tmp_path):
    """NEGATIVE no-leak: a module name appearing in an include-only header
    (.svh) plus one real .sv is NOT a duplicate-module bundle defect — only
    synthesizable .sv/.v files count, so we do not false-FAIL a normal
    macro/declaration header."""
    files = {
        "top.sv": (
            "module top (input a, output b);\n"
            "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": "module leaf (input a, output b); assign b = ~a; endmodule\n",
        # a header that textually contains `module leaf` inside a comment/
        # macro is not a second synthesizable definition.
        "leaf_decl.svh": "`define LEAF_NOTE module leaf is the canonical leaf\n",
    }
    d = _stage(tmp_path / "vendor_rtl", files)
    rep = R.resolve("top", d)
    # leaf is declared in leaf.sv (synth) and (textually) leaf_decl.svh
    # (header) — but the header is excluded from duplicate reporting.
    assert rep["verdict"] == "PASS", rep["duplicates"]


# ===========================================================================
# Integration: step_yosys_synth PRE-synth gate FAILs on the duplicate
# defect with the #639 diagnostic BEFORE the expensive yosys elaborate.
# ===========================================================================
def test_step_yosys_synth_pre_gates_duplicate(tmp_path, monkeypatch):
    """Stage the duplicate-module bundle into the runner's rtl/ layout and
    invoke the REAL step_yosys_synth. The PRE-synth #639 gate must FAIL
    with the catalog-glue closure diagnostic, and (load-bearing) yosys must
    NOT have been invoked — the crash is prevented, not triaged after."""
    import design_one_shot_runner as P2

    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    _stage(rtl, _FILES)

    # Hard-fail if yosys is ever shelled out: the gate must short-circuit
    # BEFORE the elaborate. (_run is the runner's subprocess wrapper.)
    def _boom(*a, **k):
        raise AssertionError(
            "yosys/_run must NOT be invoked — #639 gate should "
            "short-circuit on the duplicate-module defect")
    monkeypatch.setattr(P2, "_run", _boom)

    res = P2.step_yosys_synth(proj, top_name="chip_top")
    assert res.status == "FAIL"
    assert "#639" in res.detail or "CATALOG_GLUE_CLOSURE" in res.detail
    assert "duplicate-module" in res.detail
    cg = res.extras.get("catalog_glue_closure", {})
    assert cg.get("verdict") == "DUPLICATE"


def test_step_yosys_synth_no_false_gate_on_clean(tmp_path, monkeypatch):
    """NEGATIVE no-leak integration: a clean closure (no duplicate) must
    NOT trip the #639 gate — step_yosys_synth proceeds past it to the
    actual yosys invocation (which we stub to a sentinel)."""
    import design_one_shot_runner as P2

    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    clean = {
        "chip_top.sv": (
            "module chip_top (input a, output b);\n"
            "  leaf u (.a(a), .b(b));\nendmodule\n"),
        "leaf.sv": "module leaf (input a, output b); assign b = ~a; endmodule\n",
    }
    _stage(rtl, clean)

    calls = {"n": 0}

    def _sentinel_run(*a, **k):
        calls["n"] += 1
        # Pretend yosys ran and failed for an UNRELATED reason so the test
        # asserts the #639 gate did NOT fire (we got past it to _run).
        return (1, "", "stub yosys ran")
    monkeypatch.setattr(P2, "_run", _sentinel_run)

    res = P2.step_yosys_synth(proj, top_name="chip_top")
    # The #639 gate must NOT have produced the FAIL — yosys was reached.
    assert calls["n"] >= 1, "step must proceed past the #639 gate to yosys"
    assert "CATALOG_GLUE_CLOSURE" not in res.detail
